#!/usr/bin/env python3
"""Run as the desktop user to route every Firefox desktop action via its wrapper."""
import os
import re
from pathlib import Path

source = Path('/usr/share/applications/firefox.desktop')
text = source.read_text()
text, count = re.subn(
    r'^(Exec|TryExec)=(?:/usr/bin/)?firefox(?=\s|$)',
    r'\1=/usr/local/bin/firefox', text, flags=re.MULTILINE,
)
if count < 3 or re.search(r'^Exec=/usr/lib/firefox/firefox', text, re.MULTILINE):
    raise SystemExit('Firefox desktop entry changed; review the launch commands first.')

data_dir = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
target = data_dir / 'applications/firefox.desktop'
target.parent.mkdir(parents=True, exist_ok=True)
marker = '# Moto: all desktop actions use the private-codec launch wrapper.\n'
if target.exists() and not target.read_text().startswith(marker):
    backup = target.with_name('firefox.desktop.pre-moto-launcher')
    if backup.exists():
        raise SystemExit(f'Existing custom launcher and backup: review {target} first.')
    backup.write_bytes(target.read_bytes())

temporary = target.with_name('firefox.desktop.moto-new')
temporary.write_text(marker + text)
temporary.chmod(0o644)
temporary.replace(target)
print(target)
