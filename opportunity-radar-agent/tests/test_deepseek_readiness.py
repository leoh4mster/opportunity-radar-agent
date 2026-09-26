import unittest
from unittest.mock import patch

from app.core.config import Settings
from app.services.llm_gateway import LLMGateway, LLMResponseFormatError
from evaluation.check_deepseek import check_connection


class DeepSeekReadinessTest(unittest.TestCase):
    def test_probe_requires_consent_before_constructing_client(self):
        with patch('evaluation.check_deepseek.LLMGateway') as client:
            with self.assertRaisesRegex(ValueError, '--allow-network'):
                check_connection()
            client.assert_not_called()

    def test_probe_never_falls_back_without_credentials(self):
        with patch('evaluation.check_deepseek.LLMGateway') as client:
            client.return_value.is_configured.return_value = False
            with self.assertRaisesRegex(ValueError, 'DEEPSEEK_API_KEY'):
                check_connection(True)
            client.return_value.chat.assert_not_called()

    def test_probe_uses_only_one_structured_fictional_request(self):
        with patch('evaluation.check_deepseek.LLMGateway') as client:
            gateway = client.return_value
            gateway.is_configured.return_value = True
            gateway.chat.return_value = '{"location":"线上"}'
            gateway.debug_config.return_value = {'active_model': 'deepseek-flash'}
            self.assertTrue(check_connection(True)['ok'])
            gateway.chat.assert_called_once()
            kwargs = gateway.chat.call_args.kwargs
            self.assertEqual(kwargs['max_retries'], 0)
            self.assertEqual(kwargs['response_format'], {'type': 'json_object'})
            self.assertIn('虚构', kwargs['messages'][1]['content'])

    def test_gateway_sends_explicit_thinking_and_token_limit(self):
        gateway = LLMGateway()
        gateway.settings = Settings(_env_file=None, deepseek_api_key='test-only',
                                    llm_model='deepseek-flash', llm_thinking='disabled', llm_max_tokens=512)
        with patch.object(gateway, '_post_json', return_value={
            'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}]
        }) as post:
            gateway.chat([{'role': 'user', 'content': 'JSON'}], max_retries=0)
            payload = post.call_args.args[2]
            self.assertEqual(payload['model'], 'deepseek-flash')
            self.assertEqual(payload['thinking'], {'type': 'disabled'})
            self.assertEqual(payload['max_tokens'], 512)

    def test_token_truncation_is_not_silently_accepted_as_success(self):
        with self.assertRaises(LLMResponseFormatError):
            LLMGateway()._extract_content({'choices': [
                {'message': {'content': '{"looks":"valid"}'}, 'finish_reason': 'length'}]})

