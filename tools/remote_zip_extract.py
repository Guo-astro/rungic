#!/usr/bin/env python3
"""Extract named files from a remote ZIP via HTTP Range (ZIP and ZIP64)."""
from __future__ import annotations

import argparse
import os
import struct
import sys
import urllib.request

EOCD_SIG = 0x06054B50
ZIP64_LOC_SIG = 0x07064B50
ZIP64_EOCD_SIG = 0x06064B50
CDFH_SIG = 0x02014B50
LFH_SIG = 0x04034B50


def make_opener(proxy: str | None):
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        return urllib.request.build_opener(handler)
    return urllib.request.build_opener()


class Remote:
    def __init__(self, url: str, proxy: str | None):
        self.url = url
        self.opener = make_opener(proxy)
        self.size = self._size()

    def _req(self, headers: dict) -> bytes:
        req = urllib.request.Request(self.url, headers=headers, method="GET")
        with self.opener.open(req, timeout=60) as resp:
            return resp.read()

    def _size(self) -> int:
        req = urllib.request.Request(self.url, method="HEAD")
        try:
            with self.opener.open(req, timeout=30) as resp:
                length = resp.headers.get("Content-Length")
                if length:
                    return int(length)
        except Exception:
            pass
        req = urllib.request.Request(self.url, headers={"Range": "bytes=0-0"}, method="GET")
        with self.opener.open(req, timeout=30) as resp:
            cr = resp.headers.get("Content-Range", "")
            # bytes 0-0/TOTAL
            if "/" in cr:
                return int(cr.split("/")[-1])
        raise SystemExit("cannot determine remote size")

    def range(self, start: int, end: int) -> bytes:
        """Inclusive start-end."""
        if end >= self.size:
            end = self.size - 1
        if start < 0 or start > end:
            raise ValueError(f"bad range {start}-{end} size={self.size}")
        headers = {
            "Range": f"bytes={start}-{end}",
            "User-Agent": "Mozilla/5.0 remote-zip-extract",
        }
        data = self._req(headers)
        expect = end - start + 1
        if len(data) != expect:
            raise SystemExit(f"short range {start}-{end}: got {len(data)} expected {expect}")
        return data


def parse_eocd(tail: bytes, file_size: int):
    # Search EOCD from the end. Comment max 65535, we fetched enough.
    sig = struct.pack("<I", EOCD_SIG)
    idx = tail.rfind(sig)
    if idx < 0:
        raise SystemExit("EOCD signature not found")
    eocd = tail[idx:]
    (
        _sig,
        disk,
        cd_disk,
        n_this,
        n_total,
        cd_size,
        cd_off,
        comment_len,
    ) = struct.unpack_from("<IHHHHIIH", eocd, 0)
    zip64 = n_total == 0xFFFF or cd_size == 0xFFFFFFFF or cd_off == 0xFFFFFFFF
    if not zip64:
        return cd_off, cd_size, n_total

    loc_sig = struct.pack("<I", ZIP64_LOC_SIG)
    loc_idx = tail.rfind(loc_sig)
    if loc_idx < 0:
        raise SystemExit("ZIP64 locator not found")
    _lsig, _disk, zip64_eocd_off, _ndisks = struct.unpack_from("<IIQI", tail, loc_idx)
    return "zip64", zip64_eocd_off


def parse_zip64_eocd(blob: bytes):
    (
        sig,
        size,
        ver_made,
        ver_need,
        disk,
        cd_disk,
        n_this,
        n_total,
        cd_size,
        cd_off,
    ) = struct.unpack_from("<IQHHIIQQQQ", blob, 0)
    if sig != ZIP64_EOCD_SIG:
        raise SystemExit(f"bad zip64 eocd sig {sig:#x}")
    return cd_off, cd_size, n_total


