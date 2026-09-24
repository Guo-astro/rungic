"""Find a person or chat by how the name sounds (docs/60).

Speech recognition often writes a Chinese name with the wrong characters of the
same sound (周凯文 for 周楷雯). Names are compared by toneless pinyin; the
confusions of accents and recognizers (z/zh, c/ch, s/sh, n/l, f/h, an/ang,
en/eng, in/ing) count as near matches. Chat apps usually search by pinyin as
well, so `search_text()` gives what to type into their search field.
"""
from __future__ import annotations

import difflib
import re

from pypinyin import lazy_pinyin

INITIALS = (('zh', 'z'), ('ch', 'c'), ('sh', 's'))
FINALS = (('ang', 'an'), ('eng', 'en'), ('ing', 'in'))
SWAPS = (('l', 'n'), ('h', 'f'))


def syllables(text: str) -> list[str]:
    """Toneless pinyin syllables of the Chinese characters, Latin words lower-cased."""
    text = re.sub(r'[^\w一-鿿]+', ' ', text).strip()
    out = []
    for piece in lazy_pinyin(text):
        out += [p for p in re.split(r'\s+', piece.lower()) if p]
    return out


def fuzzy(syllable: str) -> str:
    """The syllable with accent-sensitive distinctions removed."""
    for long, short in INITIALS:
        if syllable.startswith(long):
            syllable = short + syllable[len(long):]
            break
    for long, short in FINALS:
        if syllable.endswith(long):
            syllable = syllable[:-len(long)] + short
            break
    for a, b in SWAPS:
        if syllable.startswith(b):
            syllable = a + syllable[1:]
            break
    return syllable


def score(spoken: str, candidate: str) -> float:
    """1.0 same sound, 0.9 same apart from accent-type confusions, else string similarity (at most 0.8)."""
    a, b = syllables(spoken), syllables(candidate)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if [fuzzy(s) for s in a] == [fuzzy(s) for s in b]:
        return 0.9
    return round(0.8 * difflib.SequenceMatcher(None, ''.join(map(fuzzy, a)), ''.join(map(fuzzy, b))).ratio(), 3)


def search_text(name: str) -> str:
    """What to type into a chat app's search field: the pinyin, which also finds same-sounding characters."""
    return ''.join(syllables(name))


def rank(spoken: str, names: list[str], limit: int = 5) -> list[tuple[str, float]]:
    scored = sorted(((n, score(spoken, n)) for n in set(names)), key=lambda item: -item[1])
    return [item for item in scored[:limit] if item[1] > 0.3]
