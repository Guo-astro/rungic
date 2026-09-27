#!/usr/bin/env python3
"""Package the reusable Android-side LXC controller and Rungic entry files."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
ANDROID_FILES = (
    ("plasma/rungic-plasma", "rungic-plasma/rungic-plasma", 0o755),
    ("plasma/android-audio", "rungic-plasma/android-audio", 0o755),
    ("plasma/android-audio.pa", "rungic-plasma/android-audio.pa", 0o644),
    ("plasma/rootfs-image", "rungic-plasma/rootfs-image", 0o755),
    ("plasma/rootfs.sepolicy.rule", "rungic-plasma/rootfs.sepolicy.rule", 0o644),
    ("plasma/rootfs-mount-hook", "rungic-plasma/rootfs-mount-hook", 0o755),
    ("plasma/plasma.config", "rungic-lxc/runtime/var/lib/lxc/plasma/config", 0o644),
    ("lxc/rungic-lxc", "rungic-lxc/rungic-lxc", 0o755),
)


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
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--rootfs-tree", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--lxc-enter", type=Path, required=True)
    parser.add_argument("--plasma-enter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name).resolve(strict=name != "output")
             for name in ("runtime", "rootfs_tree", "repo", "lxc_enter", "plasma_enter", "output")}
    if not args.inside:
        command = ["podman", "unshare", sys.executable, __file__, "--inside"]
        for name, path in paths.items():
            command += ["--" + name.replace("_", "-"), str(path)]
        os.execvp(command[0], command)
    if paths["output"].exists():
        raise ValueError("host seed output already exists")
    if not (paths["runtime"] / "usr/bin/lxc-start").is_file():
        raise ValueError("LXC manager runtime has no lxc-start")
    home = paths["rootfs_tree"] / "home/rungic"
    if home.stat().st_uid != 1000 or home.stat().st_gid != 1000:
        raise ValueError("desktop home seed must be owned by UID/GID 1000")
    stage = paths["output"].parent / "host-tree"
    if stage.exists():
        raise ValueError("host staging tree already exists")
    runtime = stage / "rungic-lxc/runtime"
    runtime.mkdir(parents=True)
    run("rsync", "-aHAX", "--numeric-ids", str(paths["runtime"]) + "/", str(runtime) + "/")
    plasma = runtime / "var/lib/lxc/plasma"
    (plasma / "rootfs").mkdir(parents=True, exist_ok=True)
    for name in ("home", "host", "rungic-cores", "rungic-apt"):
        (plasma / "state" / name).mkdir(parents=True, exist_ok=True)
    run("rsync", "-aHAX", "--numeric-ids", str(paths["rootfs_tree"] / "home") + "/",
        str(plasma / "state/home") + "/")
    run("rsync", "-aHAX", "--numeric-ids", str(paths["repo"]) + "/",
        str(plasma / "state/rungic-apt") + "/")
    for name in ("plasma-shared", "plasma-wayland", "plasma-audio"):
        (runtime / "mnt" / name).mkdir(parents=True, exist_ok=True)
    for source, dest, mode in ANDROID_FILES:
        target = stage / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / source).read_bytes())
        target.chmod(mode)
    for source, dest in (("lxc_enter", "rungic-lxc/rungic-lxc-enter"),
                         ("plasma_enter", "rungic-plasma/rungic-plasma-enter")):
        target = stage / dest
        target.write_bytes(paths[source].read_bytes())
        target.chmod(0o755)
    paths["output"].parent.mkdir(parents=True, exist_ok=True)
    run("tar", "-C", str(stage), "--numeric-owner", "-czf", str(paths["output"]),
        "rungic-lxc", "rungic-plasma")
    report = {"schema_version": 1, "arch": "aarch64", "controller": "Alpine LXC",
              "lxc_version": "6.0.4-r0", "runtime_origin": str(paths["runtime"]),
              "runtime_sha256": sha256(paths["runtime"] / "usr/bin/lxc-start"),
              "repo_release_sha256": sha256(paths["repo"] / "Release"),
              "lxc_enter_sha256": sha256(paths["lxc_enter"]),
              "plasma_enter_sha256": sha256(paths["plasma_enter"]),
              "archive_bytes": paths["output"].stat().st_size,
              "archive_sha256": sha256(paths["output"])}
    (paths["output"].parent / "host-seed-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f"host seed build failed: {error}")
