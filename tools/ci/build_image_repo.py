#!/usr/bin/env python3
"""Index a locked package snapshot outside the rootfs user namespace."""
import argparse
import gzip
import hashlib
import json
import lzma
from pathlib import Path
import subprocess
import tarfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'updates', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--builder-image', required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True)
    repo = args.output / 'repo'
    subprocess.run(['cp', '-a', '--reflink=auto', str(args.baseline), str(repo)], check=True)
    for deb in args.updates.glob('*.deb'):
        subprocess.run(['cp', '--reflink=auto', str(deb), str(repo / deb.name)], check=True)
    command = ['podman', 'run', '--rm', '--security-opt', 'label=disable', '-v',
               f'{repo}:/repo:ro', '-w', '/repo', args.builder_image, 'apt-ftparchive']
    packages = subprocess.check_output([*command, 'packages', '.'])
    (repo / 'Packages').write_bytes(packages)
    (repo / 'Packages.gz').write_bytes(gzip.compress(packages, mtime=0))
    (repo / 'Packages.xz').write_bytes(lzma.compress(packages))
    release = subprocess.check_output([*command, '-o', 'APT::FTPArchive::Release::Origin=rungic',
                                      '-o', 'APT::FTPArchive::Release::Label=rungic',
                                      '-o', 'APT::FTPArchive::Release::Suite=rungic',
                                      '-o', 'APT::FTPArchive::Release::Codename=rungic', 'release', '.'])
    (repo / 'Release').write_bytes(release)
    lock = {file.name: {'sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'bytes': file.stat().st_size}
            for file in sorted(repo.glob('*.deb'))}
    (args.output / 'packages.artifacts.json').write_text(json.dumps(lock, indent=2) + '\n')
    subprocess.run(['tar', '-C', str(repo), '-czf', str(args.output / 'repo.tar.gz'), '.'], check=True)


if __name__ == '__main__':
    main()
