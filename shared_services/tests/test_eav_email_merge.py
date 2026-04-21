"""Tests for EAV email placeholder merge (ACS-adjacent, post-template)."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase


class ExtractEavPlaceholdersTests(SimpleTestCase):
    def test_extracts_lead_field_and_intake_names(self):
        from shared_services.eav_email_merge import extract_eav_placeholders

        text = 'Hi {{ lead_field.Custom_1 }} and {{INTAKE.foo_bar}} end'
        lf, intake = extract_eav_placeholders(text)
        self.assertEqual(set(lf), {'custom_1'})
        self.assertEqual(set(intake), {'foo_bar'})

    def test_empty_text(self):
        from shared_services.eav_email_merge import extract_eav_placeholders

        self.assertEqual(extract_eav_placeholders(''), (frozenset(), frozenset()))


class ApplyEavPlaceholdersTests(SimpleTestCase):
    def test_noop_non_lead(self):
        from shared_services.eav_email_merge import apply_eav_placeholders

        text = '{{ lead_field.x }}'
        self.assertEqual(apply_eav_placeholders(text=text, lead={'lead': 1}), text)

    def test_noop_lead_without_campaign_id(self):
        from external_models.models.external_references import Lead
        from shared_services.eav_email_merge import apply_eav_placeholders

        lead = Lead()
        lead.campaign_id = None
        lead.campaign = None
        self.assertEqual(apply_eav_placeholders(text='{{ lead_field.a }}', lead=lead), '{{ lead_field.a }}')

    def test_replaces_from_queryset(self):
        from external_models.models.external_references import Campaign, Lead
        from shared_services.eav_email_merge import apply_eav_placeholders

        campaign = Campaign(
            pk=9,
            account_id=1,
            campaign_model_id=2,
            name='',
        )

        lead = Lead()
        lead.campaign_id = 9
        lead.campaign = campaign

        row = MagicMock()
        row.field_definition.api_name = 'MyField'
        row.value = 'resolved'

        with patch('external_models.models.lead_eav.LeadFieldValue.objects') as lf_objects:
            lf_objects.filter.return_value.select_related.return_value = [row]
            out = apply_eav_placeholders(
                text='X {{ lead_field.myfield }} Y',
                lead=lead,
            )
        self.assertEqual(out, 'X resolved Y')
        lf_objects.filter.assert_called_once()

    def test_apply_eav_placeholders_to_email_parts_preserves_none_text(self):
        from external_models.models.external_references import Lead
        from shared_services.eav_email_merge import apply_eav_placeholders_to_email_parts

        lead = MagicMock(spec=Lead)
        lead.campaign_id = 1
        lead.campaign = MagicMock(id=1, account_id=1, campaign_model_id=1)

        def passthrough(*, text, lead):
            return text

        with patch('shared_services.eav_email_merge.apply_eav_placeholders', side_effect=passthrough):
            sub, html, txt = apply_eav_placeholders_to_email_parts(
                subject='S',
                html_body='<p>H</p>',
                text_body=None,
                lead=lead,
            )
        self.assertIsNone(txt)
        self.assertEqual(sub, 'S')
        self.assertEqual(html, '<p>H</p>')


class SendFromEmailConfigEavWireTests(SimpleTestCase):
    def test_outbound_acs_calls_eav_after_acs(self):
        from external_models.models.channel_configs import EmailConfig
        from shared_services.email import email_dispatch as ed

        ver = MagicMock()
        ver.status = 'approved'
        ver.html_body = '<p>{{lead.first_name}}</p>'
        ver.text_body = ''

        ec = MagicMock()
        ec.from_endpoint_id = 1
        ec.from_endpoint = MagicMock()
        ec.from_endpoint.value = 'from@x.com'
        ec.email_content_mode = EmailConfig.MODE_OUTBOUND_ACS
        ec.hosted_template_version = ver
        ec.from_name = None
        ec.reply_to = None

        fake_lead = object()

        with patch.object(ed, 'replace_template_variables', side_effect=lambda s, ctx: s.replace('{{lead.first_name}}', 'Ada')):
            with patch.object(ed, '_lead_for_eav', return_value=fake_lead):
                with patch.object(ed, 'apply_eav_placeholders_to_email_parts') as eav_parts:
                    eav_parts.side_effect = lambda **kw: (kw['subject'], kw['html_body'], kw['text_body'])
                    with patch.object(ed, 'send_from_contact_endpoint', return_value=MagicMock(message_id='m1')):
                        from shared_services.email.email_dispatch import send_from_email_config

                        send_from_email_config(
                            ec,
                            to_email='to@x.com',
                            context={'lead': fake_lead},
                            subject_override='Hi {{lead.first_name}}',
                        )
        eav_parts.assert_called_once()
        kwargs = eav_parts.call_args.kwargs
        self.assertEqual(kwargs['lead'], fake_lead)
        self.assertIn('Ada', kwargs['subject'])
        self.assertIn('Ada', kwargs['html_body'])
