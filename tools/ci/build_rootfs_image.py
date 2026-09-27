#!/usr/bin/env python3
"""Turn an installed ARM64 Rungic root tree into a checked, sparse ext4 image."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


EXCLUDES = (
    "/dev/***", "/proc/***", "/sys/***", "/run/***", "/tmp/***",
    "/target/***", "/host-rootfs/***", "/root/.cache/***",
    "/var/tmp/***", "/var/log/***", "/var/cache/apt/archives/***",
    "/var/lib/apt/lists/***", "/var/lib/rungic-apt/***",
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def packages(status):
    installed = {}
    for stanza in status.read_text().split("\n\n"):
        fields = {}
        for line in stanza.splitlines():
            if line and not line[0].isspace() and ": " in line:
                key, value = line.split(": ", 1)
                fields[key] = value
        if fields.get("Status") == "install ok installed":
            installed[fields["Package"]] = (fields["Version"], fields.get("Architecture", ""))
    return installed


def run(*args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size-gib", type=int, default=16)
    parser.add_argument("--firefox-version", required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    release = args.release.resolve(strict=True)
    output = args.output.resolve()
    if not args.inside:
        os.execvp("podman", ["podman", "unshare", sys.executable, __file__, "--inside",
                            "--root", str(root), "--release", str(release),
                            "--output", str(output), "--size-gib", str(args.size_gib),
                            "--firefox-version", args.firefox_version])
    if output.exists() or args.size_gib < 8 or args.size_gib > 128:
        raise ValueError("output exists or image size is outside 8–128 GiB")
    installed = packages(root / "var/lib/dpkg/status")
    manifest = json.loads(release.read_text())
    expected = dict(manifest["packages"], firefox=args.firefox_version,
                    **{"rungic-release": manifest["version"]})
    mismatched = {name: {"want": version, "have": installed.get(name)}
                  for name, version in expected.items()
                  if installed.get(name, (None,))[0] != version}
    if mismatched:
        raise ValueError(f"release package mismatch: {mismatched}")
    protocol_path = root / "usr/share/rungic/account-protocol"
    if not protocol_path.is_file() or protocol_path.read_text().strip() != "2":
        raise ValueError("rootfs needs account protocol 2; rebuild rungic-plasma-session before composing the new launcher")
    account = next((line.split(":") for line in (root / "etc/passwd").read_text().splitlines()
                    if line.split(":")[2] == "1000"), None)
    if account is None or not account[5].startswith("/home/"):
        raise ValueError("rootfs has no regular UID 1000 desktop account")
    home = root / account[5].lstrip("/")
    if home.stat().st_uid != 1000 or home.stat().st_gid != 1000:
        raise ValueError(f"desktop home owner is not 1000:1000: {home}")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.parent / "root-tree"
    if stage.exists():
        raise ValueError(f"stage already exists: {stage}")
    stage.mkdir()
    run("rsync", "-aHAX", "--numeric-ids", *("--exclude=" + path for path in EXCLUDES),
        str(root) + "/", str(stage) + "/")
    for name, mode in (("dev", 0o755), ("proc", 0o555), ("sys", 0o555),
                       ("run", 0o755), ("tmp", 0o1777), ("var/tmp", 0o1777),
                       ("var/log", 0o755), ("var/log/plasma", 0o755),
                       ("var/cache/apt/archives", 0o755),
                       ("var/lib/apt/lists", 0o755), ("var/lib/rungic-apt", 0o755)):
        path = stage / name
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(mode)
    # systemd generates a device-unique ID at first boot; never clone the build host ID.
    for name in ("etc/machine-id", "var/lib/dbus/machine-id"):
        path = stage / name
        if path.is_file() and not path.is_symlink():
            path.write_bytes(b"")
    # Android owns the physical network. A first-boot adapter replaces this placeholder.
    (stage / "etc/resolv.conf").write_text("# Set from Android network on first boot\n")
    lock = "".join(f"{name}\t{version}\t{arch}\n"
                   for name, (version, arch) in sorted(installed.items()))
    (output.parent / "packages.lock.tsv").write_text(lock)
    with output.open("wb") as image:
        image.truncate(args.size_gib * 1024 ** 3)
    run("mkfs.ext4", "-F", "-q", "-L", "RungicOS", "-m", "0",
        "-E", "lazy_itable_init=0,lazy_journal_init=0", "-d", str(stage), str(output))
    check = subprocess.run(["e2fsck", "-fn", str(output)], capture_output=True, text=True)
    if check.returncode not in (0, 1):
        raise RuntimeError(f"e2fsck failed: {check.stdout[-2000:]} {check.stderr[-2000:]}")
    compressed = output.with_suffix(".img.gz")
    with compressed.open("wb") as destination:
        subprocess.run(["gzip", "-1", "-n", "-c", str(output)], stdout=destination, check=True)
    report = {"schema_version": 1, "account_status_protocol": 2, "release_version": manifest["version"],
              "release_sha256": sha256(release), "arch": "arm64",
              "package_count": len(installed), "package_lock_sha256": sha256(output.parent / "packages.lock.tsv"),
              "rootfs_bytes": output.stat().st_size, "rootfs_sha256": sha256(output),
              "compressed_bytes": compressed.stat().st_size, "compressed_sha256": sha256(compressed),
              "filesystem_check": check.returncode}
    (output.parent / "rootfs-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f"rootfs image build failed: {error}")
