"""The existing Codex bridge exposes read-only usage, not fabricated API-key quotas."""
import ast
import json
from pathlib import Path
import types
import unittest
from unittest.mock import Mock
source = Path(__file__).resolve().parents[2] / 'plasma/voice-agent/rungic_voice_agent.py'
node = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'VoiceAgent')
node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in {'usage', 'on_notification'}]
namespace = {'AGENT_MODEL': 'test-model', '_': lambda text: text}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)

class UsageBridgeTests(unittest.TestCase):
    def setUp(self):
        self.agent = namespace['VoiceAgent']()
        self.agent.agent_busy = False
        self.agent.usage_identity = Mock(return_value='opaque-a')
        self.agent.usage_tokens = {}
        self.agent.usage_accounts = {}
        self.agent.server = Mock()
        self.agent.thread_id = 'active'
        self.agent.emit_raw = Mock()

    def test_api_key_never_requests_subscription_quota(self):
        self.agent.server.call.return_value = {'account': {'type': 'apiKey'}}
        data = self.agent.usage()
        self.assertNotIn('rateLimits', data)
        self.assertEqual(self.agent.server.call.call_count, 1)
        self.assertEqual(data['authMode'], 'apiKey')

    def test_subscription_returns_real_nullable_fields(self):
        self.agent.server.call.side_effect = [
            {'account': {'type': 'chatgpt', 'planType': 'plus', 'email': 'do-not-publish'}},
            {'rateLimits': {'primary': {'usedPercent': 23, 'resetsAt': None}}},
            {'summary': {'lifetimeTokens': None}}]
        data = self.agent.usage()
        self.assertIsNone(data['rateLimits']['rateLimits']['primary']['resetsAt'])
        self.assertNotIn('do-not-publish', json.dumps(data))

    def test_account_change_during_read_discards_response(self):
        self.agent.server.call.return_value = {'account': {'type': 'apiKey'}}
        self.agent.usage_identity.side_effect = ['opaque-a', 'opaque-b']
        with self.assertRaises(RuntimeError): self.agent.usage()

    def test_background_thread_token_is_forwarded(self):
        self.agent.on_notification('thread/tokenUsage/updated', {'threadId': 'other', 'turnId': 't',
                                    'tokenUsage': {'total': {'totalTokens': 300}, 'last': {'totalTokens': 100}}})
        self.assertEqual(self.agent.emit_raw.call_args.args[0]['accountKey'], 'opaque-a')
        self.assertEqual(len(self.agent.usage_tokens), 1)

    def test_quota_update_requests_full_snapshot(self):
        self.agent.on_notification('account/rateLimits/updated', {'rateLimits': {'primary': None}})
        self.assertEqual(self.agent.emit_raw.call_args.args[0]['type'], 'usage-changed')

    def test_tokens_from_another_account_never_return(self):
        self.agent.server.call.return_value = {'account': {'type': 'apiKey'}}
        self.agent.usage_tokens = {'x': {'accountKey': 'opaque-b'}}
        self.assertEqual(self.agent.usage()['tokens'], [])

    def test_late_usage_keeps_account_from_turn_start(self):
        self.agent.usage_accounts[('other', 'old-turn')] = 'opaque-old'
        self.agent.on_notification('thread/tokenUsage/updated', {'threadId': 'other', 'turnId': 'old-turn',
                                    'tokenUsage': {'total': {'totalTokens': 300}, 'last': {'totalTokens': 100}}})
        self.assertEqual(self.agent.emit_raw.call_args.args[0]['accountKey'], 'opaque-old')
        self.agent.server.call.return_value = {'account': {'type': 'apiKey'}}
        self.assertEqual(self.agent.usage()['tokens'], [])
