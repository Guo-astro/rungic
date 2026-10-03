# SPDX-License-Identifier: MIT
"""The OCR contract from the Linux side (quality/contracts/ocr.json): the real
agent/computer-use/typesafe/linux_ocr.py sends a capture's pixels to tools/contracts.py's stand-in of
the platform bridge and reads its lines. The provider's side is the acceptance scenario contract.ocr."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'agent/computer-use/typesafe'))
import contracts  # noqa: E402

Image = pytest.importorskip('PIL.Image')
import linux_ocr  # noqa: E402

LINES = {'lines': [{'text': 'Settings', 'score': 0.98, 'box': [4, 6, 60, 26]},
                   {'text': '设置', 'score': 0.91, 'box': [70.5, 6, 100, 26]}], 'ms': {'det': 120, 'rec': 80}}


def picture():
    image = Image.new('RGBA', (100, 40), (250, 250, 250, 255))
    for x in range(10, 20):
        image.putpixel((x, 20), (0, 0, 0, 255))
    return image


# covers[consumer]: iface:ocr
def test_the_pixels_go_to_android_and_its_lines_come_back(monkeypatch):
    with contracts.StandIn('ocr', {'ocr': LINES}) as android:
        monkeypatch.setattr(linux_ocr, 'SOCKET', android.path)
        monkeypatch.setattr(linux_ocr, 'ENGINE', 'android')
        monkeypatch.setenv('https_proxy', 'http://192.168.5.45:6152')
        lines = linux_ocr.recognize(picture(), scale=3.0)
    assert lines == [('Settings', 0.98, (4.0, 6.0, 60.0, 26.0)), ('设置', 0.91, (70.5, 6.0, 100.0, 26.0))]
    [request] = android.requests
    assert request == {'op': 'ocr', 'width': 100, 'height': 40, 'format': 'rgb', 'bytes': 12000,
                       'proxy': 'http://192.168.5.45:6152', 'det_scale': 0.5}
    # The pixels as RGB, row by row (the alpha channel dropped).
    assert android.payloads == [picture().convert('RGB').tobytes()]
    assert android.problems == []


# covers[consumer]: iface:ocr
def test_an_android_without_models_yet_is_read_on_the_cpu(monkeypatch):
    downloading = {'available': False, 'downloading': True, 'received': 1048576, 'total': 9437184,
                   'error': 'OCR models are downloading (1 of 9 MB)'}
    local = [('from the cpu', 0.9, (0.0, 0.0, 1.0, 1.0))]
    with contracts.StandIn('ocr', handler=lambda name, request: downloading) as android:
        monkeypatch.setattr(linux_ocr, 'SOCKET', android.path)
        monkeypatch.setattr(linux_ocr, 'ENGINE', 'android')
        monkeypatch.setattr(linux_ocr, 'local', lambda image: local)
        assert linux_ocr.recognize(picture()) == local
    assert len(android.requests) == 1 and android.payloads == [picture().convert('RGB').tobytes()]
