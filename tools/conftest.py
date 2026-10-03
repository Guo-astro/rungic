# SPDX-License-Identifier: MIT
"""Offline tests never reach the phone. Every device command of these tools goes through
rungic_device: scripts through _run (adb shell), files and the phone's lookup (`adb devices`,
getprop) through adb_path(), which every adb command line starts with. Both fail the test here,
before any process starts. A deploy test once removed the real phone's development overlay through
a path the test had not stubbed (docs/97); a guard on _run alone let run() ask the real adb for the
phone first, and push/pull reach it directly."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def no_device(monkeypatch):
    import rungic_device

    def refuse(*args, **kwargs):
        raise AssertionError(f'an offline test reached the device: {list(args[:1])[:3]}')
    monkeypatch.setattr(rungic_device, '_run', refuse)
    monkeypatch.setattr(rungic_device, 'adb_path', refuse)
