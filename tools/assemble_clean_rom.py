#!/usr/bin/env python3
"""Assemble a separate, unflashed clean ROM folder after product verification."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET


def digest(path, algorithm='sha256'):
    with path.open('rb') as f:
        return hashlib.file_digest(f, algorithm).hexdigest()


def main():
    base = Path(sys.argv[1]).resolve()
    stock = Path('/home/kevinzhow/moto-stock-W1WAA36')
    work, output = base / 'work', base / 'package'
    tools = Path('/home/kevinzhow/android-kernel/prebuilts/kernel-build-tools/linux-x86/bin')
    report = json.loads((work / 'product-verification.json').read_text())
    assert report['status'] == 'PASS'
    assert digest(work / 'product-clean.img') == report['image_sha256']
    assert (work / 'stock-checksums-verified.txt').read_text().startswith('PASS:')
    assert not output.exists(), 'refusing to overwrite an existing package'
    output.mkdir()
    product = next(p for p in json.loads((work / 'partitions.json').read_text()) if p['name'] == 'product_a')
    assert len(product['extents']) == 1
    extent = product['extents'][0]
    assert extent['type'] == 0 and extent['device'] == 0
    start, length = extent['sector'] * 512, extent['sectors'] * 512
    assert report['image_bytes'] <= length
    raw = work / 'super-clean.raw.img'
    assert not raw.exists()
    subprocess.run(['cp', '--reflink=auto', '--sparse=always', str(work / 'super.raw.img'), str(raw)], check=True)
    # Clear the ENTIRE former product extent, including old APK payloads and AVB
    # tree/footer, before writing the new filesystem. Holes read back as zero.
    subprocess.run(['fallocate', '--punch-hole', '--keep-size', '--offset', str(start),
                    '--length', str(length), str(raw)], check=True)
    with raw.open('r+b') as dst, (work / 'product-clean.img').open('rb') as src:
        dst.seek(start)
        shutil.copyfileobj(src, dst, 8 * 1024 * 1024)
    subprocess.run([str(tools / 'img2simg'), str(raw), str(output / 'super.img')], check=True)
    print('Built sparse super.img', flush=True)

    source_tree = ET.parse(stock / 'flashfile.xml')
    names = {s.attrib['filename'] for s in source_tree.iter('step') if 'filename' in s.attrib
             and not s.attrib['filename'].startswith('super.img_sparsechunk.')}
    names.update(('slcf_rev_d_default_v1.0.nvm', 'regulatory_info_default.png',
                  'cmf_color_range_full_list.txt',
                  'MUMBA_CN_W1WAA36.48-23-10_subsidy-DEFAULT_regulatory-DEFAULT_CFC.info.txt'))
    for name in sorted(names):
        subprocess.run(['cp', '--reflink=auto', str(stock / name), str(output / name)], check=True)
    # Use this device's ORIGINAL OEM vbmeta. Only change the standard AVB flags;
    # never substitute an empty/GSI vbmeta with a different key.
    for name in ('vbmeta.img', 'vbmeta_system.img'):
        data = bytearray((output / name).read_bytes())
        assert data[:4] == b'AVB0' and struct.unpack_from('>I', data, 120)[0] == 0
        struct.pack_into('>I', data, 120, 3)
        (output / name).write_bytes(data)
        original = (stock / name).read_bytes()
        assert data[:120] == original[:120] and data[124:] == original[124:]
    # Recalculate every changed XML digest. The service XML deliberately retains
    # the source's erase policy; neither XML is invoked by this build program.
    md5s = {p.name: digest(p, 'md5') for p in output.iterdir() if p.is_file()}
    for xmlname in ('flashfile.xml', 'servicefile.xml'):
        tree = ET.parse(stock / xmlname)
        steps = tree.getroot().find('steps')
        first_super = True
        for step in list(steps):
            name = step.attrib.get('filename', '')
            if name.startswith('super.img_sparsechunk.'):
                if not first_super:
                    steps.remove(step)
                    continue
                first_super = False
                step.set('filename', 'super.img')
                name = 'super.img'
            if name in md5s:
                step.set('MD5', md5s[name])
        ET.indent(tree, space='  ')
        tree.write(output / xmlname, encoding='utf-8', xml_declaration=True)
    for name in ('removed-apps.json', 'product-verification.json', 'stock-checksums-verified.txt'):
        shutil.copy2(work / name, output / name)
    shutil.copy2('/home/kevinzhow/a17-gsi/magisk/Magisk-v31.0.apk', output / 'Magisk-v31.0.apk')
    metadata = dict(firmware='W1WAA36.48-23-10', sku='XT2537-4', variant='mumba_cn/RETCN',
                    removed_apps=15, product_sha256=report['image_sha256'],
                    vbmeta_flags=3, init_boot='stock; Magisk patch pending on target phone',
                    device_flashed=False, boot_tested=False)
    (output / 'build-info.json').write_text(json.dumps(metadata, indent=2) + '\n')
    checksums = '\n'.join(f'{digest(p)}  {p.name}' for p in sorted(output.iterdir()) if p.is_file()) + '\n'
    (output / 'SHA256SUMS').write_text(checksums)
    print('Package:', output, flush=True)


if __name__ == '__main__':
    main()
