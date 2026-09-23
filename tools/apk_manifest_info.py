#!/usr/bin/env python3
"""Extract package/version/SDK fields from Android binary XML manifests."""
import json
import struct
import sys
import zipfile


def manifest_info(path):
    with zipfile.ZipFile(path) as z:
        data = z.read('AndroidManifest.xml')
    typ, header, total = struct.unpack_from('<HHI', data)
    assert typ == 3 and total == len(data), 'not Android binary XML'
    strings = []
    info = {}
    pos = header
    while pos < total:
        typ, hsize, size = struct.unpack_from('<HHI', data, pos)
        assert size >= hsize and pos + size <= total
        if typ == 1:
            count, _, flags, start, _ = struct.unpack_from('<5I', data, pos + 8)
            utf8 = flags & 0x100
            for i in range(count):
                offset = struct.unpack_from('<I', data, pos + hsize + i * 4)[0]
                p = pos + start + offset

                def length(p):
                    if utf8:
                        n = data[p]
                        return (((n & 127) << 8) | data[p+1], p+2) if n & 128 else (n, p+1)
                    n = struct.unpack_from('<H', data, p)[0]
                    return (((n & 32767) << 16) | struct.unpack_from('<H', data, p+2)[0], p+4) if n & 32768 else (n, p+2)

                n, p = length(p)
                if utf8:
                    n, p = length(p)
                strings.append(data[p:p + n * (1 if utf8 else 2)].decode('utf-8' if utf8 else 'utf-16le'))
        elif typ == 0x102:
            _, name, astart, asize, count = struct.unpack_from('<IIHHH', data, pos + hsize)
            tag = strings[name]
            if tag in ('manifest', 'uses-sdk', 'application'):
                values = {}
                for i in range(count):
                    p = pos + hsize + astart + i * asize
                    _, name, raw = struct.unpack_from('<III', data, p)
                    value_type = data[p + 15]
                    value = struct.unpack_from('<I', data, p + 16)[0]
                    values[strings[name]] = (strings[raw] if raw != 0xffffffff else
                                            strings[value] if value_type == 3 else
                                            f'@0x{value:08x}' if value_type == 1 else value)
                info[tag] = values
        pos += size
    return info


if __name__ == '__main__':
    for path in sys.argv[1:]:
        print(json.dumps({'path': path, **manifest_info(path)}, ensure_ascii=False))
