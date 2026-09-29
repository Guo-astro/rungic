"""Rungic's API keys in the system keyring (docs/87).

Keys live in the Secret Service (KDE's ksecretd in the session) under the attribute
`rungic-key=<name>`, through libsecret (gir1.2-secret-1). Before the move they were files
in ~/.config/rungic-voice-agent/ (mode 600); a key still in its file is read from there,
and `store` moves it into the keyring and removes the file. Without a usable keyring (no
session bus or gir, or no unlocked default collection: KWallet not set up) keys stay in
files; the keyring is never made to prompt.

  read('openai-api-key')         the key, or '' when there is none
  store('openai-api-key', value) keep it (the keyring, else the file)
  clear('openai-api-key')        forget it (both places)
  where('openai-api-key')        'keyring' | 'file' | ''
"""
from __future__ import annotations

import os
from pathlib import Path

FILES = Path.home() / '.config/rungic-voice-agent'
LABELS = {'openai-api-key': 'OpenAI API Key (Rungic)', 'typesafe-api-key': 'TypeSafe API Key (Rungic)'}
_secret = None


def _backend():
    """libsecret, or None when the keyring cannot be reached."""
    global _secret
    if _secret is None:
        try:
            import gi
            gi.require_version('Secret', '1')
            from gi.repository import Secret
            schema = Secret.Schema.new('com.rungic.Key', Secret.SchemaFlags.NONE,
                                       {'rungic-key': Secret.SchemaAttributeType.STRING})
            _secret = (Secret, schema)
        except (ImportError, ValueError):
            _secret = False
    return _secret or None


def _file(name: str) -> Path:
    return FILES / name


def _usable() -> bool:
    """The keyring's default collection exists and is unlocked. Anything else would make
    the Secret Service ask the user (KWallet's "create a wallet" wizard, an unlock
    prompt) and block the caller meanwhile, so such a keyring is not used (docs/87)."""
    backend = _backend()
    if not backend or not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
        return False
    secret, _ = backend
    try:
        service = secret.Service.get_sync(secret.ServiceFlags.NONE, None)
        collection = secret.Collection.for_alias_sync(service, secret.COLLECTION_DEFAULT,
                                                      secret.CollectionFlags.NONE, None)
        return collection is not None and not collection.get_locked()
    except Exception:  # noqa: BLE001 - no Secret Service, or it failed (e.g. no QCA plugins)
        return False


def _lookup(name: str) -> str | None:
    if not _usable():
        return None
    secret, schema = _backend()
    try:
        return secret.password_lookup_sync(schema, {'rungic-key': name}, None) or ''
    except Exception:  # noqa: BLE001 - no Secret Service on the bus, locked, ...
        return None


def read(name: str) -> str:
    value = _lookup(name)
    if value:
        return value.strip()
    try:
        return _file(name).read_text().strip()
    except OSError:
        return ''


def where(name: str) -> str:
    if _lookup(name):
        return 'keyring'
    return 'file' if _file(name).exists() else ''


def store(name: str, value: str) -> str:
    """Keeps `value`; returns where: 'keyring' or 'file'."""
    if _usable():
        secret, schema = _backend()
        try:
            if secret.password_store_sync(schema, {'rungic-key': name}, secret.COLLECTION_DEFAULT,
                                          LABELS.get(name, name), value, None):
                _file(name).unlink(missing_ok=True)
                return 'keyring'
        except Exception:  # noqa: BLE001
            pass
    FILES.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = _file(name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(value + '\n')
    return 'file'


def clear(name: str) -> None:
    if _usable():
        secret, schema = _backend()
        try:
            secret.password_clear_sync(schema, {'rungic-key': name}, None)
        except Exception:  # noqa: BLE001
            pass
    _file(name).unlink(missing_ok=True)
