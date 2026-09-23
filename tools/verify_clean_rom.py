#!/usr/bin/env python3
"""Check super sparse encoding, unaffected extents and package manifests."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import xml.etree.ElementTree as ET


def digest(path, algorithm='sha256'):
    with path.open('rb') as f:
        return hashlib.file_digest(f, algorithm).hexdigest()


def main():
    base = Path(sys.argv[1]).resolve()
    work, package = base / 'work', base / 'package'
    parts = json.loads((work / 'partitions.json').read_text())
    product = next(p for p in parts if p['name'] == 'product_a')
    start = product['extents'][0]['sector'] * 512
    end = start + product['bytes']
    block = 8 * 1024 * 1024
    with (work / 'super.raw.img').open('rb') as old, (work / 'super-clean.raw.img').open('rb') as new:
        for lo, hi in ((0, start), (end, (work / 'super.raw.img').stat().st_size)):
            old.seek(lo)
            new.seek(lo)
            while lo < hi:
                n = min(block, hi - lo)
                assert old.read(n) == new.read(n), ('outside product changed', lo)
                lo += n
        new.seek(start)
        with (work / 'product-clean.img').open('rb') as product_file:
            while chunk := product_file.read(block):
                assert new.read(len(chunk)) == chunk, 'embedded product differs'
        while new.tell() < end:
            chunk = new.read(min(block, end - new.tell()))
            assert chunk and not any(chunk), 'former product tail not zero'

    # Decode every sparse chunk against its corresponding raw bytes, including
    # fill values and holes; avoids relying only on an image header check.
    with (package / 'super.img').open('rb') as src, (work / 'super-clean.raw.img').open('rb') as raw:
        magic, major, minor, hsz, chsz, bsz, blocks, chunks, _ = struct.unpack('<IHHHHIIII', src.read(28))
        assert magic == 0xed26ff3a and major == 1 and hsz >= 28 and chsz >= 12
        src.read(hsz - 28)
        for _ in range(chunks):
            typ, _, count, size = struct.unpack('<HHII', src.read(12))
            src.read(chsz - 12)
            remaining, payload = count * bsz, size - chsz
            if typ == 0xcac1:
                assert payload == remaining
                while remaining:
                    n = min(block, remaining)
                    value = src.read(n)
                    assert len(value) == n and raw.read(n) == value, 'sparse RAW mismatch'
                    remaining -= n
            elif typ in (0xcac2, 0xcac3):
                assert payload == (4 if typ == 0xcac2 else 0)
                pattern = src.read(4) if typ == 0xcac2 else bytes(4)
                while remaining:
                    n = min(block, remaining)
                    assert raw.read(n) == pattern * (n // 4), 'sparse FILL/HOLE mismatch'
                    remaining -= n
            else:
                raise AssertionError(('unexpected sparse chunk', hex(typ)))
        assert raw.tell() == blocks * bsz == (work / 'super-clean.raw.img').stat().st_size
        assert not src.read(1)
    md5s = {}
    for xml in ('flashfile.xml', 'servicefile.xml'):
        steps = list(ET.parse(package / xml).iter('step'))
        assert sum(s.attrib.get('partition') == 'super' for s in steps) == 1
        for s in steps:
            if 'filename' not in s.attrib:
                continue
            name = s.attrib['filename']
            if name not in md5s:
                md5s[name] = digest(package / name, 'md5')
            assert s.attrib['MD5'] == md5s[name], (xml, name, 'MD5 mismatch')
    stock = Path('/home/kevinzhow/moto-stock-W1WAA36')
    for name in md5s:
        if name == 'super.img':
            continue
        if name in ('vbmeta.img', 'vbmeta_system.img'):
            old, new = (stock / name).read_bytes(), (package / name).read_bytes()
            assert new[:120] == old[:120] and new[124:] == old[124:]
            assert struct.unpack_from('>I', new, 120)[0] == 3
        else:
            assert md5s[name] == digest(stock / name, 'md5'), (name, 'stock image changed')
    result = dict(status='PASS', super_sparse_roundtrip=True,
                  outside_product_byte_identical=True, embedded_product_byte_identical=True,
                  old_product_tail_zero=True, xml_image_checksums_match=True,
                  other_firmware_images_unchanged=True, vbmeta_only_flags_changed=True,
                  init_boot_is_stock=True, boot_tested=False,
                  super_bytes=(package / 'super.img').stat().st_size,
                  super_sha256=digest(package / 'super.img'))
    (package / 'package-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
