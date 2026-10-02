"""rungic-desktop-plasma: the independent desktop's volume applets show the phone's virtual devices
(docs/research/97 §19.6)."""
import importlib.machinery
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'agent/workspace/rungic-desktop-plasma'
loader = importlib.machinery.SourceFileLoader('rungic_desktop_plasma', str(SCRIPT))
spec = importlib.util.spec_from_loader('rungic_desktop_plasma', loader)
plasma = importlib.util.module_from_spec(spec)
loader.exec_module(plasma)

LAYOUT = """[Containments][2][Applets][7]
plugin=org.kde.plasma.systemtray

[Containments][2][Applets][7][Applets][12]
immutability=1
plugin=org.kde.plasma.volume

[Containments][2][Applets][7][Applets][12][Configuration][General]
migrated=true

[Containments][2][Applets][20]
plugin=org.kde.plasma.volume
"""


def test_the_trays_and_the_panels_volume_applets_lack_it():
    assert plasma.lacking(LAYOUT) == [['Containments', '2', 'Applets', '7', 'Applets', '12', 'Configuration', 'General'],
                                      ['Containments', '2', 'Applets', '20', 'Configuration', 'General']]


def test_once_set_nothing_lacks():
    done = LAYOUT.replace('migrated=true\n', 'migrated=true\nshowVirtualDevices=true\n') + \
        '\n[Containments][2][Applets][20][Configuration][General]\nshowVirtualDevices=true\n'
    assert plasma.lacking(done) == []
