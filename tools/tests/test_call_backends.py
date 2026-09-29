#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The caller chooses a transport; prerequisite probes never choose another."""
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'plasma/voice-agent'))
from call_backends import capabilities, resolve


class CallBackendsTest(unittest.TestCase):
    def test_explicit_and_existing_clients(self):
        for params, expected in [
            ({'backend':'cellular','number':'10000'}, ('cellular','cellular')),
            ({'app':'cellular','number':'10000'}, ('cellular','cellular')),
            ({'number':'10000'}, ('cellular','cellular')),
            ({'backend':'app','app':'wechat'}, ('app','wechat')),
            ({'app':'wechat'}, ('app','wechat')),
            ({'backend':'app','app':'another-app'}, ('app','another-app')),
        ]:
            with self.subTest(params=params):
                self.assertEqual(resolve(params), expected)

    def test_missing_or_conflicting_intent_never_defaults_to_wechat(self):
        for params in ({}, {'contact':'某人'}, {'backend':'app'},
                       {'backend':'cellular','app':'wechat','number':'10000'},
                       {'app':'wechat','number':'10000'}, {'backend':'unknown'},
                       {'backend':'cellular','number':'not a number'},
                       {'backend':'app','app':'wechat; anything'}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                resolve(params)

    def test_capability_failure_does_not_select_another_backend(self):
        def unavailable():
            raise OSError('unreachable')
        result = capabilities(probe=unavailable, router_available=True)
        self.assertEqual(result['selection'], 'user-request-only')
        phone = result['backends']['cellular']
        self.assertFalse(phone['reachable'])
        self.assertIsNone(phone['audioInterfaceAvailable'])
        self.assertFalse(phone['endToEndVerified'])
        self.assertEqual(resolve({'backend':'cellular','number':'10000'}), ('cellular','cellular'))

    def test_interface_is_not_end_to_end_verification(self):
        accounts = [{'id':'first'}, {'id':'second'}]
        result = capabilities(key_configured=True, router_available=False,
                              probe=lambda: {'protocol':1,'phoneState':0,'audioCapable':True,'accounts':accounts})
        phone = result['backends']['cellular']
        self.assertTrue(result['keyConfigured'])
        self.assertTrue(phone['reachable'])
        self.assertTrue(phone['audioInterfaceAvailable'])
        self.assertFalse(phone['endToEndVerified'])
        self.assertFalse(phone['busy'])
        self.assertEqual(phone['accounts'], accounts)
        self.assertFalse(phone['privateVoiceInstructions'])
        self.assertFalse(phone['independentMonitor'])

    def test_protocol_mismatch_is_not_usable(self):
        result = capabilities(probe=lambda: {'protocol':2,'audioCapable':True}, router_available=False)
        self.assertFalse(result['backends']['cellular']['reachable'])


if __name__ == '__main__':
    unittest.main()
