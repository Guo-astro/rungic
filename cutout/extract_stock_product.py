#!/usr/bin/env python3
"""Extract product_a from the remote Motorola super sparsechunks (ZIP). Resumable."""
from __future__ import annotations

import os
import struct
import sys
import urllib.request
import zlib

sys.path.insert(0, "/home/kevinzhow/a17-gsi/dumps")
from remote_zip_extract import (  # noqa: E402
    Remote,
    parse_central_directory,
    parse_eocd,
    parse_zip64_eocd,
)

URL = (
    "https://mirrors.lolinet.com/firmware/lenomola/2026/mumba_retcn/official/RETCN/"
    "XT2537-4_MUMBA_RETCN_16_W1WAA36.48-23-10_subsidy-DEFAULT_regulatory-DEFAULT_CFC.xml.zip"
)
PRODUCT_OFF = 2048 * 512
PRODUCT_LEN = 14869344 * 512
SPARSE_MAGIC = 0xED26FF3A
CHUNK_RAW, CHUNK_FILL, CHUNK_DONT, CHUNK_CRC = 0xCAC1, 0xCAC2, 0xCAC3, 0xCAC4


def zip_entries(remote: Remote):
    tail_len = min(131072, remote.size)
    tail = remote.range(remote.size - tail_len, remote.size - 1)
    parsed = parse_eocd(tail, remote.size)
    if parsed[0] == "zip64":
        zoff = parsed[1]
        zeocd = remote.range(zoff, min(zoff + 255, remote.size - 1))
        cd_off, cd_size, _n = parse_zip64_eocd(zeocd)
    else:
        cd_off, cd_size, _n = parsed
    cd = remote.range(cd_off, cd_off + cd_size - 1)
    return parse_central_directory(cd)


def http_range(remote: Remote, start: int, end: int) -> bytes:
    req = urllib.request.Request(
        remote.url,
        headers={
            "Range": f"bytes={start}-{end}",
            "User-Agent": "Mozilla/5.0 remote-zip-extract",
        },
        method="GET",
    )
    with remote.opener.open(req, timeout=300) as resp:
        data = resp.read()
    expect = end - start + 1
    if len(data) != expect:
        raise SystemExit(f"short range {start}-{end}: got {len(data)} expected {expect}")
    return data


def stream_zip_member(remote: Remote, entry: dict, dest: str) -> None:
    lfh = remote.range(entry["local_off"], entry["local_off"] + 29)
    sig, _ver, _flags, method, _t, _d, _crc, _csz, _usz, nlen, elen = struct.unpack(
        "<IHHHHHIIIHH", lfh
    )
    if sig != 0x04034B50:
        raise SystemExit(f"bad lfh {sig:#x}")
    data_off = entry["local_off"] + 30 + nlen + elen
    data_end = data_off + entry["comp_size"] - 1
    dec = zlib.decompressobj(-15) if method == 8 else None
    step = 8 * 1024 * 1024
    got = 0
    with open(dest, "wb") as out:
        pos = data_off
        while pos <= data_end:
            end = min(pos + step - 1, data_end)
            piece = http_range(remote, pos, end)
            got += len(piece)
            if dec is None:
                out.write(piece)
            else:
                out.write(dec.decompress(piece))
            pos = end + 1
            print(f"    dl {got}/{entry['comp_size']}", flush=True)
        if dec is not None:
            out.write(dec.flush())


