#!/usr/bin/env python3
"""The Rungic rename (docs/70) as the packages define it: no package, unit or installed file is named
"moto". Builds the host packages into a temporary root with rungic_package's own steps (build.sh,
maintainer scripts, control) and reads every package definition, its build script and the tracked
files it is built from; the phone's acceptance scenario rebrand.residue looks at what is installed.

Allowed: the old names a renamed package conflicts with and replaces, the migration of their unit
states in postinst, and the compatibility paths of phase C that the Android side still mounts
(rungic_acceptance.RESIDUE_ALLOWED). "Motor..." (Motorola, motorway) is a word, not our name.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import rungic_acceptance  # noqa: E402
import rungic_package  # noqa: E402

ROOT = rungic_package.WORKSPACE
MOTO = re.compile(r'moto(?!r)', re.I)


def residue(name):
    """A path or name that still carries the old name, unless phase C keeps it."""
    return bool(MOTO.search(name)) and not rungic_acceptance.RESIDUE_ALLOWED.match(name)


class PackageNames(unittest.TestCase):
    def setUp(self):
        self.packages = rungic_package.definitions()
        self.assertGreater(len(self.packages), 10)

    # covers: install.rebrand-migration/E4
    def test_package_and_unit_names(self):
        for name, pkg in self.packages.items():
            with self.subTest(package=name):
                self.assertFalse(residue(name))
                for scope, units in pkg.get('units', {}).items():
                    self.assertEqual([u for u in units if residue(u)], [], scope)
                if pkg.get('formerly'):
                    self.assertTrue(MOTO.search(pkg['formerly']), 'formerly names the old package')

    # covers: install.rebrand-migration/E4
    def test_control_names_the_old_package_only_to_replace_it(self):
        for name, pkg in self.packages.items():
            with self.subTest(package=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / 'DEBIAN').mkdir()
                rungic_package.control(pkg, '0.1', root)
                fields = dict(line.split(': ', 1) for line in (root / 'DEBIAN/control').read_text().splitlines()
                              if ': ' in line and not line.startswith(' '))
                for field in ('Package', 'Depends', 'Recommends', 'Provides', 'Breaks'):
                    # Names only: a version like plasma-keyboard's 6.6.6-0ubuntu0.1+moto1 is an upstream
                    # rebuild's suffix, renamed when that component is next rebuilt (docs/70).
                    names = re.sub(r'\([^)]*\)', '', fields.get(field, ''))
                    self.assertFalse(residue(names), field)
                if pkg.get('formerly'):
                    for field in ('Conflicts', 'Replaces'):
                        self.assertIn(pkg['formerly'], fields[field].split(', '))

    # covers: install.rebrand-migration/E4
    def test_build_scripts_and_sources_install_no_old_names(self):
        for name, pkg in self.packages.items():
            with self.subTest(package=name):
                lines = [line for line in (pkg['dir'] / 'build.sh').read_text().splitlines()
                         if not line.lstrip().startswith('#')]
                self.assertEqual([line for line in lines if residue(line)], [])
                tracked = subprocess.run(['git', 'ls-files', '-z', '--', *pkg['paths']], cwd=ROOT,
                                         capture_output=True, check=True).stdout.decode().split('\0')
                self.assertEqual([path for path in tracked if residue(path)], [])

    # covers: install.rebrand-migration/E4
    def test_host_packages_as_built(self):
        host = [pkg for pkg in self.packages.values() if pkg['build'] == 'host' and not pkg.get('upstream')]
        self.assertTrue(host)
        for pkg in host:
            with self.subTest(package=pkg['name']), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / 'root'
                (root / 'DEBIAN').mkdir(parents=True)
                env = dict(os.environ, DESTDIR=str(root), SRC=str(ROOT), LC_ALL='C.UTF-8')
                subprocess.run(['sh', '-eu', str(pkg['dir'] / 'build.sh')], cwd=ROOT, env=env, check=True)
                rungic_package.maintainer_scripts(pkg, root)
                installed = ['/' + str(p.relative_to(root)) for p in root.rglob('*')
                             if not str(p.relative_to(root)).startswith('DEBIAN')]
                self.assertGreater(len(installed), 0)
                self.assertEqual([p for p in installed if residue(p)], [])
                conffiles = root / 'DEBIAN/conffiles'
                if conffiles.exists():
                    self.assertEqual([p for p in conffiles.read_text().split() if residue(p)], [])


if __name__ == '__main__':
    unittest.main()
