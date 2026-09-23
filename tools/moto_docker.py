#!/usr/bin/env python3
"""Manage this phone's Docker service or pass arguments to the Docker CLI."""
import argparse
import shlex
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="ZY32MVJS25")
    parser.add_argument("--adb", default=str(Path.home() / "Android/Sdk/platform-tools/adb"))
    parser.add_argument("--tty", action="store_true")
    parser.add_argument("action", choices=("start", "stop", "restart", "status", "log", "enable", "disable", "shell", "cli", "exec"), nargs="?", default="status")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action not in ("cli", "exec") and args.args:
        parser.error("Only cli and exec accept additional arguments")
    command = shlex.join(["/data/adb/moto-docker/moto-docker", args.action, *args.args])
    interactive = args.tty or args.action == "shell"
    return subprocess.call([args.adb, "-s", args.serial, "shell",
                            "-tt" if interactive else "-T",
                            ("su -i -c " if interactive else "su -c ") + shlex.quote(command)])


if __name__ == "__main__":
    raise SystemExit(main())
