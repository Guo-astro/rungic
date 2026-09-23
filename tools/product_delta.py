#!/usr/bin/env python3
"""Reconstruct the verified product image using only Python's standard library."""
import contextlib
import gzip
import hashlib
import json
import shutil
from pathlib import Path


def digest_file(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda: f.read(8 * 1024**2), b''):
            h.update(data)
    return h.hexdigest()


def check(condition, message):
    if not condition:
        raise ValueError('镜像还原失败：' + message)


def restore_product(root, expected_sha256, expected_bytes):
    root = Path(root)
    target = root / 'images/product.img'
    if target.is_file() and target.stat().st_size == expected_bytes:
        print('检查已还原的 product 镜像……', flush=True)
        if digest_file(target) == expected_sha256:
            print('已有镜像校验通过，无需重新还原。', flush=True)
            return target
    with gzip.open(root / 'delta/product.recipe.json.gz', 'rb') as f:
        data = f.read(64 * 1024**2 + 1)
    check(len(data) <= 64 * 1024**2, '差分清单过大')
    recipe = json.loads(data)
    check(isinstance(recipe, dict) and recipe.get('format') == 'moto-block-delta-v1', '差分格式错误')
    check(recipe.get('output_bytes') == expected_bytes and recipe.get('output_sha256') == expected_sha256,
          '目标版本或摘要不匹配')
    ops = recipe.get('operations')
    check(isinstance(ops, list) and bool(ops), '缺少还原步骤')
    sizes = [(root / 'stock' / ('super.img_sparsechunk.' + str(i))).stat().st_size for i in range(34)]
    total = 0
    for op in ops:
        check(isinstance(op, list) and len(op) in (2, 4), '还原步骤错误')
        kind, length = op[0], op[-1]
        check(type(length) is int and length > 0, '块长度错误')
        if kind == 'copy':
            check(len(op) == 4, '复制步骤错误')
            source, offset = op[1:3]
            check(type(source) is int and 0 <= source < 34, '分片编号错误')
            check(type(offset) is int and 0 <= offset <= sizes[source] - length, '复制范围越界')
        else:
            check(kind in ('literal', 'zero') and len(op) == 2, '未知步骤类型')
        total += length
        check(total <= expected_bytes, '目标长度越界')
    check(total == expected_bytes, '目标长度不匹配')
    target.parent.mkdir(exist_ok=True)
    partial = target.with_suffix('.img.partial')
    # A partial file is never used for flashing. Restart a failed reconstruction.
    if partial.exists():
        partial.unlink()
    check(shutil.disk_usage(target.parent).free >= expected_bytes + 256 * 1024**2,
          '电脑空间不足，请至少留出 6 GB 空闲空间')
    print('从原厂分片还原精简镜像，约需写入 5 GB……', flush=True)
    h = hashlib.sha256()
    written = 0
    progress = 0
    try:
        with contextlib.ExitStack() as stack:
            sources = [stack.enter_context((root / 'stock' / ('super.img_sparsechunk.' + str(i))).open('rb')) for i in range(34)]
            literals = stack.enter_context(gzip.open(root / 'delta/product.literals.gz', 'rb'))
            out = stack.enter_context(partial.open('wb'))
            for op in ops:
                kind, remaining = op[0], op[-1]
                if kind == 'copy':
                    source = sources[op[1]]
                    source.seek(op[2])
                while remaining:
                    n = min(remaining, 8 * 1024**2)
                    if kind == 'copy':
                        data = source.read(n)
                    elif kind == 'literal':
                        data = literals.read(n)
                    else:
                        data = b'\0' * n
                    check(len(data) == n, '源数据不完整')
                    out.write(data)
                    h.update(data)
                    written += n
                    remaining -= n
                    if written - progress >= 512 * 1024**2:
                        progress = written
                        print('镜像还原 {:.0%}'.format(written / expected_bytes), flush=True)
            check(literals.read(1) == b'', '差分包含多余数据')
        check(written == expected_bytes and h.hexdigest() == expected_sha256,
              'SHA-256 不匹配；不会连接或刷写手机')
        partial.replace(target)
    except BaseException:
        if partial.exists():
            partial.unlink()
        raise
    print('镜像还原完成，SHA-256 与实机验证版本一致。', flush=True)
    return target
