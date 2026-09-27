#!/usr/bin/env python3
"""Add the shared Rungic Magisk bootstrap to an already patched init_boot image."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("patched-init-boot", "magiskboot", "qemu", "bootstrap-rc", "bootstrap-sh", "output"):
        parser.add_argument("--" + name, type=Path, required=name != "qemu")
    args = parser.parse_args()
    source = args.patched_init_boot.resolve(strict=True)
    magiskboot = args.magiskboot.resolve(strict=True)
    qemu = args.qemu.resolve(strict=True) if args.qemu else None
    rc = args.bootstrap_rc.resolve(strict=True)
    script = args.bootstrap_sh.resolve(strict=True)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError(f"refusing to overwrite {output}")
    command = ([str(qemu)] if qemu else []) + [str(magiskboot)]

    def run(work, *arguments, check=True):
        return subprocess.run(command + list(arguments), cwd=work, check=check,
                              capture_output=True, text=True)

    with tempfile.TemporaryDirectory(prefix="magisk-seed-", dir=output.parent) as name:
        work = Path(name)
        run(work, "unpack", str(source))
        ramdisk = work / "ramdisk.cpio"
        if not ramdisk.is_file():
            raise ValueError("patched init_boot has no ramdisk.cpio")
        for entry in ("overlay.d/rungic-magisk-bootstrap.rc",
                      "overlay.d/sbin/rungic-magisk-bootstrap.sh"):
            if run(work, "cpio", "ramdisk.cpio", "exists " + entry, check=False).returncode == 0:
                raise ValueError(f"bootstrap entry already present: {entry}")
        run(work, "cpio", "ramdisk.cpio",
            f"add 0644 overlay.d/rungic-magisk-bootstrap.rc {rc}",
            f"add 0750 overlay.d/sbin/rungic-magisk-bootstrap.sh {script}")
        for entry, expected, dest in (
                ("overlay.d/rungic-magisk-bootstrap.rc", rc, "rc.verify"),
                ("overlay.d/sbin/rungic-magisk-bootstrap.sh", script, "script.verify")):
            run(work, "cpio", "ramdisk.cpio", f"extract {entry} {dest}")
            if sha256(work / dest) != sha256(expected):
                raise ValueError(f"ramdisk entry differs from source: {entry}")
        image = work / "init_boot.img"
        run(work, "repack", str(source), str(image))
        if image.stat().st_size != source.stat().st_size or sha256(image) == sha256(source):
            raise ValueError("repacked init_boot has unexpected size or matches its input")
        report = {"schema_version": 1, "patched_init_boot_sha256": sha256(source),
                  "bootstrap_rc_sha256": sha256(rc), "bootstrap_sh_sha256": sha256(script),
                  "init_boot_sha256": sha256(image), "init_boot_bytes": image.stat().st_size}
        os.replace(image, output)
    output.with_suffix(".report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f"Magisk seed injection failed: {error}")
