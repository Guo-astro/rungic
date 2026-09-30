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
      <method name="InvestigateSuggestion"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
      <method name="ApplySuggestion"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
      <method name="StopSuggestion"><arg type="s" direction="in"/><arg type="s" direction="in"/></method>
      <method name="Usage"><arg type="s" direction="out"/></method>
      <method name="SuggestionTask"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
      <signal name="Event"><arg type="s"/></signal></interface></node>''')

    def emit(event):
        bus.emit_signal(None, '/com/rungic/VoiceAgent', 'com.rungic.VoiceAgent', 'Event',
                        GLib.Variant('(s)', (json.dumps(event),)))
        return False

    running = {}
    def call(connection, sender, path, interface, method, params, invocation):
        if method == 'Usage':
            data = {'accountKey': 'fixture-only', 'authMode': 'apiKey' if '--api' in sys.argv else 'chatgpt', 'model': 'fixture-model', 'activity': 'ready',
                    'tokens': [{'accountKey': 'fixture-only', 'threadId': 'usage-thread', 'turnId': 'usage-turn',
                                'tokenUsage': {'total': {'totalTokens': 1400}, 'last': {'totalTokens': 400}}}],
                    'rateLimits': {'rateLimits': {'primary': {'usedPercent': 23, 'windowDurationMins': 300, 'resetsAt': int(time.time()) + 5400}}},
                    'accountUsage': {'summary': {'lifetimeTokens': 10000}}}
            invocation.return_value(GLib.Variant('(s)', (json.dumps(data),)))
        elif method in ('InvestigateSuggestion', 'ApplySuggestion'):
            suggestion, task_id = params.unpack()
            conversation = 'test-' + suggestion
            running[(suggestion, task_id)] = conversation
            fields = {'suggestion': suggestion, 'suggestionTask': task_id}
            emit({'type': 'suggestion-started', **fields, 'conversation': conversation})
            invocation.return_value(GLib.Variant('(s)', (json.dumps({'conversation': conversation}),)))
            if suggestion == hashlib.sha256(b'fixture:2').hexdigest()[:24]: return
            if suggestion == hashlib.sha256(b'fixture:1').hexdigest()[:24]:
                GLib.timeout_add(80, emit, {'type': 'error', **fields, 'conversation': conversation, 'text': '401 authentication missing'})
            else:
                GLib.timeout_add(80, emit, {'type': 'agent-message', **fields, 'conversation': conversation, 'final': True,
                                           'text': '检查已完成，未修改系统；下一步需要实机验证。'})
            GLib.timeout_add(120, emit, {'type': 'agent-finished', **fields, 'conversation': conversation})
        elif method == 'SuggestionTask':
            key = tuple(params.unpack())
            invocation.return_value(GLib.Variant('(s)', (json.dumps({'state': 'running' if key in running else 'inactive', 'conversation': running.get(key, '')}),)))
        else:
            suggestion, task_id = params.unpack()
            running.pop((suggestion, task_id), None)
            emit({'type': 'task-stopped', 'suggestion': suggestion, 'suggestionTask': task_id})
            invocation.return_value(None)

    bus.register_object('/com/rungic/VoiceAgent', info.interfaces[0], call, None, None)
    Gio.bus_own_name_on_connection(bus, 'com.rungic.VoiceAgent', Gio.BusNameOwnerFlags.NONE, None, None)
    loop = GLib.MainLoop()
    threading.Thread(target=loop.run, daemon=True).start()
    return bus, loop, emit, running


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
        for item in items[:2]: item['source'] = 'crashes'
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
            assert len(cli('list')['groups']) == 39
            assert any(g['count'] == 2 for g in cli('list')['groups'])
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
            cli('update', first, json.dumps({'planStatus': 'ready', 'plan': '具体变更', 'verification': '实际功能复查', 'rollback': '恢复原设置'}))
            cli('act', first, 'apply', json.dumps({'planRevision': cli('get', first)['planRevision']}))
            wait(lambda: cli('get', first)['state'] == 'attention')
            report = cli('feedback', first)
            data = Path(report['path']).read_text()
            assert 'do-not-export' not in data and 'false' in data
            cli('update', first, json.dumps({'upstream': {'state': 'merged', 'url': 'https://example.org/issues/1'}}))
            assert cli('get', first)['state'] == 'attention'
            cli('act', second, 'restore')
            cli('act', second, 'investigate')
            wait(lambda: cli('get', second)['state'] == 'attention')
            assert cli('get', second)['result'] == '401 authentication missing'
            assert '401 authentication missing' in cli('get', second)['note']
            # Running tasks survive both ledger-service restart and disappearing observations.
            third = items[2]['id']
            started = cli('act', third, 'investigate')
            task_id = started['task']['id']
            wait(lambda: cli('get', third).get('conversation'))
            process.terminate(); process.wait(5)
            process = subprocess.Popen([binary, '--service'], env=env, stdout=log, stderr=log)
            wait(lambda: cli('get', third)['task']['state'] == 'running')
            (root / 'feed.json').write_text(json.dumps({'schema': 1, 'generated': int(time.time()),
                                                       'items': [i for i in items if i['id'] != third], 'sources': ['fixture']}))
            cli('refresh')
            wait(lambda: cli('get', third)['issueState'] == 'absent')
            assert cli('get', third)['state'] == 'working'
            voice[2]({'type': 'agent-message', 'suggestion': third, 'suggestionTask': task_id,
                      'final': True, 'text': '结果在问题消失后仍须保留'})
            wait(lambda: '仍须保留' in cli('get', third).get('result', ''))
            cli('act', third, 'stop')
            wait(lambda: cli('get', third)['task']['state'] == 'stopped')
            assert cli('get', third)['state'] == 'attention'
            old = cli('get', first)['planRevision']
            cli('update', first, json.dumps({'planStatus': 'ready', 'plan': 'another plan'}))
            assert 'error' in cli('act', first, 'apply', json.dumps({'planRevision': old}), error=True)
            print('PASS: task survives disappearance/restart; stop and result correlation; stale confirmation rejected')
            if len(sys.argv) >= 5:
                subprocess.run([sys.argv[3], sys.argv[4], *sys.argv[5:]], env=env, check=True, timeout=20)
                shown = [i for i in cli('list')['items'] if i.get('displayedRevision', 0)]
                assert ('--agent' in sys.argv or '--usage' in sys.argv) or 0 < len(shown) < 40, ('presentation must acknowledge only visible cards', len(shown))
                assert all(not i.get('openedRevision') for i in cli('list')['items'])
                print('PASS: QML acknowledged only displayed card revisions:', len(shown))
                if '--swipe-test' in sys.argv:
                    assert cli('get', first).get('displayedRevision') and cli('get', second).get('displayedRevision'), 'both actually viewed members need receipts'
                elif '--widget' in sys.argv:
                    assert not (cli('get', first).get('displayedRevision') and cli('get', second).get('displayedRevision')), 'hidden stack member was acknowledged'
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
