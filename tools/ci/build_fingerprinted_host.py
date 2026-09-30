#!/usr/bin/env python3
"""Compose the Android host seed with a fingerprinted package repository."""
import argparse
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('runtime', 'rootfs-tree', 'repo_archive', 'lxc-enter', 'plasma-enter', 'cast-jar', 'output'):
        parser.add_argument('--' + name.replace('_', '-'), type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True)
    repo = args.output / 'repo'
    repo.mkdir()
    subprocess.run(['tar', '-xzf', str(args.repo_archive), '-C', str(repo)], check=True)
    command = [sys.executable, str(HERE / 'build_host_seed.py'), '--inside']
    for name in ('runtime', 'rootfs_tree', 'lxc_enter', 'plasma_enter', 'cast_jar'):
        command += ['--' + name.replace('_', '-'), str(getattr(args, name))]
    command += ['--repo', str(repo), '--output', str(args.output / 'seed/host-seed.tar.gz')]
    subprocess.run(command, check=True)


if __name__ == '__main__':
    main()
