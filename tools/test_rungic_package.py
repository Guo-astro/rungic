#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""rungic_package without the phone or the Mac mini (docs/61): a release build takes only committed
content and versions it 0.<commit count> (+bN), an unchanged package is not rebuilt, and a device
package gets its library dependencies from dpkg-shlibdeps and its debug symbols, by build-id, in a
NAME-dbgsym package. The device build's script runs here on a stand-in build host, as it would in
the Ubuntu container of the Mac mini; the renamed package's control names its former name."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import rungic_package
import rungic_release


def sh(*argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=True).stdout


class LocalHost:
    """The build host's interface (tools/build_on_device.py) on this computer: the build script
    the Mac mini's container would run, run here."""
    name, jobs = 'macmini', 2

    def run(self, script, timeout=120, check=True):
        result = subprocess.run(['sh', '-c', script], capture_output=True, text=True, timeout=timeout)
        if check and result.returncode:
            raise AssertionError(f'build host script failed: {result.stderr}')
        return result

    def put_tar(self, archive, directory):
        os.makedirs(directory, exist_ok=True)
        subprocess.run(['tar', '-xf', str(archive), '-C', directory], check=True)

    def put(self, src, dest, mode):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy(src, dest)
        os.chmod(dest, int(mode, 8))
        return dest

    def get(self, path, target):
        shutil.copy(path, target)


