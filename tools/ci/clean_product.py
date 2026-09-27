#!/usr/bin/env python3
"""Rebuild an OEM product EROFS from a device spec's explicit purity policy."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apk_manifest_info import manifest_info


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("stock_product", type=Path)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("root", type=Path)
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    require(sha256(args.stock_product) == spec["stock"]["product_sha256"],
            "product image does not match device spec")
    entries = json.loads(args.inventory.read_text())
    paths = {item["path"] for item in entries}
    root = args.root.resolve(strict=True)
    policy = spec["purity"]
    remove = policy["remove_preinstall"]
    excluded = [f"preinstall/{item['directory']}" for item in remove] + policy["remove_files"]
    require(len(excluded) == len(set(excluded)) and all(path in paths for path in excluded),
            "purity policy has duplicate or absent product paths")
    require(all(re.fullmatch(r"[A-Za-z0-9_.]+", item["package"]) for item in remove),
            "invalid package name in purity policy")
    removed = []
    for item in remove:
        name = item["directory"]
        require(re.fullmatch(r"[A-Za-z0-9_]+", name), "invalid preinstall directory")
        apk = root / "preinstall" / name / (name + ".apk")
        require(apk.is_file() and sha256(apk) == item["apk_sha256"],
                f"APK hash mismatch: {name}")
        require(manifest_info(apk)["manifest"]["package"] == item["package"],
                f"APK package mismatch: {name}")
        members = [entry for entry in entries if entry["path"] == f"preinstall/{name}"
                   or entry["path"].startswith(f"preinstall/{name}/")]
        removed.append({"directory": name, "package": item["package"],
                        "bytes": sum(entry["size"] for entry in members
                                     if stat.S_ISREG(entry["mode"]))})

    disabled = policy["disable_packages"]
    require(len(disabled) == len(set(disabled)) and
            all(re.fullmatch(r"[A-Za-z0-9_.]+", package) for package in disabled),
            "invalid disabled package policy")
    new_path = "etc/sysconfig/rungic-disabled-ai.xml"
    require(new_path not in paths and not (root / new_path).exists(),
            "Rungic sysconfig XML already exists")
    sysconfig = next(item for item in entries if item["path"] == "etc/sysconfig")
    label = base64.b64decode(sysconfig["xattrs"]["security.selinux"]).decode().rstrip("\0")
    xml = ['<?xml version="1.0" encoding="utf-8"?>', '<config>']
    xml += [f'    <disabled-in-sku package="{package}" />' for package in disabled]
    xml += ['</config>', '']
    (root / new_path).write_text('\n'.join(xml))
    os.utime(root / new_path, (1230768000, 1230768000))
    actual = {str(path.relative_to(root)) for path in root.rglob("*")} | {""}
    require(actual == paths | {new_path}, "extraction differs from OEM product inventory")

    kept = [item for item in entries if not any(item["path"] == path or
            item["path"].startswith(path + "/") for path in excluded)]
    configs, contexts = [], []
    for item in kept:
        require(set(item["xattrs"]) == {"security.selinux"},
                f"unexpected xattrs at {item['path']}")
        label_item = base64.b64decode(item["xattrs"]["security.selinux"]).decode().rstrip("\0")
        path = "product" + ("/" + item["path"] if item["path"] else "")
        require(not any(char.isspace() for char in path), "path contains whitespace")
        attributes = f"{item['uid']} {item['gid']} {item['mode'] & 0o7777:04o} capabilities=0"
        configs.extend((f"{path} {attributes}", f"{item['path'] or '/'} {attributes}"))
        contexts.append(f"/{re.escape(path)} {label_item}")
    path = "product/" + new_path
    configs.extend((f"{path} 0 0 0644 capabilities=0",
                    f"{new_path} 0 0 0644 capabilities=0"))
    contexts.append(f"/{re.escape(path)} {label}")
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    (work / "product-fs-config.txt").write_text('\n'.join(configs) + '\n')
    (work / "product-file-contexts.txt").write_text('\n'.join(contexts) + '\n')
    for item in sorted(kept, key=lambda entry: entry["path"].count('/'), reverse=True):
        source = root / item["path"]
        timestamp = item["mtime"] * 1_000_000_000 + item["mtime_ns"]
        os.utime(source, ns=(timestamp, timestamp), follow_symlinks=False)
    output = work / "product-clean.img"
    require(not output.exists(), "refusing to overwrite product output")
    command = [str(args.tools / "mkfs.erofs"), "--quiet", "-z", "lz4hc,9", "-C", "4096",
               "--preserve-mtime", "--mount-point=/product",
               f"--fs-config-file={work / 'product-fs-config.txt'}",
               f"--file-contexts={work / 'product-file-contexts.txt'}"]
    command += [f"--exclude-path={path}" for path in excluded]
    command += [str(output), str(root)]
    subprocess.run(command, check=True)
    subprocess.run([str(args.tools / "fsck.erofs"), str(output)], check=True)
    report = {"schema_version": 1, "device_spec_id": spec["id"],
              "device_spec_sha256": sha256(args.spec),
              "stock_product_sha256": sha256(args.stock_product),
              "inventory_sha256": sha256(args.inventory),
              "image_sha256": sha256(output), "image_bytes": output.stat().st_size,
              "removed": removed, "excluded_paths": excluded,
              "disabled_packages": disabled, "sysconfig_xml": new_path}
    (work / "product-clean-report.json").write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items()
                      if key not in ("removed", "excluded_paths")}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, StopIteration, subprocess.CalledProcessError) as error:
        print(f"clean product build failed: {error}", file=sys.stderr)
        sys.exit(1)
