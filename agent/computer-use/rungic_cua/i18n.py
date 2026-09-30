"""Words for people (the assistant screen's captions, questions for the user) in the desktop's language.

English in the source, translated from the gettext catalog rungic-cua (po/zh_CN/rungic-cua.po
in agent/computer-use, installed to /usr/share/locale/<lang>/LC_MESSAGES/rungic-cua.mo). The language
is Plasma's LANGUAGE/LANG. Codex starts this MCP server with a handful of variables and
server.import_session_environment() takes the rest from the user's systemd manager after the
modules are imported: the catalog is therefore opened at the first lookup, not at import.

Tool results for the model stay English.
"""
from __future__ import annotations

import gettext
import os

DOMAIN = 'rungic-cua'
LOCALEDIR = '/usr/share/locale'
NAMES = {'zh_CN': 'Simplified Chinese', 'zh_SG': 'Simplified Chinese', 'zh_TW': 'Traditional Chinese',
         'zh_HK': 'Traditional Chinese', 'zh': 'Chinese', 'en': 'English', 'ja': 'Japanese', 'ko': 'Korean',
         'de': 'German', 'fr': 'French', 'es': 'Spanish', 'it': 'Italian', 'pt': 'Portuguese', 'ru': 'Russian'}

_translation: gettext.NullTranslations | None = None


def catalog() -> gettext.NullTranslations:
    global _translation
    if _translation is None:
        _translation = gettext.translation(DOMAIN, localedir=LOCALEDIR, fallback=True)
    return _translation


def _(message: str) -> str:
    return catalog().gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return catalog().ngettext(singular, plural, n)


def desktop_language() -> str:
    """The desktop's language as a locale code ('en_US', 'zh_CN'), where gettext looks for it."""
    for variable in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
        value = os.environ.get(variable, '').split(':')[0].split('.')[0].split('@')[0]
        if value and value not in ('C', 'POSIX'):
            return value
    return 'en_US'


def language_name() -> str:
    """'Simplified Chinese (zh_CN)', 'English (en_US)': the desktop's language for a model."""
    code = desktop_language()
    name = NAMES.get(code) or NAMES.get(code.split('_')[0])
    return f'{name} ({code})' if name else code
