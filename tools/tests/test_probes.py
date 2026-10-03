"""Diagnostic probes of rungic-plasma-diagnostics, run here on their real sources (docs/61, docs/69).

The input probe's QML (system/diagnostics/probes/input-probe.cpp) logs what an input method committed:
its length and whether it was Chinese, never the text. rungic-fs-audit runs the file operations
desktop programs need in a directory and says what breaks; an essential failure exits 1."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SECRET = '你好secret密码123'


def probe_qml():
    source = (ROOT / 'system/diagnostics/probes/input-probe.cpp').read_text()
    return re.search(r'loadData\(R"\((.*?)\)"\)', source, re.S)[1]       # a C++ raw string: taken as is


# covers: delivery.probes/E2
def test_input_probe_logs_length_and_chinese_never_the_text(tmp_path):
    pytest.importorskip('PySide6')
    (tmp_path / 'probe.qml').write_text(probe_qml())
    # The probe's window in an offscreen Qt, the text committed as an input method would.
    script = f'''
import sys
from PySide6.QtCore import QObject, QUrl, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
logged = []
qInstallMessageHandler(lambda mode, context, message: logged.append(message))
app = QGuiApplication(sys.argv)
engine = QQmlApplicationEngine()
engine.load(QUrl.fromLocalFile({str(tmp_path / 'probe.qml')!r}))
assert engine.rootObjects(), logged
window = engine.rootObjects()[0]
field = window.findChild(QObject, 'testField')
for text in ({SECRET!r}, 'plain ASCII 7', '输入'):
    field.setProperty('text', text)
print('\\n'.join(logged))
'''
    done = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=120,
                          env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
    assert done.returncode == 0, done.stderr[-2000:]
    lines = [l for l in done.stdout.splitlines() if 'RUNGIC_INPUT_LENGTH' in l]
    assert lines == [f'RUNGIC_INPUT_LENGTH {len(SECRET)} CHINESE true', 'RUNGIC_INPUT_LENGTH 13 CHINESE false',
                     'RUNGIC_INPUT_LENGTH 2 CHINESE true']
    assert not any(word in done.stdout for word in ('secret', '你好', '密码', 'plain', '输入'))


def fs_audit(*args, limit=None):
    command = [sys.executable, str(ROOT / 'system/diagnostics/rungic-fs-audit'), '--json', *args]
    if limit:
        command = ['prlimit', limit, *command]
    done = subprocess.run(command, capture_output=True, text=True, timeout=300)
    return done.returncode, json.loads(done.stdout)


# covers: delivery.probes/E3
def test_fs_audit_lists_what_fails_and_what_it_breaks(tmp_path):
    code, report = fs_audit(str(tmp_path))
    [target] = report['targets']
    checks = target['checks']
    assert {'mmap_shared', 'sqlite_wal', 'posix_lock', 'atomic_replace', 'inotify', 'unix_socket'} <= set(checks)
    assert all(c['breaks'] for c in checks.values())               # what kind of program each one serves
    assert all(c['ok'] for c in checks.values() if c['essential']) and code == 0
    assert target['mount']['target'] and list(tmp_path.iterdir()) == []      # it cleans up after itself

    # A directory where files cannot grow (as on a broken mount): shared mappings and SQLite fail there.
    code, report = fs_audit(str(tmp_path), limit='--fsize=0')
    checks = report['targets'][0]['checks']
    failed = {name for name, c in checks.items() if not c['ok']}
    assert {'mmap_shared', 'sqlite_wal'} <= failed and checks['mmap_shared']['essential']
    assert 'SQLite WAL' in checks['mmap_shared']['breaks'] and checks['mmap_shared']['detail']
    assert code == 1
