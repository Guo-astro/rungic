#!/usr/bin/env python3
"""Verify and flash an exact-device, full-wipe Rungic release from bootloader fastboot."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Device:
    def __init__(self, root, serial, spec, fastboot_bootloader_value):
        self.serial = serial
        self.spec = spec
        self.fastboot_bootloader_value = fastboot_bootloader_value
        self.fastboot = root / "bin/fastboot"
        self.log = (root / "flash.log").open("w")

    def run(self, *args, timeout=180):
        command = [str(self.fastboot), "-s", self.serial, *(str(arg) for arg in args)]
        print("$ fastboot " + " ".join(str(a) for a in args), flush=True)
        self.log.write("$ " + " ".join(command) + "\n")
        self.log.flush()
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        output = result.stdout + result.stderr
        print(output, end="", flush=True)
        self.log.write(output)
        self.log.flush()
        require(result.returncode == 0, f"fastboot failed: {args[0]}; see {self.log.name}")
        return output

    def var(self, name):
        output = self.run("getvar", name)
        pieces = re.findall(re.escape(name) + r"\[(\d+)\]:\s*([^\r\n]+)", output)
        if pieces:
            return "".join(part.strip() for _, part in sorted(pieces, key=lambda item: int(item[0])))
        match = re.search(r"(?:^|\n)(?:\(bootloader\)\s*)?" + re.escape(name) +
                          r":\s*([^\r\n]+)", output)
        require(match is not None, f"fastboot did not report {name}")
        return match.group(1).strip()

    def bootloader(self):
        identity = self.spec["identity"]
        require(self.var("is-userspace") == "no", "device is not in bootloader fastboot")
        require(self.var("product") == identity["product"], "wrong device product")
        require(self.var("sku") == identity["sku"], "wrong device SKU")
        require(self.var("version-bootloader") == self.fastboot_bootloader_value,
                "wrong firmware bootloader")
        require(self.var("securestate") == "flashing_unlocked", "bootloader is locked")


def verify(root, manifest, spec):
    require(manifest["schema_version"] == 1, "unsupported release manifest")
    require(manifest["device_spec_sha256"] == sha256(root / "device-spec.json"),
            "device spec hash differs from release manifest")
    require(manifest["device_spec_id"] == spec["id"], "device spec ID mismatch")
    require(manifest["product_partition_bytes"] == spec["stock"]["product_partition_bytes"],
            "product partition size mismatch")
    require(manifest["logical_partition_bytes"]["product_a"] == manifest["product_partition_bytes"],
            "stock product logical partition differs from the spec")
    value = manifest["fastboot_bootloader_value"]
    require(spec["identity"]["bootloader"].startswith(value) and
            len(spec["identity"]["bootloader"]) - len(value) <= 1,
            "observed fastboot bootloader is not the Android property version")
    for rel, expected in manifest["files"].items():
        path = root / rel
        require(path.is_file() and path.stat().st_size == expected["bytes"], f"missing/short file: {rel}")
        require(sha256(path) == expected["sha256"], f"SHA-256 mismatch: {rel}")
    require((root / "images/product.erofs.img").stat().st_size <= manifest["product_partition_bytes"],
            "product EROFS cannot fit the target partition")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", help="must match the device serial bound to this release")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--yes-wipe", action="store_true", help="authorize erasing userdata/metadata")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "manifest.json").read_text())
    spec = json.loads((root / "device-spec.json").read_text())
    serial = args.serial or manifest["target_serial"]
    require(serial == manifest["target_serial"], "this release is bound to a different device serial")
    print(f"Verifying {manifest['release_id']} for {serial}...", flush=True)
    verify(root, manifest, spec)
    print("All release files and the device spec are verified.", flush=True)
    if args.verify_only:
        return
    if not args.yes_wipe:
        require(input("This will erase all phone data. Type WIPE to continue: ").strip() == "WIPE",
                "wipe was cancelled")
    device = Device(root, serial, spec, manifest["fastboot_bootloader_value"])
    device.bootloader()
    require(device.var("battery-voltage").isdigit() and int(device.var("battery-voltage")) >= 3700,
            "battery voltage is too low")
    device.run("oem", "fb_mode_clear")
    device.run("set_active", "a")
    require(device.var("current-slot") == "a", "slot a was not selected")
    for name in ("vbmeta", "vbmeta_system"):
        device.run("flash", name + "_a", root / "images" / (name + ".img"), timeout=600)
    for name in ("vendor_boot", "dtbo", "recovery", "pvmfw"):
        device.run("flash", name, root / "stock" / (name + ".img"), timeout=600)
    # Motorola's bootloader accepted the first OEM sparse chunk, then stopped responding on
    # the second (G100, docs/79). Its recovery fastbootd has flashed both chunks successfully.
    device.run("oem", "fb_mode_clear")
    device.run("reboot", "fastboot", timeout=180)
    require(device.var("is-userspace") == "yes", "failed to enter fastbootd")
    require(device.var("unlocked") == "yes", "fastbootd reports locked device")
    require(device.var("current-slot") == "a", "fastbootd slot changed")
    for index in range(manifest["super_chunk_count"]):
        device.run("flash", "super", root / "stock" / f"super.img_sparsechunk.{index}", timeout=900)
    for name, expected in manifest["logical_partition_bytes"].items():
        require(int(device.var("partition-size:" + name), 16) == expected,
                f"restored {name} size differs from OEM verification")
    size = manifest["product_partition_bytes"]
    device.run("-S", "256M", "flash", "product_a", root / "images/product-fastboot.img", timeout=1800)
    require(int(device.var("partition-size:product_a"), 16) == size, "product_a size changed")
    device.run("reboot", "bootloader", timeout=180)
    device.bootloader()
    require(device.var("current-slot") == "a", "bootloader slot changed")
    device.run("flash", "boot_a", root / "images/boot.img", timeout=600)
    device.run("flash", "init_boot_a", root / "images/init_boot.img", timeout=600)
    device.run("erase", "userdata", timeout=900)
    device.run("erase", "metadata", timeout=600)
    device.run("oem", "fb_mode_clear")
    device.run("reboot")
    print("Flash completed. Android first boot will seed RungicOS from product.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        sys.exit(f"release flash stopped: {error}")
