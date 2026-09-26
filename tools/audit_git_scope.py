#!/usr/bin/env python3
"""Read-only candidate inventory using Git's actual ignore rules.

Uses a disposable Git directory, never the workspace index or a remote.
This is a limited secret-pattern check, not a guarantee that files are sanitized.
"""
import argparse
import collections
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
SENSITIVE_NAMES = {"shadow", "gshadow", "id_rsa", "id_ed25519", ".env",
                   "cookies.sqlite", "logins.json", "key4.db"}
SENSITIVE_SUFFIXES = {".p12", ".pfx", ".jks", ".keystore", ".key", ".pem", ".pyc"}
# Explicitly requested by the user on 2026-09-23 for this private dev repository.
DEVELOPMENT_KEYS = {"signing/development/launcher-signing.p12"}
SECRET_PATTERNS = {
    "private-key": re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----"),
    "github-token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "aws-access-key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write detailed JSON locally")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="rungic-git-scope-") as temporary:
        gitdir = Path(temporary) / "metadata.git"
        env = os.environ.copy()
        for key in list(env):
            if key.startswith("GIT_"):
                env.pop(key)
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        subprocess.run(["git", "init", "--bare", "--quiet", str(gitdir)],
                       check=True, env=env)
        command = ["git", "--git-dir=" + str(gitdir), "--work-tree=" + str(ROOT),
                   "-c", "core.bare=false", "ls-files", "--others", "--exclude-standard", "-z"]
        raw = subprocess.check_output(command, cwd=ROOT, env=env)
        ignored_raw = subprocess.check_output(command[:-1] + ["--ignored", "-z"], cwd=ROOT, env=env)
    tracked = set()
    if (ROOT / ".git").exists():
        tracked = set(subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")) - {""}
    paths = sorted({os.fsdecode(p) for p in raw.split(b"\0") if p} | tracked)
    exceptions_file = ROOT / "vendor/audit-exceptions.json"
    exceptions = json.loads(exceptions_file.read_text()) if exceptions_file.exists() else {}
    groups = collections.defaultdict(lambda: {"files": 0, "bytes": 0})
    files, findings = [], []
    for item in ignored_raw.split(b"\0"):
        if item and os.fsdecode(item) not in tracked and not os.fsdecode(item).startswith(".work/"):
            findings.append({"path": os.fsdecode(item), "kind": "local-only-file-outside-work"})
    for name in paths:
        path = ROOT / name
        if not path.exists() and not path.is_symlink():
            findings.append({"path": name, "kind": "tracked-file-missing"})
            continue
        size = path.lstat().st_size
        group = name.split("/", 1)[0] if "/" in name else "root-docs-and-config"
        groups[group]["files"] += 1
        groups[group]["bytes"] += size
        files.append({"path": name, "bytes": size})
        if name not in DEVELOPMENT_KEYS and (path.name in SENSITIVE_NAMES or path.suffix in SENSITIVE_SUFFIXES):
            findings.append({"path": name, "kind": "sensitive-or-generated-filename"})
        if size > 10 * 1024 * 1024:
            findings.append({"path": name, "kind": "larger-than-10-MiB"})
        if path.is_symlink():
            if not path.resolve().is_relative_to(ROOT):
                findings.append({"path": name, "kind": "symlink-outside-workspace"})
            continue
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(data):
                findings.append({"path": name, "kind": label})
    # Only exact upstream bytes with an individually reviewed reason qualify.
    # A later edit to these files must be reviewed again; vendor/ isn't exempt.
    verified = {}
    for name, exception in exceptions.items():
        path = ROOT / name
        if path.is_file() and not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest() == exception["sha256"]:
            verified[name] = exception["kinds"]
    findings = [f for f in findings if f["kind"] not in verified.get(f["path"], [])]
    result = {"scope": "tracked-files-and-untracked-candidates; does not push",
              "verified_upstream_exceptions": sorted(verified),
              "authorized_development_keys": sorted(DEVELOPMENT_KEYS.intersection(paths)),
              "files": len(files), "bytes": sum(f["bytes"] for f in files),
              "groups": dict(groups), "findings": findings, "paths": files}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "paths"},
                     ensure_ascii=False, indent=2))
    return bool(findings)


if __name__ == "__main__":
    raise SystemExit(main())
