#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The ✕ on a workspace's floating window: `rungic-agent-screen dismiss N` (docs/research/91).

The real script runs as the window runs it. Around it: the platform bridge is a stand-in that keeps
the assistant screen's state as the app does (the contract's `agent-screen` query; the switch it
sends, `enabled`, is not in the contract, which holds only read-only queries for the phone's
checks); the voice agent's State, rungic-cua close-workspace and notify-send are stand-ins on PATH
that record their calls. The notification's labels come from the package's zh_CN catalog."""
import ast
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'agent/computer-use'))
import contracts  # noqa: E402
from rungic_cua import workspace  # noqa: E402

SCRIPT = ROOT / 'agent/screen/rungic-agent-screen'
CATALOG = ROOT / 'agent/screen/po/zh_CN/rungic-agent-screen.po'


def po_entries(path):
    """{'context\\x04id' or 'id': text} of a .po file (single-line and continued strings)."""
    entries, current, key = {}, {}, None
    def flush():
        if 'msgid' in current and current.get('msgstr'):
            ident = current['msgid']
            entries[(current['msgctxt'] + '\x04' + ident) if 'msgctxt' in current else ident] = current['msgstr']
    for line in path.read_text().splitlines() + ['']:
        line = line.strip()
        match = re.match(r'(msgctxt|msgid|msgstr) "(.*)"$', line)
        if match:
            if match.group(1) in ('msgctxt',) or (match.group(1) == 'msgid' and 'msgstr' in current):
                flush()
                current = {}
            key = match.group(1)
            current[key] = ast.literal_eval(f'"{match.group(2)}"')
        elif line.startswith('"') and key:
            current[key] += ast.literal_eval(line)
        elif not line:
            flush()
            current, key = {}, None
    return entries


def write_mo(entries, path):
    """A GNU .mo of `entries` (what msgfmt makes; the header entry first)."""
    entries = {'': 'Content-Type: text/plain; charset=UTF-8\n', **entries}
    keys = sorted(entries)
    ids = [k.encode() for k in keys]
    strs = [entries[k].encode() for k in keys]
    start = 7 * 4 + 16 * len(keys)
    ids_data, strs_data, id_table, str_table = b'', b'', [], []
    for data in ids:
        id_table.append((len(data), start + len(ids_data)))
        ids_data += data + b'\0'
    base = start + len(ids_data)
    for data in strs:
        str_table.append((len(data), base + len(strs_data)))
        strs_data += data + b'\0'
    header = struct.pack('<7I', 0x950412de, 0, len(keys), 7 * 4, 7 * 4 + 8 * len(keys), 0, 0)
    tables = b''.join(struct.pack('<2I', *e) for e in id_table) + b''.join(struct.pack('<2I', *e) for e in str_table)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + tables + ids_data + strs_data)


class Screen(contracts.StandIn):
    """The app's assistant-screen state: queried by the contract's request, switched by `enabled`."""

    def __init__(self):
        super().__init__('platform-bridge')
        self.state = dict(next(q for q in self.contract['queries'] if q['name'] == 'agent-screen')['reply'],
                          enabled=True, workspace=1)

    def answer(self, request):
        if request.get('op') == 'agent-screen':
            if 'enabled' in request:
                self.state['enabled'] = bool(request['enabled'])
            if 'workspace' in request:
                self.state['workspace'] = int(request['workspace'])
            return dict(self.state)
        return super().answer(request)


STAND_INS = {
    # The voice agent's State over the user's bus (rungic-agent-screen voice_state).
    'busctl': '''#!/bin/sh
echo "busctl $*" >> "$CALLS"
printf '{"type":"s","data":[%s]}\\n' "$(python3 -c 'import json,os; print(json.dumps(os.environ["VOICE_STATE"]))')"
''',
    # rungic-cua close-workspace N [--force]: as the test says it ends.
    'rungic-cua': '''#!/bin/sh
echo "rungic-cua $*" >> "$CALLS"
case " $* " in *" --force "*) echo '{"closed": true}' ;; *) echo "$CLOSE_RESULT" ;; esac
''',
    # The user taps one of the notification's actions (--wait prints its key).
    'notify-send': '''#!/bin/sh
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:], ensure_ascii=False))' "$@" >> "$NOTIFIED"
echo "$NOTIFY_CHOICE"
''',
    'systemctl': '#!/bin/sh\nexit 0\n',
}


class DismissTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='rungic-dismiss-')
        tmp = Path(self.tmp.name)
        self.runtime = tmp / 'runtime'
        self.runtime.mkdir()
        bin_dir = tmp / 'bin'
        bin_dir.mkdir()
        for name, text in STAND_INS.items():
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o755)
        # The package's catalog where Python's gettext finds it (sitecustomize: before the script).
        write_mo(po_entries(CATALOG), tmp / 'locale/zh_CN/LC_MESSAGES/rungic-agent-screen.mo')
        (tmp / 'site').mkdir()
        (tmp / 'site/sitecustomize.py').write_text(
            'import gettext\n_t = gettext.translation\n'
            f'gettext.translation = lambda domain, localedir=None, *a, **k: _t(domain, {str(tmp / "locale")!r}, *a, **k)\n')
        self.calls = tmp / 'calls'
        self.notified = tmp / 'notified'
        self.calls.touch()
        self.notified.touch()
        self.screen = Screen().__enter__()
        self.env = {'PATH': f'{bin_dir}:/usr/bin:/bin', 'XDG_RUNTIME_DIR': str(self.runtime), 'HOME': str(tmp),
                    'RUNGIC_PLATFORM_SOCKET': self.screen.path, 'PYTHONPATH': str(tmp / 'site'),
                    'LANGUAGE': 'zh_CN', 'LANG': 'zh_CN.UTF-8', 'CALLS': str(self.calls),
                    'NOTIFIED': str(self.notified), 'VOICE_STATE': json.dumps({'agentBusy': False, 'workspace': 1}),
                    'CLOSE_RESULT': json.dumps({'closed': True}), 'NOTIFY_CHOICE': ''}

    def tearDown(self):
        self.screen.__exit__()
        self.tmp.cleanup()

    def dismiss(self, slot=1):
        done = subprocess.run([str(SCRIPT), 'dismiss', str(slot)], env=self.env, capture_output=True, text=True,
                              timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def closes(self):
        return [line for line in self.calls.read_text().splitlines() if line.startswith('rungic-cua close-workspace')]

    def wait_for(self, condition, timeout=20):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                self.fail('timed out')
            time.sleep(0.1)

    # covers: agent.workspace-lifecycle/E6
    def test_agent_at_work_there_only_hides_it_for_this_turn(self):
        self.env['VOICE_STATE'] = json.dumps({'agentBusy': True, 'workspace': 1})
        with mock.patch.dict(os.environ, XDG_RUNTIME_DIR=str(self.runtime)):
            self.assertFalse(workspace.dismissed(1))
            result = self.dismiss()
            # The agent's tools do not bring it back this turn (rungic_cua server.show_workspace).
            self.assertTrue(workspace.dismissed(1))
        self.assertEqual(result['workspace'], {'closed': False, 'hidden': 'an agent is at work'})
        self.assertFalse(self.screen.state['enabled'], 'the screen is hidden')
        self.assertEqual(self.closes(), [], 'the workspace and its apps go on')

    # covers: agent.workspace-lifecycle/E6
    def test_a_member_holding_the_workspace_only_hides_it(self):
        (self.runtime / 'rungic-workspace-1.busy').write_text(json.dumps({'pid': os.getpid()}))
        result = self.dismiss()
        self.assertEqual(result['workspace']['hidden'], 'an agent is at work')
        self.assertEqual(self.closes(), [])

    # covers: agent.workspace-lifecycle/E6
    def test_the_voice_agent_at_work_elsewhere_does_not_keep_it(self):
        self.env['VOICE_STATE'] = json.dumps({'agentBusy': True, 'workspace': 2})
        result = self.dismiss()
        self.assertEqual(self.closes(), ['rungic-cua close-workspace 1'])
        self.assertEqual(result['workspace'], {'closed': True})
        self.assertFalse((self.runtime / 'rungic-agent-screen-dismissed-1').exists())

    # covers: agent.workspace-lifecycle/E6
    def test_otherwise_the_workspace_closes_without_a_notification(self):
        result = self.dismiss()
        self.assertEqual(self.closes(), ['rungic-cua close-workspace 1'])
        self.assertTrue(result['workspace']['closed'])
        self.assertFalse(self.screen.state['enabled'])
        time.sleep(1)
        self.assertEqual(self.notified.read_text(), '', 'nothing to tell when everything closed')

    # covers: agent.workspace-lifecycle/E6
    def test_an_app_kept_open_is_told_with_view_and_close_without_saving(self):
        self.env['CLOSE_RESULT'] = json.dumps({'closed': False, 'remaining': [{'app': 'Kate', 'caption': 'notes.txt'}]})
        self.env['NOTIFY_CHOICE'] = 'force'
        result = self.dismiss()
        self.assertEqual(result['workspace']['remaining'][0]['app'], 'Kate')
        self.wait_for(lambda: self.notified.read_text().strip())
        args = json.loads(self.notified.read_text().splitlines()[0])
        self.assertIn('--action=view=查看', args)
        self.assertIn('--action=force=不保存，直接关闭', args)
        self.assertTrue(any('Kate' in a for a in args), args)
        # "不保存，直接关闭": closed by force; nothing was answered for the app before that.
        self.wait_for(lambda: 'rungic-cua close-workspace 1 --force' in self.closes())
        self.assertEqual(self.closes(), ['rungic-cua close-workspace 1', 'rungic-cua close-workspace 1 --force'])


if __name__ == '__main__':
    unittest.main()
