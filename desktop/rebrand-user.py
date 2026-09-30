#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""The desktop user's state across the Rungic rename (docs/70), in both directions.

  rungic-rebrand-user up     the session runs it before kconf_update (desktop/session): once, marked
                             by ~/.local/state/rungic-rebrand
  rungic-rebrand-user down   tools/rungic_release.py runs it, with the session stopped, before a
                             release from before the rename replaces this one
  rungic-rebrand-user rehome OLD NEW
                             paths into the home in the settings, after the home moved (the
                             first-run account setup moves it to /home/<login>)

The home directory is not part of the rootfs snapshot, so a rollback does not take it back: down
gives the older release the names it knows. Settings name desktop files, quick setting tiles, the
input method and cameras; up and down swap those names in the user's KDE configuration and Codex
configuration. Directories move between their two names (down copies back what changed since up).
The kconf_update records of the renamed .upd files go along, so their steps do not run again.
"""
import os
import re
import shutil
import sys
from pathlib import Path

HOME = Path.home()
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', HOME / '.config'))
MARKER = HOME / '.local/state/rungic-rebrand'

# Names in settings, before -> after. Exact strings: none is a prefix of another setting's text.
NAMES = [
    ('dev.moto.quicksetting.cast', 'com.rungic.quicksetting.cast'),
    ('dev.moto.quicksetting.agentscreen', 'com.rungic.quicksetting.agentscreen'),
    ('dev.moto.VoiceAssistant.desktop', 'com.rungic.VoiceAssistant.desktop'),
    ('dev.moto.AgentScreen.desktop', 'com.rungic.AgentScreen.desktop'),
    ('dev.moto.Platform.desktop', 'com.rungic.Platform.desktop'),
    ('dev.moto.screenshot.desktop', 'com.rungic.screenshot.desktop'),
    ('/moto-account.desktop', '/rungic-account.desktop'),
    ('/usr/share/applications/moto-plasma-rime.desktop', '/usr/share/applications/rungic-plasma-rime.desktop'),
    ('moto-pipewire-back', 'rungic-pipewire-back'),
    ('moto-pipewire-front', 'rungic-pipewire-front'),
    ('[mcp_servers.moto-desktop]', '[mcp_servers.rungic-desktop]'),
    ('/usr/bin/moto-cua', '/usr/bin/rungic-cua'),
]
# The home was /home/linux before the rename; rungic-rebrand-system moves it to /home/<login> at
# container start, before the session runs up.
FORMER_HOME = '/home/linux'


def home_pairs():
    return [(FORMER_HOME, str(HOME))] if str(HOME) != FORMER_HOME else []
# Files whose settings may name them: the KDE configuration files directly in ~/.config, and Codex's.
CODEX = HOME / '.codex'

DIRS = [
    (CONFIG / 'moto-voice-agent', CONFIG / 'rungic-voice-agent'),       # API keys
    (CONFIG / 'moto-cua', CONFIG / 'rungic-cua'),
    (CONFIG / 'moto-screen-recording.ini', CONFIG / 'rungic-screen-recording.ini'),
    (HOME / '.local/share/moto-voice-agent', HOME / '.local/share/rungic-voice-agent'),
    (HOME / '.local/state/moto-clicker', HOME / '.local/state/rungic-clicker'),
    (HOME / '.local/state/moto-cua', HOME / '.local/state/rungic-cua'),
    (HOME / '.local/state/moto-virtual-screen', HOME / '.local/state/rungic-virtual-screen'),
]
# Codex's link to the phone-desktop skill (rungic-codex-setup.sh): name and target per release.
SKILLS = [('moto-phone-desktop', '/usr/share/moto-voice-agent/skills/moto-phone-desktop'),
          ('rungic-phone-desktop', '/usr/share/rungic-voice-agent/skills/rungic-phone-desktop')]
UPD = [('moto.upd', 'rungic.upd', 'moto-', 'rungic-'),
       ('moto-voice-agent.upd', 'rungic-voice-agent.upd', 'moto-', 'rungic-')]


# Other files that name paths: Codex's configuration, the file dialogs' places and bookmarks.
EXTRA = [CODEX / 'config.toml', HOME / '.local/share/user-places.xbel', CONFIG / 'gtk-3.0/bookmarks',
         CONFIG / 'gtk-4.0/bookmarks']


def settings_files():
    files = [p for p in CONFIG.iterdir() if p.is_file() and not p.is_symlink()] if CONFIG.is_dir() else []
    return files + [p for p in EXTRA if p.is_file() and not p.is_symlink()]


def drop_duplicate_sections(text, pairs):
    """A section ([...] header) renamed onto one that exists already, e.g. Codex's MCP server that
    the first-run setup wrote again under its new name: the old section goes instead."""
    for old, new in pairs:
        if old.startswith('[') and old in text and new in text:
            text = re.sub(r'(?ms)^' + re.escape(old) + r'\n.*?(?=^\[|\Z)', '', text)
    return text


def dedupe_lists(text):
    """Quick setting tiles named twice after the rename (old and new names both listed)."""
    def dedupe(m):
        seen = []
        for item in m[2].split(','):
            if item not in seen:
                seen.append(item)
        return m[1] + ','.join(seen)
    return re.sub(r'(?m)^((?:enabled|disabled)QuickSettings=)(.*)$', dedupe, text)


def swap_names(pairs, homes=()):
    """Replace the names in the settings files; `homes` are (old, new) home directories, replaced
    where a path starts with them (followed by /, a quote, space, < or the line's end)."""
    changed = []
    for path in settings_files():
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        new = drop_duplicate_sections(text, pairs)
        for old, name in pairs:
            new = new.replace(old, name)
        new = dedupe_lists(new)
        for old, home in homes:
            new = re.sub(re.escape(old) + r'(?=[/"\'\s<]|$)', lambda m: home, new, flags=re.M)
        if new != text:
            tmp = path.with_name(path.name + '.rungic-rebrand')
            tmp.write_text(new)
            shutil.copymode(path, tmp)
            tmp.replace(path)
            changed.append(path.name)
    return changed


def copy(source, target):
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def remove(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def relink(before, after):
    """The skill link under its other name, if the user has the one it replaces."""
    old, new = CODEX / 'skills' / before[0], CODEX / 'skills' / after[0]
    if old.is_symlink() and os.readlink(old) == before[1]:
        old.unlink()
        if not new.is_symlink():
            new.symlink_to(after[1])


def kde_groups(text):
    """{group: {key: value}} of a KDE configuration file (keys before any group go under '')."""
    groups, group = {'': {}}, ''
    for line in text.splitlines():
        if line.startswith('[') and line.rstrip().endswith(']'):
            group = line.strip()[1:-1]
            groups.setdefault(group, {})
        elif '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            groups[group][key.strip()] = value.strip()
    return groups


def carry_kconf_records():
    """kconf_update keeps what it ran per .upd file name; the renamed files inherit the records."""
    rc = CONFIG / 'kconf_updaterc'
    if not rc.is_file():
        return []
    groups = kde_groups(rc.read_text())
    carried = []
    for old, new, prefix, new_prefix in UPD:
        if 'done' in groups.get(old, {}) and 'done' not in groups.get(new, {}):
            done = ','.join(new_prefix + i[len(prefix):] if i.startswith(prefix) else i
                            for i in groups[old]['done'].split(','))
            text = rc.read_text()
            header = re.compile(r'(?m)^\[' + re.escape(new) + r'\]\n')
            text = (header.sub(lambda m: m[0] + f'done={done}\n', text, count=1) if header.search(text)
                    else text.rstrip('\n') + f'\n\n[{new}]\ndone={done}\n')
            rc.write_text(text)
            carried.append(new)
    return carried


def up():
    if MARKER.exists():
        return {'done': 'already'}
    report = {'records': carry_kconf_records(), 'settings': swap_names(NAMES, home_pairs()), 'moved': []}
    for old, new in DIRS:
        if old.exists() and not new.exists():
            copy(old, new)
            report['moved'].append(new.name)
    relink(*SKILLS)
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text('up\n')
    return report


def down():
    report = {'settings': swap_names([(new, old) for old, new in NAMES], [(new, old) for old, new in home_pairs()]),
              'moved': []}
    for old, new in DIRS:
        if new.exists():
            copy(new, old)          # what changed since up goes back to the older release
            remove(new)
            report['moved'].append(old.name)
    relink(*reversed(SKILLS))
    remove(MARKER)
    return report


def main():
    if len(sys.argv) == 4 and sys.argv[1] == 'rehome':
        print({'settings': swap_names([], [(sys.argv[2].rstrip('/'), sys.argv[3].rstrip('/'))])})
    elif len(sys.argv) == 2 and sys.argv[1] in ('up', 'down'):
        print(up() if sys.argv[1] == 'up' else down())
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
