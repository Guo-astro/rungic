#!/usr/bin/env python3
"""Verify derived G100 logical images against the stock AVB chain."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


PARTITIONS = ("product", "system", "system_ext", "system_dlkm", "vendor", "vendor_dlkm")
HASH_PARTITIONS = ("boot", "dtbo", "init_boot", "pvmfw", "recovery", "vendor_boot")
BLOCK = 8 * 1024 * 1024


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(BLOCK), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", type=Path)
    parser.add_argument("--avbtool", type=Path, required=True)
    args = parser.parse_args()
    stock = args.stock.resolve(strict=True)
    avbtool = args.avbtool.resolve(strict=True)
    manifest_path = stock / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest["fingerprint"] != (
        "motorola/portov_cn/portov:16/W1VT36H.1-51-8/e9ec8-e96731:user/release-keys"
    ):
        raise ValueError("Unexpected G100 stock fingerprint")
    super_raw = stock / "super.raw.img"
    if (super_raw.stat().st_size != manifest["files"]["super.raw.img"]["bytes"] or
            digest(super_raw) != manifest["files"]["super.raw.img"]["sha256"]):
        raise ValueError("Super image differs from stock manifest")
    with super_raw.open("rb") as stream:
        stream.seek(4096)
        if stream.read(4) != b"gDla":
            raise ValueError("Missing primary liblp geometry")

    logical = {}
    for part in PARTITIONS:
        image = stock / "logical" / f"{part}_a.img"
        if not image.is_file() or image.stat().st_size == 0:
            raise ValueError(f"Missing logical partition: {part}_a")
        link = stock / f"{part}.img"
        if not link.is_symlink() or link.readlink() != Path("logical") / image.name:
            raise ValueError(f"Missing or unexpected AVB link: {link}")
        logical[f"{part}_a.img"] = {"bytes": image.stat().st_size, "sha256": digest(image)}

    result = subprocess.run(
        [str(avbtool), "verify_image", "--image", str(stock / "vbmeta.img"),
         "--follow_chain_partitions"],
        check=True, text=True, capture_output=True,
    )
    verified = set(re.findall(r"^([a-z_]+): Successfully verified ", result.stdout, re.MULTILINE))
    expected = set(PARTITIONS) | set(HASH_PARTITIONS) | {"vbmeta"}
    if not expected.issubset(verified) or result.stdout.count("vbmeta: Successfully verified") != 2:
        raise ValueError(f"Incomplete AVB verification: {sorted(verified)}")

    key_hashes = {}
    for name in ("vbmeta", "vbmeta_system"):
        info = subprocess.run(
            [str(avbtool), "info_image", "--image", str(stock / f"{name}.img")],
            check=True, text=True, capture_output=True,
        ).stdout
        hashes = re.findall(r"Public key \(sha1\):\s+([0-9a-f]{40})", info)
        if not hashes:
            raise ValueError(f"Missing AVB key hash in {name}")
        key_hashes[name] = hashes[0]
        if name == "vbmeta" and (len(hashes) < 2 or hashes[1] != hashes[0]):
            raise ValueError("vbmeta_system chain key differs from top-level vbmeta key")
    if key_hashes["vbmeta"] != key_hashes["vbmeta_system"]:
        raise ValueError("vbmeta_system embedded key differs from chain key")

    report = {
        "build": manifest["build"],
        "stock_manifest_sha256": digest(manifest_path),
        "super_sha256": manifest["files"]["super.raw.img"]["sha256"],
        "logical_images": logical,
        "avb_verified_partitions": sorted(verified),
        "avb_public_key_sha1": key_hashes["vbmeta"],
        "avb_exit_code": result.returncode,
        "flashed": False,
        "device_tested": False,
    }
    (stock / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    (stock / "avb-verification.log").write_text(result.stdout + result.stderr)
    print(json.dumps({"verified": sorted(verified), "report": str(stock / "verification.json")}, indent=2))


if __name__ == "__main__":
    main()
