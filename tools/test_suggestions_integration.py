#!/usr/bin/env python3
"""Private-bus acceptance of the real C++ service. Synthetic observations never reach a phone.

dbus-run-session -- python3 tools/test_suggestions_integration.py BINARY KB [PREVIEW SHOT]
Uses a fake voice transport only; storage, scheduling, D-Bus, QML and feedback are production code.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time


def fake_voice():
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    info = Gio.DBusNodeInfo.new_for_xml('''<node><interface name="com.rungic.VoiceAgent">
      <method name="InvestigateSuggestion"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
      <method name="ApplySuggestion"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
      <method name="StopSuggestion"><arg type="s" direction="in"/></method>
      <signal name="Event"><arg type="s"/></signal></interface></node>''')

    def emit(event):
        bus.emit_signal(None, '/com/rungic/VoiceAgent', 'com.rungic.VoiceAgent', 'Event',
                        GLib.Variant('(s)', (json.dumps(event),)))
        return False

    def call(connection, sender, path, interface, method, params, invocation):
        if method in ('InvestigateSuggestion', 'ApplySuggestion'):
            suggestion = params.unpack()[0]
            conversation = 'test-' + suggestion
            emit({'type': 'suggestion-started', 'suggestion': suggestion, 'conversation': conversation})
            invocation.return_value(GLib.Variant('(s)', (json.dumps({'conversation': conversation}),)))
            GLib.timeout_add(80, emit, {'type': 'agent-message', 'conversation': conversation, 'final': True,
                                       'text': '检查已完成，未修改系统；下一步需要实机验证。'})
            GLib.timeout_add(120, emit, {'type': 'agent-finished', 'conversation': conversation})
        else:
            invocation.return_value(None)

    bus.register_object('/com/rungic/VoiceAgent', info.interfaces[0], call, None, None)
    Gio.bus_own_name_on_connection(bus, 'com.rungic.VoiceAgent', Gio.BusNameOwnerFlags.NONE, None, None)
    loop = GLib.MainLoop()
    threading.Thread(target=loop.run, daemon=True).start()
    return bus, loop


def main():
    binary, kb = map(str, sys.argv[1:3])
    voice = fake_voice()
    with tempfile.TemporaryDirectory(prefix='rungic-care-') as directory:
        root = Path(directory)
        env = dict(os.environ, RUNGIC_SUGGESTIONS_STATE=str(root / 'state'),
                   RUNGIC_SUGGESTIONS_FEED=str(root / 'feed.json'), RUNGIC_COMPATIBILITY=kb,
                   QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', QT_QUICK_CONTROLS_STYLE='Basic')
        items = []
        for n in range(40):
            items.append({'id': hashlib.sha256(f'fixture:{n}'.encode()).hexdigest()[:24],
                          'source': 'fixture', 'title': f'播放体验可以进一步检查 · {n + 1}',
                          'body': '发现播放过程中持续掉帧。原因尚未确认，可以先让 Agent 检查适配情况。',
                          'kind': 'optimization', 'severity': 0,
                          'evidence': {'package': 'synthetic-player', 'version': '1.0', 'private': 'do-not-export'}})
        (root / 'feed.json').write_text(json.dumps({'schema': 1, 'generated': int(time.time()),
                                                   'items': items, 'sources': ['fixture']}))

        def cli(*args, error=False):
            p = subprocess.run([binary, *args], env=env, text=True, capture_output=True, timeout=20)
            assert (p.returncode != 0 if error else p.returncode == 0), (args, p.stderr, p.stdout)
            return json.loads(p.stdout) if p.stdout.strip() else {}

        def wait(predicate):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    if predicate():
                        return
                except (AssertionError, KeyError):
                    pass
                time.sleep(.05)
            raise AssertionError('Timed out waiting for state')

        log = open(root / 'service.log', 'w+')
        process = subprocess.Popen([binary, '--service'], env=env, stdout=log, stderr=log)
        try:
            wait(lambda: len(cli('list')['items']) == 40)
            first, second = items[0]['id'], items[1]['id']
            cli('act', first, 'snooze', json.dumps({'at': int(time.time()) + 2}))
            assert cli('get', first)['state'] == 'snoozed'
            process.terminate(); process.wait(5)
            process = subprocess.Popen([binary, '--service'], env=env, stdout=log, stderr=log)
            wait(lambda: cli('get', first)['state'] == 'snoozed')
            time.sleep(2)
            cli('refresh')
            wait(lambda: cli('get', first)['state'] == 'new')
            cli('act', second, 'dismiss'); cli('refresh')
            assert cli('get', second)['state'] == 'dismissed'
            cli('act', first, 'investigate')
            wait(lambda: cli('get', first)['state'] == 'attention')
            assert '未修改系统' in cli('get', first)['result']
            assert 'error' in cli('act', first, 'apply', error=True)
            cli('update', first, json.dumps({'plan': '具体变更', 'verification': '实际功能复查', 'rollback': '恢复原设置'}))
            cli('act', first, 'apply')
            wait(lambda: cli('get', first)['state'] == 'attention')
            report = cli('feedback', first)
            data = Path(report['path']).read_text()
            assert 'do-not-export' not in data and 'false' in data
            cli('update', first, json.dumps({'upstream': {'state': 'merged', 'url': 'https://example.org/issues/1'}}))
            assert cli('get', first)['state'] == 'attention'
            if len(sys.argv) >= 5:
                subprocess.run([sys.argv[3], sys.argv[4]], env=env, check=True, timeout=20)
            print('PASS: 40 cards, restart, snooze, dedup/mute, Agent handoff/result, private feedback, independent upstream state, QML preview')
        finally:
            process.terminate(); process.wait(5)
            log.seek(0)
            text = log.read()
            if 'save:' in text:
                raise AssertionError(text)
            voice[1].quit()


if __name__ == '__main__':
    main()
