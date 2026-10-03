"""rungic_trace.capture() against a stand-in phone: KWin's FTrace markers are on only while perfetto
records, and afterwards are as they were before (docs/55). The trace's content (KWin, SurfaceFlinger,
KGSL in one buffer) is the phone's to show."""
import sys
import threading
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rungic_device  # noqa: E402
import rungic_trace  # noqa: E402


class Phone:
    """KWin's /FTrace isEnabled property and perfetto, as far as capture() talks to them."""

    def __init__(self, markers):
        self.markers = markers
        self.events = []
        self.recording = threading.Event()
        self.observed = threading.Event()

    def run(self, script, level='root', timeout=60, check=True):
        result = types.SimpleNamespace(returncode=0, stdout='', stderr='')
        if 'org.kde.kwin.FTrace' in script:
            assert level == 'user'
            result.stdout = f"{'true' if self.markers else 'false'}\n"
            self.markers = 'setEnabled true' in script
            self.events.append(('markers', self.markers))
        elif 'perfetto --txt' in script:
            self.events.append(('perfetto', 'start'))
            self.recording.set()
            assert self.observed.wait(5)
            self.events.append(('perfetto', 'end'))
        return result


@pytest.fixture
def phone(tmp_path, monkeypatch):
    def make(markers):
        fake = Phone(markers)
        monkeypatch.setattr(rungic_trace, 'run', fake.run)
        monkeypatch.setattr(rungic_trace, 'DIAG_DIR', tmp_path)
        monkeypatch.setattr(rungic_trace, 'time', types.SimpleNamespace(
            strftime=lambda f: '20261003-120000', sleep=lambda s: fake.recording.wait(5)))
        monkeypatch.setattr(rungic_trace, 'subprocess', types.SimpleNamespace(run=lambda *a, **k: None, DEVNULL=None))
        monkeypatch.setattr(rungic_device, 'adb', lambda *args: ['adb-stand-in', *args])
        monkeypatch.setattr(rungic_device, 'apk', lambda: 'com.rungic.plasma')
        return fake
    return make


def during(fake):
    def act():
        fake.events.append(('during', fake.markers))
        fake.observed.set()
    return act


# covers: delivery.trace/E2
@pytest.mark.parametrize('before', [False, True])
def test_markers_on_only_while_recording_then_as_before(phone, before):
    fake = phone(before)
    rungic_trace.capture(1, 'test', during=during(fake))
    events = fake.events
    # Off before perfetto starts (KWin's marker file breaks if written while tracing is off) ...
    assert events[0] == ('markers', False) and events.index(('perfetto', 'start')) == 1
    # ... on during the recording ...
    assert ('during', True) in events
    on = events.index(('markers', True))
    assert events.index(('perfetto', 'start')) < on < events.index(('perfetto', 'end'))
    # ... and afterwards what it was before the capture.
    assert events[-1] == ('markers', before) and events.index(('perfetto', 'end')) < len(events) - 1
    assert fake.markers is before
