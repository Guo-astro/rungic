"""The Codex usage provider (docs/research/95): read-only, provider-shaped, no fabricated API-key quotas."""
import ast
import json
from pathlib import Path
import types
import unittest
from unittest.mock import Mock
root = Path(__file__).resolve().parents[2]
source = root / 'plasma/voice-agent/rungic_voice_agent.py'
tree = ast.parse(source.read_text())
node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VoiceAgent')
node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in {'usage', 'usage_limits', 'on_notification'}]
namespace = {'AGENT_MODEL': 'test-model', '_': lambda text: text, 'json': json}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
# Keys every provider object may carry (the rest is dropped by the service anyway).
PROVIDER_KEYS = {'accountKey', 'status', 'account', 'model', 'tokens', 'limits', 'error', 'tokenEvents'}


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
        self.agent.usage_push = Mock()

    def pushed(self, method):
        return [c.args[1:] for c in self.agent.usage_push.call_args_list if c.args[0] == method]

    def test_api_key_never_requests_subscription_quota(self):
        self.agent.server.call.return_value = {'account': {'type': 'apiKey'}}
        data = self.agent.usage()
        self.assertNotIn('limits', data)
        self.assertEqual(self.agent.server.call.call_count, 1)
        self.assertEqual(data['account'], {'kind': 'api-key', 'label': 'API Key', 'plan': ''})
        self.assertEqual(data['status'], 'ready')
        self.assertLessEqual(set(data), PROVIDER_KEYS)

    def test_subscription_returns_real_nullable_fields(self):
        self.agent.server.call.side_effect = [
            {'account': {'type': 'chatgpt', 'planType': 'plus', 'email': 'do-not-publish'}},
            {'rateLimits': {'primary': {'usedPercent': 23, 'resetsAt': None, 'windowDurationMins': 300}}},
            {'summary': {'lifetimeTokens': None}}]
        data = self.agent.usage()
        self.assertEqual(data['account'], {'kind': 'subscription', 'label': 'ChatGPT', 'plan': 'plus'})
        self.assertEqual(data['limits'], [{'id': 'codex.primary', 'label': 'codex', 'windowMinutes': 300,
                                           'usedPercent': 23, 'resetsAt': None}])
        self.assertIsNone(data['tokens']['account'])
        self.assertNotIn('do-not-publish', json.dumps(data))
        self.assertLessEqual(set(data), PROVIDER_KEYS)

    def test_limit_buckets_become_named_limits(self):
        read = {'rateLimitsByLimitId': {'codex': {'limitName': 'Codex', 'primary': {'usedPercent': 3.0, 'windowDurationMins': 300, 'resetsAt': 200},
                                                  'secondary': {'usedPercent': 40, 'windowDurationMins': 10080, 'resetsAt': 900}},
                                        'other': {'primary': None, 'secondary': {'usedPercent': 'n/a'}}}}
        limits = namespace['VoiceAgent'].usage_limits(read)
        self.assertEqual([l['id'] for l in limits], ['codex.primary', 'codex.secondary'])
        self.assertEqual(limits[1]['label'], 'Codex')
        self.assertEqual(limits[1]['windowMinutes'], 10080)

    def test_failed_quota_read_is_an_error_without_invented_limits(self):
        self.agent.server.call.side_effect = [{'account': {'type': 'chatgpt'}}, RuntimeError('timeout')]
        data = self.agent.usage()
        self.assertNotIn('limits', data)
        self.assertEqual(data['error'], 'Account usage has not updated yet')

    def test_signed_out_and_offline_states(self):
        self.agent.server.call.return_value = {'account': None}
        self.assertEqual(self.agent.usage()['status'], 'signed-out')
        self.agent.server = None
        self.assertEqual(self.agent.usage()['status'], 'offline')
        self.agent.agent_busy = True
        self.agent.server = Mock()
        self.agent.server.call.return_value = {'account': {'type': 'apiKey'}}
        self.assertEqual(self.agent.usage()['status'], 'working')

    def test_account_change_during_read_discards_response(self):
        self.agent.server.call.return_value = {'account': {'type': 'apiKey'}}
        self.agent.usage_identity.side_effect = ['opaque-a', 'opaque-b']
        with self.assertRaises(RuntimeError): self.agent.usage()

    def test_background_thread_token_is_recorded(self):
        self.agent.on_notification('thread/tokenUsage/updated', {'threadId': 'other', 'turnId': 't',
                                    'tokenUsage': {'total': {'totalTokens': 300}, 'last': {'totalTokens': 100}}})
        (provider, text), = self.pushed('RecordTokens')
        self.assertEqual(provider, 'codex')
        self.assertEqual(json.loads(text), {'accountKey': 'opaque-a', 'session': 'other', 'turn': 't', 'total': 300, 'last': 100})
        self.assertEqual(len(self.agent.usage_tokens), 1)
        self.agent.emit_raw.assert_not_called()  # no longer a chat event

    def test_quota_and_turn_changes_ask_for_a_new_read(self):
        self.agent.on_notification('account/rateLimits/updated', {'rateLimits': {'primary': None}})
        self.agent.on_notification('turn/started', {'threadId': 'other', 'turn': {'id': 't'}})
        self.assertEqual(self.pushed('ProviderChanged'), [('codex',), ('codex',)])

    def test_tokens_from_another_account_never_return(self):
        self.agent.server.call.return_value = {'account': {'type': 'apiKey'}}
        self.agent.usage_tokens = {'x': {'accountKey': 'opaque-b'}}
        self.assertEqual(self.agent.usage()['tokenEvents'], [])

    def test_late_usage_keeps_account_from_turn_start(self):
        self.agent.usage_accounts[('other', 'old-turn')] = 'opaque-old'
        self.agent.on_notification('thread/tokenUsage/updated', {'threadId': 'other', 'turnId': 'old-turn',
                                    'tokenUsage': {'total': {'totalTokens': 300}, 'last': {'totalTokens': 100}}})
        self.assertEqual(json.loads(self.pushed('RecordTokens')[0][1])['accountKey'], 'opaque-old')
        self.agent.server.call.return_value = {'account': {'type': 'apiKey'}}
        self.assertEqual(self.agent.usage()['tokenEvents'], [])


class DescriptorTests(unittest.TestCase):
    def test_codex_descriptor_names_the_agents_usage_method(self):
        d = json.loads((root / 'plasma/voice-agent/agent-usage/codex.json').read_text())
        self.assertEqual((d['schema'], d['id']), (1, 'codex'))
        interface = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                                          and getattr(n.targets[0], 'id', '') == 'INTERFACE'))
        self.assertIn(f'<interface name="{d["dbus"]["interface"]}">', interface)
        self.assertIn(f'<method name="{d["dbus"]["method"]}"><arg type="s" direction="out"/></method>', interface)
        consts = {n.targets[0].id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
                  and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant)}
        self.assertEqual(d['dbus']['service'], consts['BUS_NAME'])
        self.assertEqual(d['dbus']['path'], consts['OBJECT_PATH'])
        build = (root / 'plasma/packaging/rungic-voice-agent/build.sh').read_text()
        self.assertIn('/usr/share/rungic/agent-usage/providers/codex.json', build)
