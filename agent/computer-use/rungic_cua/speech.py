"""Speech for voice messages (docs/62): OpenAI text-to-speech as raw PCM.

The key is the voice assistant's (its file, read by rungic_cua.keys, docs/87);
requests go through the proxy in the environment (the rungic-cua launcher sets it).
"""
from __future__ import annotations

import json
import urllib.request

from . import keys

RATE = 24000   # s16le mono, the API's "pcm" format


def synthesize(text: str, *, voice: str = 'marin', instructions: str = '', pad_s: float = 0.3) -> bytes:
    """PCM of `text` with `pad_s` of silence before and after."""
    body = {'model': 'gpt-4o-mini-tts', 'voice': voice, 'input': text, 'response_format': 'pcm'}
    if instructions:
        body['instructions'] = instructions
    request = urllib.request.Request('https://api.openai.com/v1/audio/speech', data=json.dumps(body).encode(),
                                     headers={'Authorization': 'Bearer ' + keys.read('openai-api-key'),
                                              'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        audio = response.read()
    silence = bytes(int(RATE * pad_s) * 2)
    return silence + audio + silence