def parse_central_directory(cd: bytes):
    entries = []
    pos = 0
    while pos + 46 <= len(cd):
        sig = struct.unpack_from("<I", cd, pos)[0]
        if sig != CDFH_SIG:
            break
        (
            _sig,
            ver_made,
            ver_need,
            flags,
            method,
            mtime,
            mdate,
            crc,
            comp_size,
            uncomp_size,
            name_len,
            extra_len,
            comment_len,
            disk_start,
            int_attr,
            ext_attr,
            local_off,
        ) = struct.unpack_from("<IHHHHHHIIIHHHHHII", cd, pos)
        name = cd[pos + 46 : pos + 46 + name_len].decode("utf-8", "replace")
        extra = cd[pos + 46 + name_len : pos + 46 + name_len + extra_len]
        # ZIP64 extra: id 1
        if (
            comp_size == 0xFFFFFFFF
            or uncomp_size == 0xFFFFFFFF
            or local_off == 0xFFFFFFFF
        ):
            epos = 0
            while epos + 4 <= len(extra):
                eid, esize = struct.unpack_from("<HH", extra, epos)
                payload = extra[epos + 4 : epos + 4 + esize]
                if eid == 1:
                    p = 0
                    if uncomp_size == 0xFFFFFFFF:
                        uncomp_size = struct.unpack_from("<Q", payload, p)[0]
                        p += 8
                    if comp_size == 0xFFFFFFFF:
                        comp_size = struct.unpack_from("<Q", payload, p)[0]
                        p += 8
                    if local_off == 0xFFFFFFFF:
                        local_off = struct.unpack_from("<Q", payload, p)[0]
                        p += 8
                    break
                epos += 4 + esize
        entries.append(
            {
                "name": name,
                "method": method,
                "comp_size": comp_size,
                "uncomp_size": uncomp_size,
                "local_off": local_off,
            }
        )
        pos += 46 + name_len + extra_len + comment_len
    return entries


def extract_file(remote: Remote, entry: dict, dest: str):
    # Local file header is 30 bytes + name + extra, then data
    lfh = remote.range(entry["local_off"], entry["local_off"] + 29)
    sig, ver, flags, method, t, d, crc, csz, usz, nlen, elen = struct.unpack(
        "<IHHHHHIIIHH", lfh
    )
    if sig != LFH_SIG:
        raise SystemExit(f"bad local header for {entry['name']}: {sig:#x}")
    data_off = entry["local_off"] + 30 + nlen + elen
    data_end = data_off + entry["comp_size"] - 1
    print(
        f"  downloading {entry['name']}  {entry['uncomp_size']} bytes "
        f"(method={method}) from {data_off}",
        flush=True,
    )
    blob = remote.range(data_off, data_end)
    if method == 0:
        payload = blob
    elif method == 8:
        import zlib

        payload = zlib.decompress(blob, -15)
    else:
        raise SystemExit(f"unsupported compression method {method} for {entry['name']}")
    if len(payload) != entry["uncomp_size"]:
        raise SystemExit(
            f"size mismatch {entry['name']}: {len(payload)} != {entry['uncomp_size']}"
        )
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "wb") as f:
        f.write(payload)
    print(f"  wrote {dest} ({len(payload)} bytes)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("names", nargs="+")
    args = ap.parse_args()

    print(f"HEAD {args.url}", flush=True)
    remote = Remote(args.url, args.proxy)
    print(f"remote size {remote.size}", flush=True)

    tail_len = min(131072, remote.size)
    tail = remote.range(remote.size - tail_len, remote.size - 1)
    parsed = parse_eocd(tail, remote.size)
    if parsed[0] == "zip64":
        zoff = parsed[1]
        # ZIP64 EOCD is variable; 56 bytes min, fetch 256
        zeocd = remote.range(zoff, zoff + 255)
        cd_off, cd_size, n_total = parse_zip64_eocd(zeocd)
    else:
        cd_off, cd_size, n_total = parsed
    print(f"central directory offset={cd_off} size={cd_size} entries={n_total}", flush=True)
    cd = remote.range(cd_off, cd_off + cd_size - 1)
    entries = parse_central_directory(cd)
    print(f"parsed {len(entries)} entries", flush=True)
    by_base = {os.path.basename(e["name"]): e for e in entries}
    wanted = []
    for name in args.names:
        if name in by_base:
            wanted.append(by_base[name])
        else:
            # substring match
            hits = [e for e in entries if e["name"].endswith("/" + name) or e["name"] == name]
            if not hits:
                print(f"MISSING {name}", flush=True)
                continue
            wanted.append(hits[0])
    if not wanted:
        print("available basenames:", sorted({os.path.basename(e["name"]) for e in entries}))
        raise SystemExit("no requested files found")
    for e in wanted:
        dest = os.path.join(args.out, os.path.basename(e["name"]))
        extract_file(remote, e, dest)


if __name__ == "__main__":
    main()
