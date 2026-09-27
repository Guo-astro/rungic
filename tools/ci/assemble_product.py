#!/usr/bin/env python3
"""Add a verified Rungic first-boot seed to a spec-cleaned product EROFS."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from erofs_inventory import Erofs

PROJECT = Path(__file__).resolve().parents[2]
LABEL = base64.b64encode(b"u:object_r:system_file:s0").decode()
TIMESTAMP = 1230768000


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(*args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("spec", "clean-image", "clean-root", "magisk-apk", "rootfs-gz",
                 "rootfs-raw", "host-seed", "termux-apk", "termux-prefix",
                 "rungic-apk", "sparse-write", "tools", "work"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--partition-bytes", type=int, required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    if args.partition_bytes != spec["stock"]["product_partition_bytes"]:
        raise ValueError("product partition size differs from the device spec")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.release_id):
        raise ValueError("invalid release ID")
    phone_proxy = spec.get("deployment", {}).get("phone_http_proxy", "")
    if phone_proxy and not re.fullmatch(r"https?://[A-Za-z0-9.:-]+", phone_proxy):
        raise ValueError("invalid phone HTTP proxy in device spec")
    if not args.clean_image.is_file() or not args.clean_root.is_dir():
        raise ValueError("clean product image/tree are absent")
    base = list(Erofs(args.clean_image).walk())
    existing = {entry["path"] for entry in base}
    if {str(path.relative_to(args.clean_root)) for path in args.clean_root.rglob("*")} | {""} != existing:
        raise ValueError("clean product tree differs from EROFS inventory")
    work = args.work.resolve()
    if work.exists():
        raise ValueError(f"refusing to overwrite product staging: {work}")
    work.mkdir(parents=True)
    root = work / "root"
    shutil.copytree(args.clean_root, root, symlinks=True, copy_function=shutil.copy2)
    added = {}

    def put(rel, source, mode=0o644):
        if rel in existing or rel in added or not re.fullmatch(r"[A-Za-z0-9_.+/-]+", rel):
            raise ValueError(f"invalid or duplicate payload path: {rel}")
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(mode)
        added[rel] = sha256(target)

    put("etc/magisk/Magisk.apk", args.magisk_apk)
    with zipfile.ZipFile(args.magisk_apk) as apk:
        for name in apk.namelist():
            if name.startswith("lib/arm64-v8a/lib") and name.endswith(".so"):
                rel = "etc/magisk-prebuilt/" + Path(name).name[3:-3]
            elif name.startswith("assets/") and not name.endswith("/") and not name.startswith("assets/dexopt/"):
                rel = "etc/magisk-prebuilt/" + name[len("assets/"):]
            else:
                continue
            if ".." in Path(rel).parts:
                raise ValueError("unsafe Magisk APK asset path")
            target = work / "magisk-assets" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(apk.read(name))
            put(rel, target, 0o755)
    if (root / "etc/magisk-prebuilt/busybox").stat().st_size < 1_000_000:
        raise ValueError("Magisk runtime asset extraction failed")
    # Bundled system apps do not get the /data/app native-library extraction
    # performed by pm install. Preserve their compressed ARM64 JNI payloads in
    # the bundled app's nativeLibraryDir (docs/12).
    for app_name, apk_path in (("Termux", args.termux_apk), ("Rungic", args.rungic_apk)):
        put(f"app/{app_name}/{app_name}.apk", apk_path)
        with zipfile.ZipFile(apk_path) as apk:
            for entry in apk.infolist():
                if not entry.filename.startswith("lib/arm64-v8a/") or entry.is_dir():
                    continue
                basename = entry.filename[len("lib/arm64-v8a/"):]
                if not re.fullmatch(r"[A-Za-z0-9_.+-]+\.so", basename):
                    raise ValueError(f"unsafe bundled app library path: {entry.filename}")
                library = work / "app-libraries" / app_name / basename
                library.parent.mkdir(parents=True, exist_ok=True)
                library.write_bytes(apk.read(entry))
                put(f"app/{app_name}/lib/arm64/{basename}", library, 0o755)
    payloads = (
        ("etc/default-permissions/rungic.xml", PROJECT / "tools/ci/rungic-default-permissions.xml", 0o644),
        ("etc/rungic/rootfs.img.gz", args.rootfs_gz, 0o644),
        ("etc/rungic/host-seed.tar.gz", args.host_seed, 0o644),
        ("etc/rungic/termux.apk", args.termux_apk, 0o644),
        ("etc/rungic/termux-prefix.tar.gz", args.termux_prefix, 0o644),
        ("etc/rungic/rungic.apk", args.rungic_apk, 0o644),
        ("etc/rungic/rungic-sparse-write", args.sparse_write, 0o755),
        ("etc/rungic/firstboot.sh", PROJECT / "tools/ci/rungic-firstboot.sh", 0o644),
        ("etc/rungic/firstboot-service.sh", PROJECT / "tools/ci/rungic-firstboot-service.sh", 0o644),
    )
    for name, source, mode in payloads:
        put(name, source, mode)
    seed = {
        "RELEASE_ID": args.release_id,
        "HOST_SEED_SHA256": sha256(args.host_seed),
        "ROOTFS_GZ_SHA256": sha256(args.rootfs_gz),
        "ROOTFS_SHA256": sha256(args.rootfs_raw),
        "ROOTFS_BYTES": str(args.rootfs_raw.stat().st_size),
        "TERMUX_APK_SHA256": sha256(args.termux_apk),
        "TERMUX_PREFIX_SHA256": sha256(args.termux_prefix),
        "RUNGIC_APK_SHA256": sha256(args.rungic_apk),
        "SPARSE_WRITE_SHA256": sha256(args.sparse_write),
        "PHONE_HTTP_PROXY": phone_proxy,
    }
    env = work / "seed.env"
    env.write_text("".join(f"{key}='{value}'\n" for key, value in seed.items()))
    put("etc/rungic/seed.env", env)
    actual = {str(path.relative_to(root)) for path in root.rglob("*")} | {""}
    new_paths = actual - existing
    if not set(added).issubset(new_paths):
        raise ValueError("payload copy did not produce all files")
    expected = {entry["path"]: entry for entry in base}
    for rel in sorted(new_paths, key=lambda name: (name.count("/"), name)):
        path = root / rel
        mode = (stat.S_IFDIR | 0o755) if path.is_dir() else (stat.S_IFREG | (path.stat().st_mode & 0o7777))
        expected[rel] = {"path": rel, "uid": 0, "gid": 0, "mode": mode,
                         "mtime": TIMESTAMP, "mtime_ns": 0,
                         "xattrs": {"security.selinux": LABEL}}
    config, contexts = [], []
    for rel, entry in expected.items():
        path = "product" + ("/" + rel if rel else "")
        attrs = f"{entry['uid']} {entry['gid']} {entry['mode'] & 0o7777:04o} capabilities=0"
        config += [f"{path} {attrs}", f"{rel or '/'} {attrs}"]
        label = base64.b64decode(entry["xattrs"]["security.selinux"]).decode().rstrip("\0")
        contexts.append(f"/{re.escape(path)} {label}")
    (work / "fs-config.txt").write_text("\n".join(config) + "\n")
    (work / "file-contexts.txt").write_text("\n".join(contexts) + "\n")
    for rel, entry in sorted(expected.items(), key=lambda item: item[0].count("/"), reverse=True):
        moment = entry["mtime"] * 1_000_000_000 + entry["mtime_ns"]
        os.utime(root / rel, ns=(moment, moment), follow_symlinks=False)
    image = work / "product-rungic.img"
    command = [str(args.tools / "mkfs.erofs"), "--quiet", "-z", "lz4hc,9", "-C", "4096",
               "--preserve-mtime", "--mount-point=/product",
               f"--fs-config-file={work / 'fs-config.txt'}",
               f"--file-contexts={work / 'file-contexts.txt'}", str(image), str(root)]
    run(*command)
    if image.stat().st_size > args.partition_bytes:
        raise ValueError(f"product exceeds OEM partition: {image.stat().st_size} > {args.partition_bytes}")
    run(str(args.tools / "fsck.erofs"), str(image))
    rebuilt = {entry["path"]: entry for entry in Erofs(image).walk()}
    if set(rebuilt) != set(expected):
        raise ValueError("rebuilt EROFS inode paths differ")
    for rel, entry in expected.items():
        for key in ("uid", "gid", "mode", "mtime", "mtime_ns", "xattrs"):
            if rebuilt[rel][key] != entry[key]:
                raise ValueError(f"rebuilt EROFS metadata differs: {rel}: {key}")
    report = {"schema_version": 1, "device_spec_id": spec["id"],
              "device_spec_sha256": sha256(args.spec), "release_id": args.release_id,
              "clean_product_sha256": sha256(args.clean_image),
              "image_sha256": sha256(image), "image_bytes": image.stat().st_size,
              "partition_bytes": args.partition_bytes, "file_count": len(expected),
              "payload_sha256": added, "rootfs_sha256": seed["ROOTFS_SHA256"]}
    (work / "product-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "payload_sha256"}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        sys.exit(f"product assembly failed: {error}")
