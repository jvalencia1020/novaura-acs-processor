"""Tests for native Postmark send helpers (mocked HTTP)."""

from unittest.mock import MagicMock, patch

import requests

from django.test import SimpleTestCase


class PostmarkMessageSendTests(SimpleTestCase):
    def test_send_postmark_email_posts_json(self):
        from shared_services.email.postmark import POSTMARK_API, send_postmark_email

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {'MessageID': 'abc-123', 'Message': 'OK'}

        with patch('requests.post', return_value=mock_resp) as post:
            result = send_postmark_email(
                server_token='server-token',
                to_email='to@example.com',
                subject='Hi',
                html_body='<p>Hello</p>',
                text_body='Hello explicit',
                from_email='From <from@example.com>',
                reply_to='support@example.com',
                tags=['bulk', 'nurture'],
                message_stream='broadcast',
            )

        self.assertEqual(result.message_id, 'abc-123')
        post.assert_called_once()
        ca = post.call_args
        self.assertEqual(ca.args[0], POSTMARK_API)
        self.assertEqual(ca.kwargs['headers']['X-Postmark-Server-Token'], 'server-token')
        body = ca.kwargs['json']
        self.assertEqual(body['From'], 'From <from@example.com>')
        self.assertEqual(body['To'], 'to@example.com')
        self.assertEqual(body['Subject'], 'Hi')
        self.assertEqual(body['HtmlBody'], '<p>Hello</p>')
        self.assertEqual(body['TextBody'], 'Hello explicit')
        self.assertEqual(body['ReplyTo'], 'support@example.com')
        self.assertEqual(body['MessageStream'], 'broadcast')
        self.assertEqual(body['Tag'], 'bulk,nurture')

    def test_send_postmark_email_list_unsubscribe_extra_headers(self):
        from shared_services.email.postmark import send_postmark_email

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {'MessageID': 'x-postmark', 'Message': 'OK'}

        with patch('requests.post', return_value=mock_resp) as post:
            send_postmark_email(
                server_token='server-token',
                to_email='to@example.com',
                subject='Hi',
                html_body='<p>x</p>',
                text_body=None,
                from_email='from@example.com',
                extra_headers={
                    'List-Unsubscribe': '<mailto:u@example.com>, <https://example.com/unsub>',
                    'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
                },
            )

        headers = post.call_args.kwargs['json']['Headers']
        self.assertEqual(
            headers,
            [
                {
                    'Name': 'List-Unsubscribe',
                    'Value': '<mailto:u@example.com>, <https://example.com/unsub>',
                },
                {'Name': 'List-Unsubscribe-Post', 'Value': 'List-Unsubscribe=One-Click'},
            ],
        )

    def test_send_postmark_email_plain_text_generated_from_html(self):
        from shared_services.email.postmark import send_postmark_email

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {'MessageID': 'x-postmark', 'Message': 'OK'}

        with patch('requests.post', return_value=mock_resp) as post:
            send_postmark_email(
                server_token='server-token',
                to_email='to@example.com',
                subject='Hi',
                html_body='<div><p>Line1</p><p>Line2</p></div>',
                text_body='',
                from_email='from@example.com',
            )

        body = post.call_args.kwargs['json']
        self.assertEqual(body['TextBody'], 'Line1\nLine2')
        self.assertNotIn('<', body['TextBody'])

    def test_adapter_uses_config_for_stream_tracking_and_metadata(self):
        from shared_services.email.postmark import PostmarkEmailAdapter

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {'MessageID': 'x-postmark', 'Message': 'OK'}

        adapter = PostmarkEmailAdapter()
        with patch('requests.post', return_value=mock_resp) as post:
            adapter.send(
                credentials={'server_token': 'server-token'},
                config={
                    'transactional_stream': 'broadcast',
                    'track_opens': True,
                    'track_links': 'HtmlAndText',
                    'metadata': {'endpoint_id': 17, 'ignored_none': None},
                },
                to_email='to@example.com',
                subject='Hi',
                html_body='<p>Hello</p>',
                text_body=None,
                from_email='from@example.com',
            )

        body = post.call_args.kwargs['json']
        self.assertEqual(body['MessageStream'], 'broadcast')
        self.assertIs(body['TrackOpens'], True)
        self.assertEqual(body['TrackLinks'], 'HtmlAndText')
        self.assertEqual(body['Metadata'], {'endpoint_id': '17'})

    def test_adapter_defaults_message_stream_to_broadcast(self):
        from shared_services.email.postmark import PostmarkEmailAdapter

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {'MessageID': 'x-postmark', 'Message': 'OK'}

        adapter = PostmarkEmailAdapter()
        with patch('requests.post', return_value=mock_resp) as post:
            adapter.send(
                credentials={'api_key': 'server-token'},
                config={},
                to_email='to@example.com',
                subject='Hi',
                html_body='<p>Hello</p>',
                text_body=None,
                from_email='from@example.com',
            )

        self.assertEqual(post.call_args.kwargs['json']['MessageStream'], 'broadcast')

    def test_send_postmark_email_tags_are_limited_and_joined(self):
        from shared_services.email.postmark import send_postmark_email

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {'MessageID': 'x-postmark', 'Message': 'OK'}

        tags = [f'tag{i}' for i in range(12)]
        with patch('requests.post', return_value=mock_resp) as post:
            send_postmark_email(
                server_token='server-token',
                to_email='to@example.com',
                subject='Hi',
                html_body='<p>Hello</p>',
                text_body=None,
                from_email='from@example.com',
                tags=tags,
            )

        self.assertEqual(post.call_args.kwargs['json']['Tag'], ','.join(tags[:10]))

    def test_adapter_raises_when_credentials_missing(self):
        from shared_services.email.postmark import PostmarkEmailAdapter

        adapter = PostmarkEmailAdapter()
        with self.assertRaisesMessage(ValueError, 'Postmark credentials missing api_key or server_token'):
            adapter.send(
                credentials={},
                config={},
                to_email='to@example.com',
                subject='Hi',
                html_body='<p>Hello</p>',
                text_body=None,
                from_email='from@example.com',
            )

    def test_send_postmark_email_retries_on_503_then_succeeds(self):
        from shared_services.email.postmark import send_postmark_email

        bad = MagicMock()
        bad.status_code = 503
        bad.ok = False
        bad.headers = {}

        ok = MagicMock()
        ok.status_code = 200
        ok.ok = True
        ok.json.return_value = {'MessageID': 'retry-ok', 'Message': 'OK'}

        with patch('requests.post', side_effect=[bad, ok]) as post:
            with patch('shared_services.email.postmark.time.sleep'):
                result = send_postmark_email(
                    server_token='server-token',
                    to_email='to@example.com',
                    subject='Hi',
                    html_body='<p>Hello</p>',
                    text_body=None,
                    from_email='from@example.com',
                )

        self.assertEqual(result.message_id, 'retry-ok')
        self.assertEqual(post.call_count, 2)

    def test_send_postmark_email_retries_on_429_then_succeeds(self):
        from shared_services.email.postmark import send_postmark_email

        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.ok = False
        rate_limited.headers = {'Retry-After': '0'}

        ok = MagicMock()
        ok.status_code = 200
        ok.ok = True
        ok.json.return_value = {'MessageID': 'retry-ok', 'Message': 'OK'}

        with patch('requests.post', side_effect=[rate_limited, ok]) as post:
            with patch('shared_services.email.postmark.time.sleep'):
                result = send_postmark_email(
                    server_token='server-token',
                    to_email='to@example.com',
                    subject='Hi',
                    html_body='<p>Hello</p>',
                    text_body=None,
                    from_email='from@example.com',
                )

        self.assertEqual(result.message_id, 'retry-ok')
        self.assertEqual(post.call_count, 2)

    def test_send_postmark_email_retries_on_timeout_then_succeeds(self):
        from shared_services.email.postmark import send_postmark_email

        ok = MagicMock()
        ok.status_code = 200
        ok.ok = True
        ok.json.return_value = {'MessageID': 'retry-ok', 'Message': 'OK'}

        with patch('requests.post', side_effect=[requests.Timeout(), ok]) as post:
            with patch('shared_services.email.postmark.time.sleep'):
                result = send_postmark_email(
                    server_token='server-token',
                    to_email='to@example.com',
                    subject='Hi',
                    html_body='<p>Hello</p>',
                    text_body=None,
                    from_email='from@example.com',
                )

        self.assertEqual(result.message_id, 'retry-ok')
        self.assertEqual(post.call_count, 2)

    def test_send_postmark_email_retries_on_connection_error_then_succeeds(self):
        from shared_services.email.postmark import send_postmark_email

        ok = MagicMock()
        ok.status_code = 200
        ok.ok = True
        ok.json.return_value = {'MessageID': 'retry-ok', 'Message': 'OK'}

        with patch('requests.post', side_effect=[requests.ConnectionError(), ok]) as post:
            with patch('shared_services.email.postmark.time.sleep'):
                result = send_postmark_email(
                    server_token='server-token',
                    to_email='to@example.com',
                    subject='Hi',
                    html_body='<p>Hello</p>',
                    text_body=None,
                    from_email='from@example.com',
                )

        self.assertEqual(result.message_id, 'retry-ok')
        self.assertEqual(post.call_count, 2)

    def test_send_postmark_email_logs_error_code_on_http_failure(self):
        from shared_services.email.postmark import send_postmark_email

        bad = MagicMock()
        bad.status_code = 422
        bad.ok = False
        bad.text = '{"ErrorCode":406,"Message":"You tried to send to inactive recipients"}'
        bad.json.return_value = {
            'ErrorCode': 406,
            'Message': 'You tried to send to inactive recipients',
        }

        with patch('requests.post', return_value=bad):
            with self.assertLogs('shared_services.email.postmark', level='ERROR') as logs:
                with self.assertRaises(requests.HTTPError):
                    send_postmark_email(
                        server_token='server-token',
                        to_email='to@example.com',
                        subject='Hi',
                        html_body='<p>Hello</p>',
                        text_body=None,
                        from_email='from@example.com',
                    )

        joined = '\n'.join(logs.output)
        self.assertIn('postmark_send_fail', joined)
        self.assertIn('ErrorCode=406', joined)

    def test_registry_returns_postmark_adapter(self):
        from shared_services.email.postmark import PostmarkEmailAdapter
        from shared_services.email.registry import get_email_provider_adapter

        self.assertIsInstance(get_email_provider_adapter('postmark'), PostmarkEmailAdapter)
