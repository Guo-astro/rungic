#!/usr/bin/env python3
"""Run ARM64 rootfs commands in a private user/mount namespace with QEMU binfmt."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def run(*argv):
    subprocess.run(argv, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    rootfs = args.rootfs.resolve(strict=True)
    qemu = args.qemu.resolve(strict=True)
    if not args.inside:
        # Podman's rootless user namespace maps the build user's UID to root
        # and subuids to guest users; package postinst scripts can chown files.
        os.execvp("podman", ["podman", "unshare", "unshare", "-mpf",
                            sys.executable, __file__, "--inside", "--rootfs", str(rootfs),
                            "--qemu", str(qemu), *args.command])
    # argparse REMAINDER treats a standalone -- as an argument.
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or not command[0].startswith("/"):
        raise ValueError("command must begin with an absolute path inside the ARM64 rootfs")
    run("mount", "--make-rprivate", "/")
    mountdir = tempfile.mkdtemp(prefix="rungic-binfmt-")
    mounted = []
    try:
        run("mount", "-t", "binfmt_misc", "binfmt_misc", mountdir)
        mounted.append(mountdir)
        # ARM64 ELF e_machine is 0x00b7. The F flag keeps QEMU open across chroot.
        rule = b":rungic-aarch64:M:18:\xb7\x00::" + os.fsencode(qemu) + b":F\n"
        (Path(mountdir) / "register").write_bytes(rule)
        run("mount", "-t", "proc", "proc", str(rootfs / "proc"))
        mounted.append(str(rootfs / "proc"))
        environment = dict(os.environ)
        environment.update(PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                           HOME="/root", DEBIAN_FRONTEND="noninteractive")
        return subprocess.run(["chroot", str(rootfs), *command],
                              env=environment, check=False).returncode
    finally:
        for path in reversed(mounted):
            subprocess.run(["umount", "-l", path], check=False)
        Path(mountdir).rmdir()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ARM64 chroot failed: {error}", file=sys.stderr)
        sys.exit(1)
