#!/usr/bin/env python3
"""Read-only preflight for one device spec and an audited OEM extraction."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


def sha256(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def adb(port, serial, *args):
    command = ["adb", "-P", str(port), "-s", serial, *args]
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=30).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("stock", type=Path)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb-port", type=int, default=5037)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text())
    require(spec.get("schema_version") == 1, "unsupported device spec schema")
    identity = spec["identity"]
    stock = args.stock.resolve(strict=True)
    manifest_path = stock / "manifest.json"
    verification_path = stock / "verification.json"
    manifest = json.loads(manifest_path.read_text())
    verification = json.loads(verification_path.read_text())
    require(verification["stock_manifest_sha256"] == sha256(manifest_path), "stock manifest changed")
    require(manifest["archive_sha256"] == spec["stock"]["archive_sha256"], "OEM archive mismatch")
    require(manifest["fingerprint"] == identity["fingerprint"], "OEM fingerprint mismatch")
    require(manifest["device"] == identity["device"], "OEM device mismatch")
    require(manifest["files"]["boot.img"]["sha256"] == spec["stock"]["boot_sha256"],
            "OEM boot manifest mismatch")
    require(sha256(stock / "boot.img") == spec["stock"]["boot_sha256"], "OEM boot changed")
    require(verification["super_sha256"] == spec["stock"]["super_sha256"],
            "OEM super verification mismatch")
    require(verification["avb_public_key_sha1"] == spec["stock"]["avb_public_key_sha1"],
            "OEM AVB key mismatch")
    require(not verification["flashed"] and not verification["device_tested"],
            "stock verification report has unexpected device state")

    devices = subprocess.run(["adb", "-P", str(args.adb_port), "devices"], check=True,
                             capture_output=True, text=True, timeout=30).stdout
    states = dict(re.findall(r"^([^\s]+)\s+(device|offline|unauthorized)$", devices, re.MULTILINE))
    require(states.get(args.serial) == "device", f"target {args.serial} is not authorized on ADB port {args.adb_port}")
    props = {
        name: adb(args.adb_port, args.serial, "shell", "getprop", name)
        for name in ("ro.product.device", "ro.boot.hardware.sku", "ro.build.fingerprint",
                     "ro.bootloader", "ro.build.version.sdk", "ro.boot.flash.locked",
                     "ro.boot.verifiedbootstate", "ro.boot.slot_suffix")
    }
    expected = {
        "ro.product.device": identity["product"],
        "ro.boot.hardware.sku": identity["sku"],
        "ro.build.fingerprint": identity["fingerprint"],
        "ro.bootloader": identity["bootloader"],
        "ro.build.version.sdk": str(spec["release_requirements"]["android_api"]),
        "ro.boot.flash.locked": "0",
        "ro.boot.verifiedbootstate": "orange",
    }
    for name, wanted in expected.items():
        require(props[name] == wanted, f"{name}: got {props[name]!r}; expected {wanted!r}")
    release = adb(args.adb_port, args.serial, "shell", "uname", "-r")
    require(release == spec["kernel"]["stock_release"], "running kernel differs from OEM baseline")
    selinux = adb(args.adb_port, args.serial, "shell", "getenforce")
    require(selinux == "Enforcing", "SELinux is not Enforcing")
    battery = adb(args.adb_port, args.serial, "shell", "dumpsys", "battery")
    match = re.search(r"^\s*level:\s*(\d+)$", battery, re.MULTILINE)
    require(match is not None, "battery level unavailable")
    battery_percent = int(match[1])
    require(battery_percent >= spec["release_requirements"]["minimum_battery_percent"],
            "battery below device spec minimum")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    host_free = shutil.disk_usage(args.output.parent.resolve()).free
    minimum = spec["release_requirements"]["minimum_host_free_gib"] * 1024**3
    require(host_free >= minimum, "host free space below build minimum")

    report = {
        "schema_version": 1,
        "result": "source-and-device-preflight-passed",
        "timestamp_unix": int(time.time()),
        "device_spec_id": spec["id"],
        "device_spec_sha256": sha256(args.spec),
        "serial": args.serial,
        "adb_port": args.adb_port,
        "observed": {"properties": props, "kernel_release": release,
                     "selinux": selinux, "battery_percent": battery_percent,
                     "host_free_bytes": host_free},
        "stock_manifest_sha256": sha256(manifest_path),
        "stock_verification_sha256": sha256(verification_path),
        "kernel_common_commit": spec["kernel"]["common_commit"],
        "note": "Read-only preflight; no kernel, rootfs, firmware bundle, flash, or acceptance has run."
    }
    temporary = args.output.with_name(args.output.name + ".partial")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(args.output)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"preflight failed: {error}", file=sys.stderr)
        raise SystemExit(1)
