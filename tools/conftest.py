# SPDX-License-Identifier: MIT
"""Offline tests never reach the phone: every device command of these tools goes through
rungic_device._run (adb shell), which fails the test here. A deploy test once removed the real
phone's development overlay through a path the test had not stubbed (docs/97)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def no_device(monkeypatch):
    import rungic_device

    def refuse(argv, *args, **kwargs):
        raise AssertionError(f'an offline test reached the device: {argv[:3]}')
    monkeypatch.setattr(rungic_device, '_run', refuse)
