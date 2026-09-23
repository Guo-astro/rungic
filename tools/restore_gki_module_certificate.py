#!/usr/bin/env python3
"""Keep the OEM GKI module trust anchor in the already tested namespace kernel.

Only works with these two locally verified boot images and equal-size X.509
certificates. No code, configuration, module CRC, or signature policy is changed.
"""
import hashlib
import json
import struct
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / ".work/refs/lxc-install-20260922"
STOCK = Path("/home/kevinzhow/moto-stock-W1WAA36/boot.img")
CANDIDATE = Path("/home/kevinzhow/a17-gsi/boot-gki-userns/boot-gki-userns.img")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    stock = STOCK.read_bytes()
    candidate = CANDIDATE.read_bytes()
    assert sha256(stock) == "f0af1c76dba07456d4b3f33342e58efecac18f54c0590705402771fec5a3139e"
    assert sha256(candidate) == "e6e7f697749db66e253f659c2460420069406ab40c67b3cf77ec286fdd8fc184"
    stock_info = json.loads((BASE / "certificates/stock.json").read_text())
    new_info = json.loads((BASE / "certificates/userns.json").read_text())
    assert len(stock_info) == len(new_info) == 1
    old, new = stock_info[0], new_info[0]
    assert old["length"] == new["length"] == 1357
    length = old["length"]
    source = 4096 + old["kernel_offset"]
    target = 4096 + new["kernel_offset"]
    cert = stock[source:source + length]
    previous_cert = candidate[target:target + length]
    assert cert[:4] == previous_cert[:4] == b"\x30\x82\x05\x49"
    assert candidate.count(previous_cert) == 1
    kernel_size = struct.unpack_from("<I", candidate, 8)[0]
    assert 4096 <= target < target + length <= 4096 + kernel_size
    output = candidate[:target] + cert + candidate[target + length:]
    assert len(output) == len(candidate)
    assert output[:target] == candidate[:target]
    assert output[target + length:] == candidate[target + length:]
    dest = BASE / "boot-gki-userns-stockcert.img"
    dest.write_bytes(output)
    manifest = {
        "stock_boot_sha256": sha256(stock),
        "input_boot_sha256": sha256(candidate),
        "output_boot_sha256": sha256(output),
        "output": str(dest),
        "certificate_boot_offset": target,
        "certificate_length": length,
        "stock_certificate_sha256": sha256(cert),
        "replaced_certificate_sha256": sha256(previous_cert),
        "changed_bytes": sum(a != b for a, b in zip(candidate, output)),
        "change": "Equal-length replacement of built-in X.509 certificate only",
    }
    (BASE / "kernel-certificate-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
