#!/usr/bin/env python3
"""Build a byte-exact copy/literal delta against original Motorola sparse files."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct


def raw_regions(path):
    with path.open('rb') as f:
        header = f.read(28)
        magic, major, minor, fhs, chs, block, blocks, chunks, checksum = struct.unpack('<I4H4I', header)
        if magic != 0xED26FF3A or major != 1 or fhs < 28 or chs < 12 or block != 4096:
            raise ValueError('Unsupported sparse header: ' + str(path))
        f.seek(fhs)
        logical = 0
        for _ in range(chunks):
            record = f.read(chs)
            kind, reserved, count, size = struct.unpack('<2H2I', record[:12])
            n = size - chs
            if n < 0 or f.tell() + n > path.stat().st_size:
                raise ValueError('Invalid sparse record')
            if kind == 0xCAC1:
                if n != count * block:
                    raise ValueError('RAW length mismatch')
                yield f.tell(), n
            elif kind == 0xCAC2:
                if n != 4:
                    raise ValueError('Invalid FILL record')
            elif kind == 0xCAC3:
                if n != 0:
                    raise ValueError('Invalid DONT_CARE record')
            elif kind == 0xCAC4:
                if n != 4 or count != 0:
                    raise ValueError('Invalid CRC record')
            else:
                raise ValueError('Unknown sparse record')
            logical += count
            f.seek(n, 1)
        if logical != blocks or f.tell() != path.stat().st_size:
            raise ValueError('Sparse length mismatch')


def build(stock, target, dest):
    dest.mkdir(parents=True, exist_ok=True)
    index = {}
    zero = b'\0' * 4096
    for i in range(34):
        path = stock / ('super.img_sparsechunk.' + str(i))
        with path.open('rb') as f:
            for start, length in raw_regions(path):
                f.seek(start)
                for offset in range(start, start + length, 4096):
                    data = f.read(4096)
                    if data != zero:
                        index.setdefault(hashlib.sha256(data).digest(), (i, offset))
        print('Indexed source {}/34, unique blocks {}'.format(i + 1, len(index)), flush=True)
    ops = []
    stats = dict(copy=0, literal=0, zero=0)
    digest = hashlib.sha256()

    def emit(op):
        kind, n = op[0], op[-1]
        stats[kind] += n
        if ops and kind == ops[-1][0]:
            last = ops[-1]
            if kind != 'copy' or (last[1] == op[1] and last[2] + last[3] == op[2]):
                last[-1] += n
                return
        ops.append(op)

    with target.open('rb') as f, gzip.open(dest / 'product.literals.gz', 'wb', compresslevel=6) as literals:
        def literal(data):
            if data:
                digest.update(data)
                literals.write(data)
                emit(['literal', len(data)])
        progress = 0
        for start, length in raw_regions(target):
            literal(f.read(start - f.tell()))
            for offset in range(start, start + length, 4096):
                data = f.read(4096)
                digest.update(data)
                if data == zero:
                    emit(['zero', len(data)])
                else:
                    source = index.get(hashlib.sha256(data).digest())
                    if source is None:
                        literals.write(data)
                        emit(['literal', len(data)])
                    else:
                        emit(['copy', source[0], source[1], len(data)])
                if f.tell() - progress >= 256 * 1024**2:
                    progress = f.tell()
                    print('Target {:.1f} GiB, copied {:.1%}, literal {:.1f} MiB'.format(progress / 2**30, stats['copy'] / progress, stats['literal'] / 2**20), flush=True)
        literal(f.read())
    recipe = dict(format='moto-block-delta-v1', output_bytes=target.stat().st_size,
                  output_sha256=digest.hexdigest(), stats=stats, operations=ops)
    with gzip.open(dest / 'product.recipe.json.gz', 'wt', encoding='utf-8', compresslevel=9) as f:
        json.dump(recipe, f, separators=(',', ':'))
    print(json.dumps({k: v for k, v in recipe.items() if k != 'operations'}, indent=2), flush=True)
    print('Operations:', len(ops), 'Delta bytes:', sum(p.stat().st_size for p in dest.iterdir()), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stock', type=Path)
    p.add_argument('target', type=Path)
    p.add_argument('dest', type=Path)
    args = p.parse_args()
    build(args.stock, args.target, args.dest)
