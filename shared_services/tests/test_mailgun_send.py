"""Tests for native Mailgun send helpers (mocked HTTP)."""

from unittest.mock import MagicMock, patch

import requests

from django.test import SimpleTestCase


class MailgunMessageSendTests(SimpleTestCase):
    def test_send_mailgun_message_posts_form(self):
        from shared_services.email.mailgun import send_mailgun_message

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.json.return_value = {'id': '<abc@test.mailgun.org>', 'message': 'Queued'}
        mock_resp.raise_for_status = MagicMock()

        # requests is imported inside send_mailgun_message, so patch the library target.
        with patch('requests.post', return_value=mock_resp) as post:
            result = send_mailgun_message(
                api_key='key-xxx',
                domain='mg.example.com',
                api_base='https://api.mailgun.net/v3',
                to_email='to@example.com',
                subject='Hi',
                html_body='<p>Hello</p>',
                text_body=None,
                from_email='From <from@mg.example.com>',
                reply_to='support@example.com',
                tags=['bulk', 'nurture'],
            )

        self.assertEqual(result.message_id, '<abc@test.mailgun.org>')
        post.assert_called_once()
        ca = post.call_args
        self.assertIn('auth', ca.kwargs)
        self.assertEqual(ca.kwargs['auth'], ('api', 'key-xxx'))
        raw = ca.kwargs['data']
        data = dict(raw) if isinstance(raw, list) else raw
        self.assertEqual(data['from'], 'From <from@mg.example.com>')
        self.assertEqual(data['to'], 'to@example.com')
        self.assertEqual(data['subject'], 'Hi')
        self.assertEqual(data['html'], '<p>Hello</p>')
        self.assertEqual(data['h:Reply-To'], 'support@example.com')
        self.assertEqual(data['text'], 'Hello')
        self.assertNotIn('<', data['text'])

    def test_send_mailgun_message_plain_text_when_explicit_empty_string(self):
        from shared_services.email.mailgun import send_mailgun_message

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.json.return_value = {'id': '<x@mailgun>', 'message': 'Queued'}
        mock_resp.raise_for_status = MagicMock()

        with patch('requests.post', return_value=mock_resp) as post:
            send_mailgun_message(
                api_key='key-xxx',
                domain='mg.example.com',
                api_base='https://api.mailgun.net/v3',
                to_email='to@example.com',
                subject='Hi',
                html_body='<div><p>Line1</p><p>Line2</p></div>',
                text_body='',
                from_email='from@mg.example.com',
            )
        data = dict(post.call_args.kwargs['data'])
        self.assertEqual(data['text'], 'Line1\nLine2')

    def test_send_mailgun_message_list_unsubscribe_extra_headers(self):
        from shared_services.email.mailgun import send_mailgun_message

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.json.return_value = {'id': '<x@mailgun>', 'message': 'Queued'}
        mock_resp.raise_for_status = MagicMock()

        with patch('requests.post', return_value=mock_resp) as post:
            send_mailgun_message(
                api_key='key-xxx',
                domain='mg.example.com',
                api_base='https://api.mailgun.net/v3',
                to_email='to@example.com',
                subject='Hi',
                html_body='<p>x</p>',
                text_body=None,
                from_email='from@mg.example.com',
                extra_headers={
                    'List-Unsubscribe': '<mailto:u@example.com>, <https://example.com/unsub>',
                    'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
                },
            )
        data = dict(post.call_args.kwargs['data'])
        self.assertEqual(
            data['h:List-Unsubscribe'],
            '<mailto:u@example.com>, <https://example.com/unsub>',
        )
        self.assertEqual(data['h:List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click')

    def test_list_unsubscribe_extra_headers_builder(self):
        from shared_services.email.mailgun import list_unsubscribe_extra_headers

        self.assertEqual(list_unsubscribe_extra_headers(None, None), {})
        h = list_unsubscribe_extra_headers('list@example.com', 'https://example.com/u', None)
        self.assertEqual(
            h['List-Unsubscribe'],
            '<mailto:list@example.com>, <https://example.com/u>',
        )
        self.assertEqual(h['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click')
        self.assertNotIn(
            'List-Unsubscribe-Post',
            list_unsubscribe_extra_headers('list@example.com', None, None),
        )
        no_post = list_unsubscribe_extra_headers(
            'list@example.com',
            'https://example.com/u',
            False,
        )
        self.assertIn('List-Unsubscribe', no_post)
        self.assertNotIn('List-Unsubscribe-Post', no_post)

    def test_send_mailgun_message_retries_on_503_then_succeeds(self):
        from shared_services.email.mailgun import send_mailgun_message

        bad = MagicMock()
        bad.status_code = 503

        ok = MagicMock()
        ok.status_code = 200
        ok.raise_for_status = MagicMock()
        ok.json.return_value = {'id': '<retry-ok@mailgun>', 'message': 'Queued'}

        with patch('requests.post', side_effect=[bad, ok]) as post:
            with patch('shared_services.email.mailgun.time.sleep'):
                result = send_mailgun_message(
                    api_key='key-xxx',
                    domain='mg.example.com',
                    api_base='https://api.mailgun.net/v3',
                    to_email='to@example.com',
                    subject='Hi',
                    html_body='<p>Hello</p>',
                    text_body=None,
                    from_email='from@mg.example.com',
                )

        self.assertEqual(result.message_id, '<retry-ok@mailgun>')
        self.assertEqual(post.call_count, 2)

    def test_send_mailgun_message_does_not_retry_on_401(self):
        from shared_services.email.mailgun import send_mailgun_message

        bad = MagicMock()
        bad.status_code = 401
        bad.text = 'unauthorized'
        bad.raise_for_status.side_effect = requests.HTTPError(response=bad)

        with patch('requests.post', return_value=bad) as post:
            with self.assertRaises(requests.HTTPError):
                send_mailgun_message(
                    api_key='key-xxx',
                    domain='mg.example.com',
                    api_base='https://api.mailgun.net/v3',
                    to_email='to@example.com',
                    subject='Hi',
                    html_body='<p>Hello</p>',
                    text_body=None,
                    from_email='from@mg.example.com',
                )

        post.assert_called_once()


class EffectiveEmailSubjectTests(SimpleTestCase):
    def test_subject_from_config_wins(self):
        from shared_services.email.email_dispatch import effective_email_subject

        ec = MagicMock()
        ec.subject = '  Config subject  '
        ec.email_content_mode = 'inline'
        ec.hosted_template_version_id = None
        self.assertEqual(effective_email_subject(ec), 'Config subject')

    def test_subject_from_version_when_config_empty(self):
        from shared_services.email.email_dispatch import effective_email_subject

        ver = MagicMock()
        ver.subject_text = '  Version subj  '
        ec = MagicMock()
        ec.subject = ''
        ec.email_content_mode = 'outbound_acs'
        ec.hosted_template_version_id = 1
        ec.hosted_template_version = ver
        self.assertEqual(effective_email_subject(ec), 'Version subj')


class SendFromEmailConfigInlineSubjectTests(SimpleTestCase):
    def test_inline_merged_body_subject_replaces_template_variables(self):
        from shared_services.email import email_dispatch
        from shared_services.email.email_dispatch import send_from_email_config

        lead = MagicMock()
        lead.first_name = 'Ada'

        endpoint = MagicMock()
        endpoint.value = 'from@example.com'

        ec = MagicMock()
        ec.from_endpoint_id = 1
        ec.from_endpoint = endpoint
        ec.email_content_mode = 'inline'
        ec.from_name = None
        ec.reply_to = None

        def fake_replace(s, ctx):
            self.assertIn('lead', ctx)
            return s.replace('{{lead.first_name}}', lead.first_name)

        with patch.object(email_dispatch, 'replace_template_variables', side_effect=fake_replace):
            with patch.object(
                email_dispatch,
                'send_from_contact_endpoint',
                return_value=MagicMock(success=True),
            ) as send_fn:
                send_from_email_config(
                    ec,
                    to_email='to@example.com',
                    subject_override='Hi {{lead.first_name}}',
                    merged_html_body='<p>x</p>',
                    context={'lead': lead},
                )

        send_fn.assert_called_once()
        self.assertEqual(send_fn.call_args.kwargs['subject'], 'Hi Ada')
