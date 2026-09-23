#!/usr/bin/env python3
"""Use the installed LXC container on the explicitly selected Android device."""
import argparse
import shlex
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="ZY32MVJS25")
    parser.add_argument("--adb", default=str(Path.home() / "Android/Sdk/platform-tools/adb"))
    parser.add_argument("action", choices=("start", "stop", "restart-session", "status", "shell", "exec", "user-exec", "open", "log", "home", "hide-keyboard"), nargs="?", default="status")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action not in ("exec", "user-exec") and args.args:
        parser.error("Only exec accepts a command and its arguments")
    if args.action in ("exec", "user-exec") and not args.args:
        parser.error("exec requires a command")
    command = shlex.join(["/data/adb/moto-plasma/moto-plasma", args.action, *args.args])
    return subprocess.call([
        args.adb, "-s", args.serial, "shell",
        "-tt" if args.action == "shell" else "-T",
        "su -c " + shlex.quote(command),
    ])


if __name__ == "__main__":
    raise SystemExit(main())
