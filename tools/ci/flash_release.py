#!/usr/bin/env python3
"""Verify and flash an exact-device, full-wipe Rungic release from bootloader fastboot."""

import argparse
import codecs
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import time


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def fastboot_settings(spec, spec_sha256, bootloader_value, adapter=None):
    """Check a recorded device mapping, retaining the original G100 defaults."""
    if adapter is None:
        require(spec["identity"]["bootloader"].startswith(bootloader_value) and
                len(spec["identity"]["bootloader"]) - len(bootloader_value) <= 1,
                "observed fastboot bootloader is not the Android property version")
        return "flashing_unlocked"
    require(adapter.get("schema_version") == 1, "unsupported fastboot adapter")
    require(adapter.get("device_spec_id") == spec["id"] and
            adapter.get("device_spec_sha256") == spec_sha256,
            "fastboot adapter belongs to a different device spec")
    require(adapter.get("android_bootloader") == spec["identity"]["bootloader"] and
            adapter.get("fastboot_bootloader") == bootloader_value,
            "fastboot adapter firmware mapping differs")
    require(adapter.get("securestate") in ("flashing_unlocked", "flashing_unlocked:SDP"),
            "fastboot adapter does not describe an unlocked device")
    # This installer implements the Motorola slot-a / fastbootd plan only.
    require(adapter.get("target_slot") == "a" and adapter.get("super_mode") == "userspace",
            "fastboot adapter requires an unsupported partition plan")
    require(adapter.get("mode_probe_verified") is True,
            "fastboot adapter mode transitions have not been verified")
    return adapter["securestate"]


