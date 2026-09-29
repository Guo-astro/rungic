#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Lifecycle regressions using the actual call classes, without API/socket/device I/O."""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'plasma/voice-agent'))
# GI/WebSocket are runtime adapters. These tests never create them, and can run
# in restricted CI without a sound server, GI packages or a network connection.
gi = types.ModuleType('gi'); gi.require_version = lambda *args: None
repository = types.ModuleType('gi.repository')
repository.GLib = types.SimpleNamespace(idle_add=lambda fn,*args: fn(*args))
repository.Gst = types.SimpleNamespace()
with patch.dict(sys.modules, {'gi':gi, 'gi.repository':repository, 'websocket':types.ModuleType('websocket')}):
    import call_proxy
    import cellular_call


class CellularStateTest(unittest.TestCase):
    def new_call(self):
        self.events = []
        with patch.object(call_proxy, 'JEV_KEYS', ()):
            call = cellular_call.CellularCall(lambda e, keep=True: self.events.append(e), Mock(), number='10000')
        call.player = Mock()
        call.phase, call.active = 'agent', True
        call.call_id = 'our-call'
        return call

    def test_unbound_bridge_idle_is_a_confirmed_end(self):
        call = self.new_call()
        call.phase, call.active = 'user', False
        # Android unbinds InCallService when its last Call goes away.
        with patch.object(cellular_call, 'request', return_value={'available':False, 'phoneState':0, 'calls':[]}):
            call._watch_user_call()
        self.assertEqual(call.phase, 'ended')
        self.assertEqual(self.events[-1]['type'], 'call-ended')

    def test_missing_or_recreated_bridge_is_not_hangup(self):
        for state in ({'available':False,'phoneState':2,'calls':[]},
                      {'available':True,'phoneState':2,'calls':[{'id':'new-id','state':4}]},
                      {}):
            self.assertFalse(cellular_call.confirmed_ended(state, 'our-call'))

    def test_explicit_disconnect_belongs_to_our_call(self):
        self.assertTrue(cellular_call.confirmed_ended({'calls':[{'id':'ours','state':7}]}, 'ours'))
        self.assertFalse(cellular_call.confirmed_ended({'calls':[{'id':'other','state':7}]}, 'ours'))

    def test_cancel_before_realtime_ready_never_dials(self):
        call = self.new_call()
        call.ready.set()
        call.ending = 'end'
        with patch.object(cellular_call,'request') as request:
            with self.assertRaises(RuntimeError):
                call.dial()
            request.assert_not_called()

    def test_ringback_does_not_open_audio(self):
        call = self.new_call()
        ringing = {'phoneState':2,'calls':[{'id':'our-call','state':1}]}
        with patch.object(cellular_call, 'request', side_effect=[ringing, {'phoneState':0}]), \
             patch.object(cellular_call.time, 'sleep'):
            call._watch()
        call.player.open.assert_not_called()
        self.assertEqual(call.phase, 'ended')

    def test_ui_failure_keeps_the_audio_call_running(self):
        call = self.new_call()
        active = {'phoneState':2,'calls':[{'id':'our-call','state':4}]}
        def request(op, **fields):
            if op == 'show-linux':
                raise RuntimeError('activity not allowed')
            return active
        # One observation is enough: end the loop at its wait, without changing
        # the call's active flag (which a UI error must not change).
        with patch.object(cellular_call, 'request', side_effect=request), \
             patch.object(cellular_call.threading, 'Thread') as worker, \
             patch.object(cellular_call.time, 'sleep', side_effect=lambda _: setattr(call,'phase','test-exit')):
            call._watch()
        call.player.open.assert_called_once()
        call.player.close.assert_not_called()
        worker.assert_called_once()         # opening still scheduled
        self.assertTrue(call.active)
        self.assertTrue(any(e['type']=='call-note' for e in self.events))

    def test_recreated_call_id_hands_over_never_redials(self):
        call = self.new_call()
        replacement = {'phoneState':2,'calls':[{'id':'new-id','state':4}]}
        with patch.object(cellular_call, 'request', return_value=replacement) as request, \
             patch.object(cellular_call.threading,'Thread'), patch.object(cellular_call.time,'sleep'):
            call._watch()
        self.assertEqual(call.phase, 'user')
        self.assertFalse(call.active)
        self.assertEqual(call.call_id,'our-call')
        self.assertTrue(all(args.args == ('status',) for args in request.call_args_list))
        call.player.close.assert_called_once()

    def test_handover_is_idempotent(self):
        call = self.new_call()
        with patch.object(cellular_call.threading,'Thread') as worker:
            call.take_over(); call.take_over()
        self.assertEqual(call.phase, 'user')
        self.assertEqual(len([e for e in self.events if e['type']=='call-phase']),1)
        call.player.close.assert_called_once()
        worker.assert_called_once()


if __name__ == '__main__':
    unittest.main()
