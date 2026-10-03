# SPDX-License-Identifier: MIT
"""The shared storage's contract from the Linux side (quality/contracts/shared-storage.json): the real
system/user-dirs runs with HOME in a temporary directory whose ~/Shared stands in for Android's
mounted storage (a fake `mountpoint` reports it mounted) and a fake xdg-user-dirs-update that records
the mapping. The provider's side is the acceptance scenario contract.shared-storage on the phone."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import contracts  # noqa: E402

USER_DIRS = ROOT / 'system/user-dirs'
PATHS = contracts.load('shared-storage')['paths']


def run(tmp_path, mounted=True):
    """user-dirs as the session runs it; returns (exit code, the XDG mapping it set)."""
    home, tools = tmp_path / 'home', tmp_path / 'bin'
    tools.mkdir(exist_ok=True)
    (home / PATHS['shared']).mkdir(parents=True, exist_ok=True)
    (tools / 'mountpoint').write_text('#!/bin/sh\n[ "$1" = -q ] && shift\n[ "$1" = "$FAKE_MOUNTED" ]\n')
    (tools / 'xdg-user-dirs-update').write_text('#!/bin/sh\n[ "$1" = --set ] && echo "$2=$3" >> "$FAKE_XDG"\n')
    for tool in tools.iterdir():
        tool.chmod(0o755)
    xdg = tmp_path / 'xdg'
    xdg.write_text('')
    env = dict(os.environ, HOME=str(home), PATH=f'{tools}:{os.environ["PATH"]}', FAKE_XDG=str(xdg),
               FAKE_MOUNTED=str(home / PATHS['shared']) if mounted else '/nowhere')
    done = subprocess.run(['sh', str(USER_DIRS)], env=env, capture_output=True, text=True, timeout=30)
    mapping = dict(line.split('=', 1) for line in xdg.read_text().splitlines())
    return done.returncode, mapping, home


# covers[consumer]: iface:shared-storage
def test_the_standard_directories_live_on_android_storage(tmp_path):
    code, mapping, home = run(tmp_path)
    assert code == 0
    shared = home / PATHS['shared']
    for name in PATHS['linked']:
        assert (shared / name).is_dir(), f'{name} is created on Android storage'
        assert os.readlink(home / name) == f'{PATHS["shared"]}/{name}', 'a relative link, valid under any login'
    for name in PATHS['local']:
        assert (home / name).is_dir() and not (home / name).is_symlink()
    assert mapping == {key: str(home / name) for key, name in PATHS['xdg'].items()}
    # Android unmounting the storage for a moment must not reset the mapping to $HOME.
    assert (home / '.config/user-dirs.conf').read_text() == 'enabled=False\n'


# covers[consumer]: iface:shared-storage
def test_without_android_storage_nothing_is_made(tmp_path):
    code, mapping, home = run(tmp_path, mounted=False)
    assert code == 1
    assert list((home / PATHS['shared']).iterdir()) == []
    assert not any((home / name).exists() for name in PATHS['linked'] + PATHS['local'])
    assert mapping == {}


# covers[consumer]: iface:shared-storage
def test_the_users_own_directories_are_kept(tmp_path):
    home = tmp_path / 'home'
    (home / 'Music').mkdir(parents=True)
    (home / 'Music/song.ogg').write_text('mine')
    code, mapping, home = run(tmp_path)
    assert code == 0
    assert not (home / 'Music').is_symlink() and (home / 'Music/song.ogg').read_text() == 'mine'
    assert mapping['MUSIC'] == str(home / 'Music')
    # A link the user made that leads nowhere is reported, not replaced.
    (home / 'Pictures').unlink()
    (home / 'Pictures').symlink_to('/nowhere/pictures')
    code, _, _ = run(tmp_path)
    assert code == 1 and os.readlink(home / 'Pictures') == '/nowhere/pictures'
