#!/usr/bin/env python3
"""Use the installed LXC container on the explicitly selected Android device."""
import argparse
import shlex
import subprocess

import rungic_device


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", help="adb transport id; default: resolved by rungic_device")
    parser.add_argument("action", choices=("start", "stop", "status", "shell", "exec", "log"), nargs="?", default="status")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action != "exec" and args.args:
        parser.error("Only exec accepts a command and its arguments")
    if args.action == "exec" and not args.args:
        parser.error("exec requires a command")
    command = shlex.join(["/data/adb/rungic-lxc/rungic-lxc", args.action, *args.args])
    return subprocess.call([
        *(rungic_device.adb() if args.transport is None else [rungic_device.adb_path(), "-s", args.transport]), "shell",
        "-tt" if args.action == "shell" else "-T",
        "su -c " + shlex.quote(command),
    ])


if __name__ == "__main__":
    raise SystemExit(main())
