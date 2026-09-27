#!/usr/bin/env python3
"""Compose one exact-device, full-wipe Android/Rungic flash directory."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("spec", "stock", "product-image", "product-report", "boot",
                 "init-boot", "init-boot-report", "rootfs-report", "host-report",
                 "kernel-abi-report", "package-lock", "img2simg", "fastboot", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--fastboot-bootloader-value", required=True,
                        help="exact segmented fastboot getvar value observed on the target")
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    stock_manifest = json.loads((args.stock / "manifest.json").read_text())
    stock_verification = json.loads((args.stock / "verification.json").read_text())
    product_report = json.loads(args.product_report.read_text())
    init_report = json.loads(args.init_boot_report.read_text())
    rootfs_report = json.loads(args.rootfs_report.read_text())
    host_report = json.loads(args.host_report.read_text())
    kernel_report = json.loads(args.kernel_abi_report.read_text())
    if init_report["init_boot_sha256"] != sha256(args.init_boot):
        raise ValueError("init_boot differs from its bootstrap injection report")
    if rootfs_report["rootfs_sha256"] != product_report["rootfs_sha256"] or \
            rootfs_report["compressed_sha256"] != product_report["payload_sha256"]["etc/rungic/rootfs.img.gz"]:
        raise ValueError("product rootfs differs from CI2 report")
    if rootfs_report["filesystem_check"] != 0 or rootfs_report["arch"] != "arm64":
        raise ValueError("CI2 filesystem or architecture check did not pass")
    if rootfs_report["package_lock_sha256"] != sha256(args.package_lock):
        raise ValueError("package lock differs from CI2 report")
    if host_report["archive_sha256"] != product_report["payload_sha256"]["etc/rungic/host-seed.tar.gz"]:
        raise ValueError("product host seed differs from its build report")
    if kernel_report["mismatch_count"] != 0 or kernel_report["module_count"] < 1:
        raise ValueError("kernel ABI comparison did not pass")
    if not args.serial.isalnum() or product_report["release_id"] != args.release_id:
        raise ValueError("invalid target serial or mismatched product release")
    if not spec["identity"]["bootloader"].startswith(args.fastboot_bootloader_value) or \
            len(spec["identity"]["bootloader"]) - len(args.fastboot_bootloader_value) > 1:
        raise ValueError("observed fastboot bootloader is not the spec version")
    if product_report["device_spec_sha256"] != sha256(args.spec):
        raise ValueError("product image was built from a different device spec")
    if product_report["image_sha256"] != sha256(args.product_image):
        raise ValueError("product image differs from its checked build report")
    if stock_manifest["archive_sha256"] != spec["stock"]["archive_sha256"]:
        raise ValueError("OEM archive differs from device spec")
    if stock_verification["super_sha256"] != spec["stock"]["super_sha256"]:
        raise ValueError("OEM super verification differs from device spec")
    if sha256(args.boot) == spec["stock"]["boot_sha256"]:
        raise ValueError("candidate boot is still the OEM kernel")
    if sha256(args.init_boot) == spec["stock"]["init_boot_sha256"]:
        raise ValueError("candidate init_boot is still unpatched")
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"refusing to overwrite release directory: {output}")
    output.mkdir(parents=True)

    def link(source, rel):
        target = output / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(source.resolve(strict=True), target)

    def copy(source, rel, mode=None):
        target = output / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if mode is not None:
            target.chmod(mode)

    copy(args.spec, "device-spec.json")
    copy(Path(__file__).with_name("flash_release.py"), "flash.py", 0o755)
    copy(args.fastboot, "bin/fastboot", 0o755)
    for source, name in ((args.product_report, "product.json"),
                         (args.init_boot_report, "init-boot.json"),
                         (args.rootfs_report, "rootfs.json"),
                         (args.host_report, "host-seed.json"),
                         (args.kernel_abi_report, "kernel-abi.json"),
                         (args.package_lock, "packages.lock.tsv")):
        copy(source, "reports/" + name)
    (output / "flash.sh").write_text('#!/bin/sh\nset -eu\ncd "$(dirname "$0")"\nexec python3 ./flash.py "$@"\n')
    (output / "flash.sh").chmod(0o755)
    (output / "README.md").write_text(
        f"# RungicOS {args.release_id}\n\n"
        f"设备：{spec['id']}；本包绑定测试机 {args.serial}。\n\n"
        "宿主：Linux x86_64、Python 3、可访问 USB 的权限；已附 fastboot。"
        "手机须已解锁且处于 bootloader fastboot。\n\n"
        "离线校验：`./flash.sh --verify-only`。刷入：`./flash.sh`，按提示输入 WIPE；"
        "无人值守测试用 `./flash.sh --yes-wipe`。刷入会清除全部用户数据。\n\n"
        "首次启动先初始化 Android，再自动重启一次准备 Magisk；随后自动展开 RungicOS。"
        "完成 Android 初始设置后打开 Rungic，创建 Linux 账户。"
        "无需联网下载运行环境，也无需手动安装 APK 或修复 Magisk。\n\n"
        "如失败，保留 flash.log 和屏幕提示，先诊断，不重复擦除数据。"
        "stock/ 内保留本包所用的原厂启动镜像；不要使用其他机型的恢复镜像。\n\n"
        "本目录是候选包。是否通过整包验收，以配套 acceptance.json 为准；"
        "刷写成功不等于首启或硬件验收通过。\n"
    )
    link(args.boot, "images/boot.img")
    link(args.init_boot, "images/init_boot.img")
    link(args.product_image, "images/product.erofs.img")
    for name in ("vendor_boot.img", "dtbo.img", "recovery.img", "pvmfw.img",
                 "boot.img", "init_boot.img"):
        source = args.stock / name
        if sha256(source) != stock_manifest["files"][name]["sha256"]:
            raise ValueError(f"OEM {name} hash mismatch")
        link(source, "stock/" + name)
    chunks = sorted((p.name for p in args.stock.glob("super.img_sparsechunk.*")),
                    key=lambda name: int(name.rsplit(".", 1)[1]))
    if not chunks or [int(name.rsplit(".", 1)[1]) for name in chunks] != list(range(len(chunks))):
        raise ValueError("OEM super sparse chunks are incomplete")
    for name in chunks:
        source = args.stock / name
        if sha256(source) != stock_manifest["files"][name]["sha256"]:
            raise ValueError(f"OEM {name} hash mismatch")
        link(source, "stock/" + name)
    for name in ("vbmeta.img", "vbmeta_system.img"):
        original = (args.stock / name).read_bytes()
        if sha256(args.stock / name) != spec["stock"][name.removesuffix(".img") + "_sha256"]:
            raise ValueError(f"OEM {name} differs from spec")
        if original[:4] != b"AVB0" or struct.unpack_from(">I", original, 120)[0] != 0:
            raise ValueError(f"unexpected OEM {name} AVB header")
        candidate = bytearray(original)
        struct.pack_into(">I", candidate, 120, 3)
        (output / "images" / name).write_bytes(candidate)

    partition_bytes = spec["stock"]["product_partition_bytes"]
    padded = output / "images/product-padded.raw.img"
    subprocess.run(["cp", "--reflink=auto", "--sparse=always", args.product_image, padded], check=True)
    with padded.open("r+b") as image:
        image.truncate(partition_bytes)
    sparse = output / "images/product-fastboot.img"
    subprocess.run([args.img2simg, padded, sparse], check=True)
    padded.unlink()
    if sparse.stat().st_size > partition_bytes:
        raise ValueError("sparse product is larger than the logical partition")
    files = {str(path.relative_to(output)): {"sha256": sha256(path), "bytes": path.stat().st_size}
             for path in sorted(output.rglob("*")) if path.is_file()}
    manifest = {"schema_version": 1, "release_id": args.release_id,
                "target_serial": args.serial, "device_spec_sha256": sha256(args.spec),
                "device_spec_id": spec["id"], "product_partition_bytes": partition_bytes,
                "fastboot_bootloader_value": args.fastboot_bootloader_value,
                "logical_partition_bytes": {
                    name.removesuffix(".img"): info["bytes"]
                    for name, info in stock_verification["logical_images"].items()},
                "super_chunk_count": len(chunks), "files": files,
                "installation": "full OEM Android restore, Rungic payload, userdata wipe"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({key: value for key, value in manifest.items() if key != "files"}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f"release assembly failed: {error}")