class Device:
    def __init__(self, root, serial, spec, fastboot_bootloader_value,
                 securestate="flashing_unlocked"):
        self.serial = serial
        self.spec = spec
        self.fastboot_bootloader_value = fastboot_bootloader_value
        self.securestate = securestate
        self.fastboot = root / "bin/fastboot"
        self.log = (root / "flash.log").open("w")

    def phase(self, number, message):
        line = f"\n[{number}/8] {message}\n"
        print(line, end="", flush=True)
        self.log.write(line)
        self.log.flush()

    def run(self, *args, timeout=180):
        command = [str(self.fastboot), "-s", self.serial, *(str(arg) for arg in args)]
        print("$ fastboot " + " ".join(str(a) for a in args), flush=True)
        self.log.write("$ " + " ".join(command) + "\n")
        self.log.flush()
        started = last_output = time.monotonic()
        output = []
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        # Stream transfer/write acknowledgements immediately. capture_output
        # hides all progress until a multi-gigabyte flash finishes.
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    now = time.monotonic()
                    if now - started >= timeout:
                        process.kill()
                        process.wait()
                        raise subprocess.TimeoutExpired(command, timeout)
                    for key, _ in selector.select(min(1, timeout - (now - started))):
                        block = os.read(key.fd, 65536)
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        text = decoder.decode(block)
                        output.append(text)
                        print(text, end="", flush=True)
                        self.log.write(text)
                        self.log.flush()
                        last_output = time.monotonic()
                    if time.monotonic() - last_output >= 10:
                        message = (f"\n等待设备返回进度，已用 {int(time.monotonic() - started)} 秒。"
                                   "请保持 USB 连接；手机可能暂时没有进度显示。\n")
                        print(message, end="", flush=True)
                        self.log.write(message)
                        self.log.flush()
                        last_output = time.monotonic()
            output.append(decoder.decode(b"", final=True))
            remaining = timeout - (time.monotonic() - started)
            try:
                code = process.wait(timeout=max(0, remaining))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise
        require(code == 0, f"fastboot failed: {args[0]}; see {self.log.name}")
        return "".join(output)

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
        require(self.var("securestate") == self.securestate, "bootloader unlock state differs")


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
    adapter = None
    if manifest.get("fastboot_adapter"):
        require(manifest["fastboot_adapter"] == "fastboot-adapter.json" and
                "fastboot-adapter.json" in manifest["files"], "invalid fastboot adapter path")
        adapter = json.loads((root / "fastboot-adapter.json").read_text())
    securestate = fastboot_settings(spec, manifest["device_spec_sha256"], value, adapter)
    for rel, expected in manifest["files"].items():
        path = root / rel
        require(path.is_file() and path.stat().st_size == expected["bytes"], f"missing/short file: {rel}")
        require(sha256(path) == expected["sha256"], f"SHA-256 mismatch: {rel}")
    require((root / "images/product.erofs.img").stat().st_size <= manifest["product_partition_bytes"],
            "product EROFS cannot fit the target partition")
    return securestate


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
    print(f"[1/8] 校验完整安装包 {manifest['release_id']}，目标设备 {serial}…", flush=True)
    securestate = verify(root, manifest, spec)
    print("All release files and the device spec are verified.", flush=True)
    if args.verify_only:
        return
    if not args.yes_wipe:
        require(input("This will erase all phone data. Type WIPE to continue: ").strip() == "WIPE",
                "wipe was cancelled")
    device = Device(root, serial, spec, manifest["fastboot_bootloader_value"], securestate)
    device.phase(2, "检查手机型号、固件和解锁状态")
    device.bootloader()
    require(device.var("battery-voltage").isdigit() and int(device.var("battery-voltage")) >= 3700,
            "battery voltage is too low")
    device.run("oem", "fb_mode_clear")
    device.run("set_active", "a")
    require(device.var("current-slot") == "a", "slot a was not selected")
    device.phase(3, "写入启动辅助分区")
    for name in ("vbmeta", "vbmeta_system"):
        device.run("flash", name + "_a", root / "images" / (name + ".img"), timeout=600)
    for name in ("vendor_boot", "dtbo", "recovery", "pvmfw"):
        device.run("flash", name, root / "stock" / (name + ".img"), timeout=600)
    # Motorola's bootloader accepted the first OEM sparse chunk, then stopped responding on
    # the second (G100, docs/79). Its recovery fastbootd has flashed both chunks successfully.
    device.run("oem", "fb_mode_clear")
    device.phase(4, "切换到系统刷写模式（fastbootd），本机通常需要约一分钟；无需操作手机")
    device.run("reboot", "fastboot", timeout=180)
    require(device.var("is-userspace") == "yes", "failed to enter fastbootd")
    require(device.var("unlocked") == "yes", "fastbootd reports locked device")
    require(device.var("current-slot") == "a", "fastbootd slot changed")
    for index in range(manifest["super_chunk_count"]):
        device.phase(5, f"恢复 Android 系统，分片 {index + 1}/{manifest['super_chunk_count']}")
        device.run("flash", "super", root / "stock" / f"super.img_sparsechunk.{index}", timeout=900)
    for name, expected in manifest["logical_partition_bytes"].items():
        require(int(device.var("partition-size:" + name), 16) == expected,
                f"restored {name} size differs from OEM verification")
    size = manifest["product_partition_bytes"]
    device.phase(6, "写入 Rungic 系统；下方实时显示每个传输分段的发送和写入结果")
    device.run("-S", "256M", "flash", "product_a", root / "images/product-fastboot.img", timeout=1800)
    require(int(device.var("partition-size:product_a"), 16) == size, "product_a size changed")
    device.phase(7, "返回启动刷写模式并安装内核和引导镜像")
    if manifest.get("fastboot_adapter"):
        adapter = json.loads((root / manifest["fastboot_adapter"]).read_text())
        if adapter.get("bootloader_usb_replug_observed"):
            print("本机曾在返回 bootloader 后 USB 不重新枚举。若出现 waiting for，"
                  "且手机已显示 bootloader，请重插 USB；此时尚未开始下一次写入。", flush=True)
    device.run("reboot", "bootloader", timeout=180)
    device.bootloader()
    require(device.var("current-slot") == "a", "bootloader slot changed")
    device.run("flash", "boot_a", root / "images/boot.img", timeout=600)
    device.run("flash", "init_boot_a", root / "images/init_boot.img", timeout=600)
    device.phase(8, "清除用户数据并启动系统")
    device.run("erase", "userdata", timeout=900)
    device.run("erase", "metadata", timeout=600)
    device.run("oem", "fb_mode_clear")
    device.run("reboot")
    print("刷写完成。首次启动会自动初始化并重启一次。完成 Android 引导后打开 Rungic，"
          "等待安装界面自动转到账户设置，再创建账户并进入 Plasma Mobile。", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        sys.exit(f"release flash stopped: {error}")
