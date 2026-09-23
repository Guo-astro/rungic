#!/usr/bin/env python3
"""Use the installed LXC container on the explicitly selected Android device."""
import argparse
import shlex
import subprocess

import moto_device


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", help="adb transport id; default: resolved by moto_device")
    parser.add_argument("action", choices=("start", "stop", "restart-session", "status", "shell", "exec", "user-exec", "open", "log", "home", "hide-keyboard"), nargs="?", default="status")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action not in ("exec", "user-exec") and args.args:
        parser.error("Only exec accepts a command and its arguments")
    if args.action in ("exec", "user-exec") and not args.args:
        parser.error("exec requires a command")
    command = shlex.join(["/data/adb/moto-plasma/moto-plasma", args.action, *args.args])
    return subprocess.call([
        *(moto_device.adb() if args.transport is None else [moto_device.adb_path(), "-s", args.transport]), "shell",
        "-tt" if args.action == "shell" else "-T",
        "su -c " + shlex.quote(command),
    ])


if __name__ == "__main__":
    raise SystemExit(main())
