#!/usr/bin/env python3
"""Copy an already patched vendor tree into .work for an isolated build.

Every invocation gets a fresh directory by default. Explicit destinations must
not exist. Edit vendor/, never the disposable build copy. No downloads, patch
application, builds or installs are performed here.
"""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    manifest = json.loads((ROOT / "vendor/manifest.json").read_text())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=sorted(manifest["components"]))
    parser.add_argument("--output", type=Path, help="New source directory inside .work")
    args = parser.parse_args()
    source = ROOT / manifest["components"][args.component]["path"]
    work = ROOT / ".work"
    if args.output:
        dest = args.output.resolve()
        if not dest.is_relative_to(work.resolve()) or dest == work.resolve():
            parser.error("--output must be a new directory inside this checkout's .work")
        if dest.exists() or dest.is_symlink():
            parser.error("destination exists; choose a new output directory")
    else:
        builds = work / "build/vendor"
        builds.mkdir(parents=True, exist_ok=True)
        dest = Path(tempfile.mkdtemp(prefix=args.component + "-", dir=builds)) / "source"
    # Resolve links to shared project code so the build copy is self-contained.
    # Also retains upstream license content when archives use license symlinks.
    shutil.copytree(source, dest, symlinks=False)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    (dest.parent / (dest.name + "-origin.json")).write_text(json.dumps({
        "component": args.component, "source": str(source.relative_to(ROOT)),
        "integration_commit": revision, "checkout_dirty": dirty,
        "note": "Copy includes current working tree edits; commit before sharing a reproducible build.",
    }, indent=2) + "\n")
    print(dest)


if __name__ == "__main__":
    main()
