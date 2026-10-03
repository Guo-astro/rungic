"""rungic_device.run() sends a script on stdin to one of four levels (Android shell, Android root,
container root, desktop user) without nesting it in quotes, and returns its exit status (docs/55).

Here adb, su and the Android-side launcher are stand-ins on this computer: adb runs `shell ARGS` as
Android's adb does (one sh -c of the joined words), su runs `-c CMD` with sh, and the launcher's
`exec` / `user-exec` run their command. A separate copy of rungic_device is loaded with RUNGIC_ADB
pointing to the stand-in, so nothing can reach a phone (tools/conftest.py guards the shared one)."""
import importlib.util
import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Quotes of every kind, expansions, a backslash, a heredoc and a multi-line string: what nested
# `su -c '...'` quoting used to break (AGENTS.md: only the first command ran as root).
SCRIPT = r'''name="it's \"quoted\""
echo "$name" '$HOME stays literal' back\\slash
cat <<'EOF'
line with $dollar and `backticks`
EOF
echo "level=${FAKE_UID:-shell}:${FAKE_IN:-android}"
exit 7
'''
EXPECTED = '''it's "quoted" $HOME stays literal back\\slash
line with $dollar and `backticks`
'''


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def device(tmp_path, monkeypatch):
    android = tmp_path / 'android'          # stands for /data/adb
    executable(tmp_path / 'bin/adb', '#!/bin/sh\n'
               '[ "$1" = -s ] && [ "$2" = stand-in ] && [ "$3" = shell ] || { echo "adb: $*" >&2; exit 99; }\n'
               'shift 3\nexec sh -c "$*"\n')
    executable(tmp_path / 'bin/su', '#!/bin/sh\n'
               '[ "$1" = -c ] || exit 98\n'
               f'export FAKE_UID=root\nexec sh -c "$(printf %s "$2" | sed "s#/data/adb/#{android}/#g")"\n')
    executable(android / 'rungic-plasma/rungic-plasma', '#!/bin/sh\n'
               'case $1 in exec) export FAKE_IN=container ;; user-exec) export FAKE_IN=desktop-user ;; *) exit 97 ;; esac\n'
               'shift\nexec "$@"\n')
    monkeypatch.setenv('PATH', f'{tmp_path / "bin"}:{os.environ["PATH"]}')
    monkeypatch.setenv('RUNGIC_ADB', str(tmp_path / 'bin/adb'))
    monkeypatch.setenv('RUNGIC_TRANSPORT', 'stand-in')
    spec = importlib.util.spec_from_file_location('rungic_device_stand_in', ROOT / 'tools/rungic_device.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# covers: delivery.phone-access/E2
@pytest.mark.parametrize('level, where', [('shell', 'shell:android'), ('root', 'root:android'),
                                          ('container', 'root:container'), ('user', 'root:desktop-user')])
def test_a_script_reaches_each_level_verbatim_with_its_exit_status(device, level, where):
    result = device.run(SCRIPT, level, check=False)
    assert result.stderr == ''
    assert result.stdout == EXPECTED + f'level={where}\n'
    assert result.returncode == 7
    with pytest.raises(device.DeviceError, match='Exit 7'):
        device.run(SCRIPT, level)
    assert device.out('printf ok', level) == 'ok'
