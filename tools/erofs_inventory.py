#!/usr/bin/env python3
"""Read flat EROFS directories/inode metadata without mounting the image.

Format reference: Linux fs/erofs/erofs_fs.h. File payload decompression is
intentionally delegated to fsck.erofs; this reader rejects unsupported layouts.
"""
import argparse
import base64
import json
import mmap
import stat
import struct


class Erofs:
    def __init__(self, path):
        self.file = open(path, 'rb')
        self.data = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        s = self.data[1024:1152]
        assert struct.unpack_from('<I', s)[0] == 0xE0F5E1E2
        self.block = 1 << s[12]
        self.root = struct.unpack_from('<H', s, 14)[0]
        self.mtime, self.mtime_ns = struct.unpack_from('<QI', s, 24)
        self.meta, self.xattr = struct.unpack_from('<II', s, 40)
        assert not s[91], 'long xattr prefixes are unsupported'

    def inode(self, nid):
        off = self.meta * self.block + nid * 32
        fmt, count, mode = struct.unpack_from('<HHH', self.data, off)
        extended = fmt & 1
        size = struct.unpack_from('<Q' if extended else '<I', self.data, off + 8)[0]
        raw = struct.unpack_from('<I', self.data, off + 16)[0]
        uid, gid = struct.unpack_from('<II' if extended else '<HH', self.data, off + 24)
        mtime, ns = (struct.unpack_from('<QI', self.data, off + 32)
                     if extended else (self.mtime, self.mtime_ns))
        xsize = 12 + (count - 1) * 4 if count else 0
        xstart = off + (64 if extended else 32)
        xattrs = {}

        def read_xattr(pos):
            nlen, index, vlen = struct.unpack_from('<BBH', self.data, pos)
            prefixes = {1: 'user.', 2: 'system.posix_acl_access',
                        3: 'system.posix_acl_default', 4: 'trusted.',
                        6: 'security.'}
            assert index in prefixes, ('unsupported xattr prefix', index)
            name = prefixes[index] + self.data[pos + 4:pos + 4 + nlen].decode()
            value = self.data[pos + 4 + nlen:pos + 4 + nlen + vlen]
            xattrs[name] = base64.b64encode(value).decode()
            return (4 + nlen + vlen + 3) & ~3

        if count:
            shared = self.data[xstart + 4]
            for i in range(shared):
                xid = struct.unpack_from('<I', self.data, xstart + 12 + i * 4)[0]
                read_xattr(self.xattr * self.block + xid * 4)
            pos = xstart + 12 + shared * 4
            while pos < xstart + xsize:
                pos += read_xattr(pos)
            assert pos == xstart + xsize
        return dict(nid=nid, offset=off, inode_size=64 if extended else 32,
                    xattr_size=xsize, layout=(fmt >> 1) & 7, mode=mode,
                    size=size, raw=raw, uid=uid, gid=gid, mtime=mtime,
                    mtime_ns=ns, xattrs=xattrs)

    def flat_data(self, inode):
        size, raw, layout = inode['size'], inode['raw'], inode['layout']
        assert layout in (0, 2), ('unsupported flat layout', layout)
        start = raw * self.block
        if layout == 0:
            return self.data[start:start + size]
        full = (size // self.block) * self.block
        tail = inode['offset'] + inode['inode_size'] + inode['xattr_size']
        return self.data[start:start + full] + self.data[tail:tail + size - full]

    def walk(self, nid=None, path=''):
        inode = self.inode(self.root if nid is None else nid)
        inode['path'] = path
        if stat.S_ISLNK(inode['mode']):
            inode['target'] = self.flat_data(inode).decode()
        yield inode
        if not stat.S_ISDIR(inode['mode']):
            return
        data = self.flat_data(inode)
        for offset in range(0, len(data), self.block):
            block = data[offset:offset + self.block]
            first_name = struct.unpack_from('<H', block, 8)[0]
            assert first_name % 12 == 0 and 12 <= first_name <= len(block)
            for pos in range(0, first_name, 12):
                child, nameoff, typ, _ = struct.unpack_from('<QHBB', block, pos)
                end = (struct.unpack_from('<H', block, pos + 20)[0]
                       if pos + 12 < first_name else len(block))
                name = block[nameoff:end].split(b'\0')[0].decode()
                if name in ('.', '..'):
                    continue
                assert name and '/' not in name
                yield from self.walk(child, path + '/' + name if path else name)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('image')
    p.add_argument('output')
    args = p.parse_args()
    entries = list(Erofs(args.image).walk())
    with open(args.output, 'w') as out:
        json.dump(entries, out, ensure_ascii=False, indent=2)
        out.write('\n')
    for e in entries:
        if e['path'].endswith('.apk'):
            print(f"{e['size']:12d} {e['path']}")
    print(f'{len(entries)} entries total')
