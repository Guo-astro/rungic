# SPDX-License-Identifier: MIT
"""The voice agent's words for people, in the desktop's language.

User-visible text is English in the source and translated from the gettext catalog
rungic-voice-agent (po/zh_CN/rungic-voice-agent.po in this directory, installed to
/usr/share/locale/<lang>/LC_MESSAGES/rungic-voice-agent.mo). The language is Plasma's: the
user's systemd manager takes LANGUAGE/LANG from plasma-localerc, and the service inherits them.

Instructions for the models stay English; they are told the desktop's language instead
(language_note), and answer in the language the user speaks.
"""
from __future__ import annotations

import gettext
import os

DOMAIN = 'rungic-voice-agent'
LOCALEDIR = '/usr/share/locale'

_translation = gettext.translation(DOMAIN, localedir=LOCALEDIR, fallback=True)
_ = _translation.gettext
ngettext = _translation.ngettext

# Names the models are told; any other code is passed as it is (models know locale codes).
NAMES = {'zh_CN': 'Simplified Chinese', 'zh_SG': 'Simplified Chinese', 'zh_TW': 'Traditional Chinese',
         'zh_HK': 'Traditional Chinese', 'zh': 'Chinese', 'en': 'English', 'ja': 'Japanese', 'ko': 'Korean',
         'de': 'German', 'fr': 'French', 'es': 'Spanish', 'it': 'Italian', 'pt': 'Portuguese', 'ru': 'Russian'}


def desktop_language() -> str:
    """The desktop's language as a locale code ('en_US', 'zh_CN'), where gettext looks for it:
    the first entry of LANGUAGE, else LC_ALL, LC_MESSAGES, LANG."""
    for variable in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
        value = os.environ.get(variable, '').split(':')[0].split('.')[0].split('@')[0]
        if value and value not in ('C', 'POSIX'):
            return value
    return 'en_US'


def language_name(code: str | None = None) -> str:
    """'Simplified Chinese (zh_CN)', 'English (en_US)': the language for a model to write in."""
    code = code or desktop_language()
    name = NAMES.get(code) or NAMES.get(code.split('_')[0])
    return f'{name} ({code})' if name else code


def language_note() -> str:
    """The end of a model's instructions: the desktop's language (their rules say when to use it)."""
    return (f"\n\n## The desktop's language\n\nThe user's desktop (KDE Plasma) is set to {language_name()}. "
            'Use it for what the user sees or hears whenever you cannot tell which language they use.\n')
