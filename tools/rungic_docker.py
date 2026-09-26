#!/usr/bin/env python3
"""Manage this phone's Docker service or pass arguments to the Docker CLI."""
import argparse
import shlex
import subprocess

import rungic_device


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", help="adb transport id; default: resolved by rungic_device")
    parser.add_argument("--tty", action="store_true")
    parser.add_argument("action", choices=("start", "stop", "restart", "status", "log", "enable", "disable", "shell", "cli", "exec"), nargs="?", default="status")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action not in ("cli", "exec") and args.args:
        parser.error("Only cli and exec accept additional arguments")
    command = shlex.join(["/data/adb/moto-docker/moto-docker", args.action, *args.args])
    interactive = args.tty or args.action == "shell"
    return subprocess.call([*(rungic_device.adb() if args.transport is None else [rungic_device.adb_path(), "-s", args.transport]), "shell",
                            "-tt" if interactive else "-T",
                            ("su -i -c " if interactive else "su -c ") + shlex.quote(command)])


if __name__ == "__main__":
    raise SystemExit(main())