class PackageRepo(unittest.TestCase):
    """A repository of its own (git), with one host package and one device package."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = root = Path(temp.name)
        (root / '.work/cache').mkdir(parents=True)
        (root / '.gitignore').write_text('.work/\n')
        self.write('demo/data.txt', 'one\n')
        self.write('packaging/rungic-demo/package.json', json.dumps({
            'name': 'rungic-demo', 'architecture': 'all', 'build': 'host', 'paths': ['demo'],
            'description': 'demo package\nA package of the test.'}))
        self.write('packaging/rungic-demo/build.sh',
                   'install -Dm644 "$SRC/demo/data.txt" "$DESTDIR/usr/share/rungic-demo/data.txt"\n')
        self.write('hello/hello.c', '#include <stdio.h>\nint main(void) { puts("hello"); return 0; }\n')
        self.write('packaging/rungic-hello/package.json', json.dumps({
            'name': 'rungic-hello', 'architecture': 'arm64', 'build': 'device', 'paths': ['hello'],
            'formerly': 'moto-hello', 'description': 'hello program'}))
        self.write('packaging/rungic-hello/build.sh',
                   'mkdir -p "$DESTDIR/usr/bin"\n'
                   'cc -g -O1 -Wl,--build-id -o "$DESTDIR/usr/bin/rungic-hello" "$SRC/hello/hello.c"\n')
        sh('git', 'init', '-q', cwd=root)
        sh('git', 'config', 'user.email', 'test@localhost', cwd=root)
        sh('git', 'config', 'user.name', 'test', cwd=root)
        self.commit('first')
        apt = root / '.work/apt'
        stubs = [(rungic_package, 'WORKSPACE', root), (rungic_package, 'PACKAGING', root / 'packaging'),
                 (rungic_package, 'BUILDS', apt / 'project-builds.json'),
                 (rungic_package, 'DEVICE_BASE', str(root / 'buildhost')),
                 (rungic_release, 'APT', apt), (rungic_release, 'POOL', apt / 'repo')]
        for obj, name, value in stubs:
            p = patch.object(obj, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(rungic_package.build_on_device, 'host', LocalHost())
        p.start()
        self.addCleanup(p.stop)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self, message):
        sh('git', 'add', '-A', cwd=self.root)
        sh('git', 'commit', '-q', '-m', message, cwd=self.root)

    def count(self):
        return sh('git', 'rev-list', '--count', 'HEAD', cwd=self.root).strip()

    def state(self, name):
        return next(r['state'] for r in rungic_package.listing() if r['package'] == name)


class ReleaseBuildTests(PackageRepo):
    # covers: delivery.packaging/E1
    def test_committed_content_only_and_versions(self):
        self.assertEqual(self.state('rungic-demo'), 'never built')
        first = rungic_package.build(['rungic-demo'])
        self.assertEqual(first, [{'package': 'rungic-demo', 'version': f'0.{self.count()}', 'built': True,
                                  'file': f'rungic-demo_0.{self.count()}_all.deb'}])
        self.assertEqual(self.state('rungic-demo'), 'current')
        # Unchanged paths: not rebuilt, even after a commit elsewhere.
        self.write('elsewhere.txt', 'x\n')
        self.commit('elsewhere')
        self.assertEqual(rungic_package.build(['rungic-demo'])[0]['built'], False)
        self.assertEqual(self.state('rungic-demo'), 'current')
        # An uncommitted change in its paths: listed, and no release build from it.
        self.write('demo/data.txt', 'two\n')
        self.assertTrue(self.state('rungic-demo').startswith('uncommitted'))
        with self.assertRaises(SystemExit) as refused:
            rungic_package.build(['rungic-demo'])
        self.assertIn('uncommitted changes', str(refused.exception))
        self.assertFalse([p for p in (self.root / '.work/apt/repo').glob('*.deb') if p.name != first[0]['file']])
        # Committed: stale until rebuilt at the new commit count.
        self.commit('two')
        self.assertEqual(self.state('rungic-demo'), 'stale')
        second = rungic_package.build(['rungic-demo'])[0]
        self.assertEqual((second['version'], second['built']), (f'0.{self.count()}', True))
        deb = self.root / '.work/apt/repo' / second['file']
        sh('dpkg-deb', '-x', str(deb), str(self.root / 'second'))
        self.assertEqual((self.root / 'second/usr/share/rungic-demo/data.txt').read_text(), 'two\n')
        # The same commit rebuilt with other contents (the pool's copy differs): +b1, the first kept.
        deb.write_bytes(b'another build of this commit')
        third = rungic_package.build(['rungic-demo'], force=True)[0]
        self.assertEqual(third['version'], f'0.{self.count()}+b1')
        self.assertEqual(deb.read_bytes(), b'another build of this commit')
        self.assertEqual(rungic_release.deb_field(self.root / '.work/apt/repo' / third['file'], 'Version'),
                         f'0.{self.count()}+b1')


class DeviceBuildTests(PackageRepo):
    # covers: delivery.packaging/E5
    def test_library_dependencies_and_debug_symbols_by_build_id(self):
        result = rungic_package.build(['rungic-hello'])[0]
        pool = self.root / '.work/apt/repo'
        deb = pool / result['file']
        depends = rungic_release.deb_field(deb, 'Depends')
        self.assertRegex(depends, r'\blibc6 \(>= [^)]+\)')       # from dpkg-shlibdeps
        # The program in the package is stripped and has its build-id; the debug package holds the
        # debug information under .build-id/xx/rest.debug, at the same version, depending on it.
        unpacked = self.root / 'unpacked'
        sh('dpkg-deb', '-x', str(deb), str(unpacked))
        program = unpacked / 'usr/bin/rungic-hello'
        build_id = re.search(r'Build ID: ([0-9a-f]+)', sh('readelf', '-n', str(program)))[1]
        self.assertNotIn('.debug_info', sh('readelf', '-S', str(program)))
        dbg = pool / f"rungic-hello-dbgsym_{result['version']}_arm64.deb"
        self.assertTrue(dbg.exists(), sorted(p.name for p in pool.iterdir()))
        self.assertEqual(rungic_release.deb_field(dbg, 'Depends'), f"rungic-hello (= {result['version']})")
        sh('dpkg-deb', '-x', str(dbg), str(self.root / 'dbg'))
        debug = self.root / 'dbg/usr/lib/debug/.build-id' / build_id[:2] / f'{build_id[2:]}.debug'
        self.assertTrue(debug.exists(), list((self.root / 'dbg').rglob('*.debug')))
        self.assertIn('.debug_info', sh('readelf', '-S', str(debug)))

    # covers: delivery.packaging/E4
    def test_renamed_package_conflicts_with_and_replaces_its_former_name(self):
        result = rungic_package.build(['rungic-hello'])[0]
        deb = self.root / '.work/apt/repo' / result['file']
        self.assertEqual(rungic_release.deb_field(deb, 'Conflicts'), 'moto-hello')
        self.assertEqual(rungic_release.deb_field(deb, 'Replaces'), 'moto-hello')


if __name__ == '__main__':
    unittest.main()


class IncrementalBuildTree(unittest.TestCase):
    """A package's tree is kept between builds on the build host (rungic_package.sync_script): only
    what changed rebuilds; trees not built for 30 days go (build_on_device.expire_script)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)

    def unpack(self, files):
        incoming = self.base / 'incoming'
        shutil.rmtree(incoming, ignore_errors=True)
        for name, text in files.items():
            (incoming / name).parent.mkdir(parents=True, exist_ok=True)
            (incoming / name).write_text(text)

    def sync(self, files, clean=False):
        self.unpack(files)
        subprocess.run(['sh', '-c', rungic_package.sync_script(str(self.base), clean)], check=True)

    # covers: delivery.packaging
    def test_unchanged_sources_keep_their_time_and_the_build_tree_stays(self):
        src = self.base / 'src'
        self.sync({'app/main.cpp': 'one', 'app/util.cpp': 'two', 'app/old.qml': 'gone soon'})
        (src / 'app/build').mkdir()
        (src / 'app/build/main.o').write_text('object')              # what build.sh made
        old = 1_000_000_000
        for name in ('app/main.cpp', 'app/util.cpp'):
            os.utime(src / name, (old, old))
        self.sync({'app/main.cpp': 'one', 'app/util.cpp': 'two, changed', 'app/new.qml': 'new'})
        self.assertEqual((src / 'app/main.cpp').stat().st_mtime, old, 'same content: its time stays, no rebuild')
        self.assertEqual((src / 'app/util.cpp').read_text(), 'two, changed')
        self.assertGreater((src / 'app/util.cpp').stat().st_mtime, old, 'changed: newer than its objects')
        self.assertFalse((src / 'app/old.qml').exists(), 'a source no longer in the tree goes')
        self.assertTrue((src / 'app/new.qml').exists())
        self.assertEqual((src / 'app/build/main.o').read_text(), 'object', 'the build tree stays')
        self.assertFalse((self.base / 'incoming').exists())
        self.assertTrue((self.base / '.rungic-last-build').exists(), 'marked as built now')

    # covers: delivery.packaging
    def test_clean_starts_from_the_new_tree_alone(self):
        self.sync({'a.c': 'x'})
        (self.base / 'src/build').mkdir()
        self.sync({'a.c': 'x'}, clean=True)
        self.assertEqual(sorted(p.name for p in (self.base / 'src').iterdir()), ['a.c'])

    # covers: delivery.packaging
    def test_a_tree_from_before_the_manifest_is_replaced(self):
        (self.base / 'src').mkdir()
        (self.base / 'src/stale.c').write_text('from an older tool')
        self.sync({'a.c': 'x'})
        self.assertEqual(sorted(p.name for p in (self.base / 'src').iterdir()), ['a.c'])

    # covers: delivery.packaging
    def test_trees_not_built_for_thirty_days_expire(self):
        import build_on_device
        old, recent, unmarked, absent = (self.base / n for n in ('old', 'recent', 'unmarked', 'absent'))
        for d in (old, recent, unmarked):
            d.mkdir()
        (old / build_on_device.MARKER).touch()
        (recent / build_on_device.MARKER).touch()
        long_ago = 1_000_000_000
        os.utime(old / build_on_device.MARKER, (long_ago, long_ago))
        os.utime(unmarked, (long_ago, long_ago))           # from before the markers: its own time
        (recent / 'big.o').write_text('x')
        out = subprocess.run(['sh', '-c', build_on_device.expire_script([str(old), str(recent), str(unmarked), str(absent)])],
                             capture_output=True, text=True, check=True).stdout
        self.assertFalse(old.exists())
        self.assertFalse(unmarked.exists())
        self.assertTrue((recent / 'big.o').exists(), 'built within 30 days: kept')
        self.assertIn(f'build cache expired: {old}', out)

    # covers: delivery.packaging
    def test_only_build_trees_may_expire(self):
        import build_on_device
        dirs = build_on_device.cache_dirs()
        self.assertIn(f'{build_on_device.BASE}/kwin', dirs)
        self.assertIn(f'{build_on_device.PACKAGE_BASE}/rungic-agent-screen', dirs)
        self.assertNotIn(f'{build_on_device.BASE}/cmake-shims', dirs)
        self.assertNotIn(f'{build_on_device.BASE}/dev-pool', dirs)
        self.assertEqual(build_on_device.CACHE_DAYS, 30)