def apply_sparse_file(sparse_path: str, out, p0: int, p1: int) -> int:
    with open(sparse_path, "rb") as inf:
        hdr = inf.read(28)
        magic, _maj, _min, hdr_sz, chunk_hdr_sz, blk_sz, total_blks, total_chunks, _crc = (
            struct.unpack("<IHHHHIIII", hdr)
        )
        if magic != SPARSE_MAGIC:
            raise SystemExit("not sparse")
        if hdr_sz > 28:
            inf.read(hdr_sz - 28)
        pos = 0
        written = 0
        for _i in range(total_chunks):
            ch = inf.read(12)
            if len(ch) < 12:
                raise SystemExit(f"short chunk header {len(ch)}")
            ctype, _res, nblks, total_sz = struct.unpack("<HHII", ch)
            extra = chunk_hdr_sz - 12
            if extra:
                inf.read(extra)
            data_sz = total_sz - chunk_hdr_sz
            span = nblks * blk_sz
            if ctype == CHUNK_RAW:
                left = data_sz
                cur = pos
                while left:
                    n = min(left, 8 * 1024 * 1024)
                    raw = inf.read(n)
                    written += _copy_window(out, cur, raw, p0, p1)
                    cur += len(raw)
                    left -= len(raw)
                pos += span
            elif ctype == CHUNK_FILL:
                fill = inf.read(4)
                if pos < p1 and pos + span > p0:
                    # only materialize the overlapping window
                    a = max(pos, p0)
                    b = min(pos + span, p1)
                    out.seek(a - p0)
                    remain = b - a
                    block = fill * (1024 * 1024 // 4)
                    while remain:
                        n = min(remain, len(block))
                        out.write(block[:n] if n < len(block) else block)
                        remain -= n
                    written += b - a
                pos += span
            elif ctype == CHUNK_DONT:
                pos += span
            elif ctype == CHUNK_CRC:
                inf.read(data_sz)
            else:
                raise SystemExit(f"chunk {ctype:#x}")
        return written


def _copy_window(out, pos: int, data: bytes, p0: int, p1: int) -> int:
    start = pos
    end = pos + len(data)
    if end <= p0 or start >= p1:
        return 0
    a = max(start, p0)
    b = min(end, p1)
    out.seek(a - p0)
    out.write(data[a - start : b - start])
    return b - a


def main():
    out_dir = "/home/kevinzhow/a17-gsi/stock-super"
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(out_dir, "product_a.img")
    os.makedirs(out_dir, exist_ok=True)
    done_path = os.path.join(out_dir, "product_extract.done")
    done = set()
    if os.path.exists(done_path):
        done = set(open(done_path).read().split())
    print(f"product window super[{PRODUCT_OFF}:{PRODUCT_OFF+PRODUCT_LEN}) -> {out_path}", flush=True)
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "http://127.0.0.1:8080"
    print(f"proxy {proxy}", flush=True)
    remote = Remote(URL, proxy)
    entries = zip_entries(remote)
    chunks = [e for e in entries if "sparsechunk" in e["name"]]
    chunks.sort(key=lambda e: int(e["name"].rsplit(".", 1)[-1]))
    print(f"{len(chunks)} sparsechunks, already done={sorted(done)}", flush=True)
    mode = "r+b" if os.path.exists(out_path) and os.path.getsize(out_path) == PRODUCT_LEN else "wb"
    with open(out_path, mode) as out:
        if mode == "wb":
            out.truncate(PRODUCT_LEN)
        total_w = 0
        for e in chunks:
            name = os.path.basename(e["name"])
            if name in done:
                print(f"skip {name}", flush=True)
                continue
            sparse_path = os.path.join(out_dir, name)
            print(f"fetch {name} {e['comp_size']}...", flush=True)
            stream_zip_member(remote, e, sparse_path)
            print(f"  apply {os.path.getsize(sparse_path)}", flush=True)
            needle = "config_mainBuiltInDisplayCutout".encode("utf-16le")
            with open(sparse_path, "rb") as sf:
                blob = sf.read()
            idx = blob.find(needle)
            if idx >= 0:
                print(f"  FOUND cutout string at sparse offset {idx}", flush=True)
                snippet = blob[max(0, idx - 64) : idx + 256]
                print("  context", snippet, flush=True)
                hit_path = os.path.join(out_dir, f"hit-{name}.bin")
                with open(hit_path, "wb") as hf:
                    hf.write(blob[max(0, idx - 4096) : idx + 8192])
                print(f"  saved {hit_path}", flush=True)
            del blob
            w = apply_sparse_file(sparse_path, out, PRODUCT_OFF, PRODUCT_OFF + PRODUCT_LEN)
            out.flush()
            total_w += w
            print(f"  wrote {w} this chunk", flush=True)
            os.remove(sparse_path)
            with open(done_path, "a") as df:
                df.write(name + "\n")
            done.add(name)
    # report fill
    import subprocess
    print("done file", os.path.getsize(out_path), flush=True)


if __name__ == "__main__":
    main()
