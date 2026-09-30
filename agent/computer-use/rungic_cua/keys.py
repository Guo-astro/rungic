"""Rungic's API keys (docs/87): plain files in ~/.config/rungic-voice-agent/, mode 600 in a
700 directory. The user chose files over the system keyring (2026-09-29): an unlocked
keyring gives every program of the user the same access, and a password would have to be
entered at every start. Every reader goes through here.

  read('openai-api-key')         the key, or '' when there is none
  store('openai-api-key', value) keep it
  clear('openai-api-key')        forget it
  where('openai-api-key')        'file' | ''
"""
from __future__ import annotations

import os
from pathlib import Path

FILES = Path.home() / '.config/rungic-voice-agent'


def _file(name: str) -> Path:
    return FILES / name


def read(name: str) -> str:
    try:
        return _file(name).read_text().strip()
    except OSError:
        return ''


def where(name: str) -> str:
    return 'file' if _file(name).exists() else ''


def store(name: str, value: str) -> str:
    FILES.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = _file(name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(value + '\n')
    os.chmod(path, 0o600)
    return 'file'


def clear(name: str) -> None:
    _file(name).unlink(missing_ok=True)
