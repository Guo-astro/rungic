# covers: agent.computer-use/E4
"""rungic_cua.blocked (docs/103): a program held by a dialog nobody can see, told apart from an
ordinary dialog and from a portal's dialog window showing in its stead. Accessibility nodes and
KWin windows are stand-ins, as the phone listed them for Krita."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'agent/computer-use'))
from rungic_cua import a11y, blocked  # noqa: E402

KRITA = 6974


def node(role, name, showing=True):
    states = [0, 0]
    for bit in ((a11y.SHOWING, a11y.VISIBLE) if showing else ()):
        states[bit // 32] |= 1 << (bit % 32)
    return a11y.Node('x', '/x', None, name=name, role=role, states=tuple(states))


MAIN = node('frame', 'Krita')
SHELL = node('dialog', 'Saving As — Krita')             # the native dialog's empty modal shell
KRITA_WINDOW = {'pid': KRITA, 'caption': 'Krita', 'resource_class': 'org.kde.krita'}
PORTAL_WINDOW = {'pid': 11835, 'caption': 'Saving As', 'resource_class': 'org.freedesktop.impl.portal.desktop.kde'}


def test_held_by_a_dialog_nobody_sees():
    hidden = blocked.hidden_dialogs([MAIN, SHELL], [KRITA_WINDOW], KRITA)
    assert hidden == [{'name': 'Saving As — Krita', 'portal': None}]
    text = blocked.note('Krita', hidden)
    assert 'not on the screen' in text and 'Do not keep trying' in text


def test_the_portal_shows_it_in_another_window():
    hidden = blocked.hidden_dialogs([MAIN, SHELL], [KRITA_WINDOW, PORTAL_WINDOW], KRITA)
    assert hidden[0]['portal'] == PORTAL_WINDOW
    assert 'separate window' in blocked.note('Krita', hidden)


def test_an_ordinary_dialog_is_not_held():
    own_dialog = {'pid': KRITA, 'caption': 'Saving As — Krita', 'resource_class': 'org.kde.krita'}
    assert blocked.hidden_dialogs([MAIN, SHELL], [KRITA_WINDOW, own_dialog], KRITA) == []
    assert blocked.note('Krita', []) is None


def test_hidden_dialogs_do_not_count():
    # Qt keeps closed dialogs in the tree: neither showing nor visible (Krita's colour name dialog).
    closed = node('dialog', 'Color name', showing=False)
    assert blocked.hidden_dialogs([MAIN, closed], [KRITA_WINDOW], KRITA) == []


def test_frames_are_not_dialogs():
    offscreen = node('frame', 'Offscreen')                # Krita has such a frame, never on screen
    assert blocked.hidden_dialogs([MAIN, offscreen], [KRITA_WINDOW], KRITA) == []
