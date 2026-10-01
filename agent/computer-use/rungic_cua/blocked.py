"""An application held by a dialog nobody can see (docs/103).

A native file dialog in a Qt program is an empty modal shell: the dialog the user sees is another
process's window (xdg-desktop-portal), and the shell closes when the portal's answer arrives. When
that answer never arrives, the shell stays, shown and visible to Qt (and in the accessibility tree)
but with no window on the screen, and every window of the program ignores clicks and keys. Krita
waited like this for good (docs/103); the agent kept clicking its menus. This tells the model what
it is looking at instead.
"""
from __future__ import annotations

from . import a11y

DIALOG_ROLES = ('dialog', 'file chooser', 'alert')


def base_title(name: str) -> str:
    """'Saving As — Krita' -> 'Saving As': Qt adds the application's name; the portal's window has none."""
    return name.split(' — ')[0].strip()


def hidden_dialogs(app_windows: list, windows: list[dict], pid: int) -> list[dict]:
    """The program's dialogs that the accessibility tree shows and the window manager does not have.
    app_windows: its top-level accessibility nodes; windows: every window (normal and dialog) as
    KWin lists them, {pid, caption, resource_class}. Each: {'name', 'portal': the window showing it
    in its stead, or None}."""
    own = {w['caption'] for w in windows if w.get('pid') == pid}
    found = []
    for node in app_windows:
        if node.role not in DIALOG_ROLES or not node.name:
            continue
        if not (node.state(a11y.SHOWING) and node.state(a11y.VISIBLE)):
            continue
        if node.name in own or any(c.startswith(base_title(node.name)) for c in own if c):
            continue                      # on the screen: an ordinary dialog
        title = base_title(node.name)
        portal = next((w for w in windows if w.get('pid') != pid and w.get('caption') == title), None)
        found.append({'name': node.name, 'portal': portal})
    return found


def note(app: str, hidden: list[dict]) -> str | None:
    """What to tell the model, or None when nothing holds the program."""
    if not hidden:
        return None
    first = hidden[0]
    if first['portal']:
        return (f"{app} waits for its dialog '{base_title(first['name'])}', which is a separate window "
                f"({first['portal'].get('resource_class')}): work in that window, {app}'s own windows take no "
                f"input until it closes.")
    return (f"{app} is held by a dialog that is not on the screen ('{first['name']}'): its windows take no "
            f"clicks or keys now. Do not keep trying. Tell the user {app} is stuck waiting on a dialog; "
            f"closing {app} is the way out (save what you can elsewhere first).")
