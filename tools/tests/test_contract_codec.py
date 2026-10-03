# SPDX-License-Identifier: MIT
"""The hardware codec's contract from the Linux side (quality/contracts/codec.json): the real
shared/media/codec-client.c, the transport of the GStreamer and FFmpeg adapters, built here and driven
by tools/tests/contract_codec_driver.c against tools/contracts.py's CodecStandIn (descriptors, shared
memory and records as CodecBridge sends them). The provider's side is acceptance codec.hw on the phone."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import contracts  # noqa: E402

AU = bytes([0, 0, 0, 1, 0x67, 0x42, 0, 0x1e, 0, 0, 0, 1, 0x65, 0x88, 0x84])
W, H = 64, 48


@pytest.fixture(scope='module')
def driver(tmp_path_factory):
    compiler = shutil.which('cc') or shutil.which('gcc')
    if not compiler:
        pytest.skip('no C compiler')
    out = tmp_path_factory.mktemp('codec') / 'contract_codec_driver'
    subprocess.run([compiler, '-std=gnu11', '-O1', f'-I{ROOT}/shared/media',
                    str(ROOT / 'tools/tests/contract_codec_driver.c'), str(ROOT / 'shared/media/codec-client.c'),
                    '-Wl,--wrap=connect', '-lpthread', '-o', str(out)], check=True)
    return out


def run(driver, broker, mode, **env):
    done = subprocess.run([str(driver), mode, str(W), str(H)], capture_output=True, text=True, timeout=30,
                          env={**os.environ, 'RUNGIC_CODEC_TEST_SOCKET': broker.path, **env})
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def picture():
    """A decoded 64x48 picture as Android's hardware decoder gives it: rows padded to 80 bytes and the
    chroma semi-planar (U and V interleaved, pixel step 2: the U and V planes overlap)."""
    y = bytearray(b'\xee' * 80 * H)
    uv = bytearray(b'\xee' * 80 * (H // 2))
    for row in range(H):
        for x in range(W):
            y[row * 80 + x] = (x + 3 * row) & 255
    for row in range(H // 2):
        for i in range(W // 2):
            uv[row * 80 + 2 * i] = (100 + i + row) & 255
            uv[row * 80 + 2 * i + 1] = (200 + 2 * i + row) & 255
    chroma = 80 * (H // 2 - 1) + (W // 2 - 1) * 2 + 1
    planes = [(80, 1, bytes(y)), (80, 2, bytes(uv[:chroma])), (80, 2, bytes(uv[1:1 + chroma]))]
    expected = {'y': bytes((x + 3 * r) & 255 for r in range(H) for x in range(W)),
                'u': bytes((100 + i + r) & 255 for r in range(H // 2) for i in range(W // 2)),
                'v': bytes((200 + 2 * i + r) & 255 for r in range(H // 2) for i in range(W // 2))}
    return planes, expected


# covers[consumer]: iface:codec
def test_a_decoded_picture_reaches_the_adapter_as_i420(driver):
    planes, expected = picture()

    def decode(config, frame):
        return [{'type': 'DECODED', 'id': frame['id'], 'flags': 0, 'pts': frame['pts'],
                 'width': W, 'height': H, 'crop': (0, 0), 'planes': planes}]
    with contracts.CodecStandIn(output=decode) as broker:
        result = run(driver, broker, 'decode')
    assert result['open'] is True and result['name'] == 'c2.qti.avc.decoder'
    [config] = broker.configs
    assert (config['encoder'], config['kind'], config['width'], config['height']) == (0, 0, W, H)
    [frame] = broker.frames
    assert frame['data'] == AU and frame['id'] == 7 and frame['pts'] == 1234567890123
    [picture_] = result['frame_records']
    assert (picture_['type'], picture_['id'], picture_['pts']) == (2, 7, 1234567890123)
    assert picture_['copied'] is True
    for plane in 'yuv':
        assert bytes.fromhex(picture_[plane]) == expected[plane], plane
    # A drain ends with EOS; a flush makes the codec usable again.
    assert result['frame'] == 0 and result['drain'] == 0 and result['ended'] == 1
    assert result['flush'] == 0 and result['ended_after_flush'] == 0
    assert (result['inputs'], result['outputs']) == (1, 1)
    assert broker.commands == [1, 2, 3] and broker.problems == []


# covers[consumer]: iface:codec
def test_an_encoded_frame_and_its_headers_reach_the_adapter(driver):
    def encode(config, frame):
        return [{'type': 'CONFIG', 'id': 0, 'flags': 2, 'pts': 0, 'data': AU[:8]},
                {'type': 'ENCODED', 'id': frame['id'], 'flags': 1, 'pts': frame['pts'], 'data': AU[8:]}]
    with contracts.CodecStandIn(output=encode) as broker:
        result = run(driver, broker, 'encode')
    assert result['name'] == 'c2.qti.avc.encoder'
    [config] = broker.configs
    assert (config['encoder'], config['fps_num'], config['fps_den'], config['bitrate'], config['key_interval']) == \
        (1, 30, 1, 2000000, 1)
    [frame] = broker.frames
    assert frame['data'] == bytes((i * 7) & 255 for i in range(W * H * 3 // 2)) and frame['flags'] == 1
    headers, coded = result['frame_records']
    assert (headers['type'], bytes.fromhex(headers['data'])) == (3, AU[:8])
    assert (coded['type'], coded['id'], coded['flags'], bytes.fromhex(coded['data'])) == (1, 7, 1, AU[8:])
    assert result['outputs'] == 1, 'codec headers are not counted as output frames'
    assert broker.problems == []


# covers[consumer]: iface:codec
def test_a_refused_configuration_is_the_adapters_error(driver):
    with contracts.CodecStandIn(reject=lambda config: 'Size unsupported by hardware') as broker:
        result = run(driver, broker, 'decode')
    assert result['open'] is False and 'Size unsupported by hardware' in result['error']
    assert broker.frames == []


# covers[consumer]: iface:codec
def test_disabled_hardware_never_reaches_the_broker(driver):
    with contracts.CodecStandIn() as broker:
        result = run(driver, broker, 'decode', RUNGIC_CODEC_DISABLE='1')
    assert result['open'] is False and 'disabled' in result['error']
    assert broker.configs == []
