#!/usr/bin/env python3
"""rungic_release's Android-side file handling without a device: sync_android() records what it
changes and restore_android() puts it back (the snapshot rollback path, docs/70)."""
import hashlib
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

import rungic_release


class FakeDevice:
    """Files on the phone as a dict; understands the few commands rungic_release sends."""

    def __init__(self, files):
        self.files = dict(files)

    def run(self, command, level='root', timeout=None, check=True):
        result = type('Result', (), {'stdout': '', 'stderr': '', 'returncode': 0})()
        for part in command.split('&&'):
            argv = shlex.split(part.split('|')[0].split(';')[0])
            if argv[0] == 'sha256sum':
                data = self.files.get(argv[1])
                result.stdout = hashlib.sha256(data).hexdigest() + '\n' if data is not None else ''
            elif argv[0] == 'install':
                self.files[argv[3]] = self.files[argv[2]]
            elif argv[0] == 'mv':
                self.files[argv[2]] = self.files.pop(argv[1])
            elif argv[0] == 'rm':
                for path in argv[2:]:
                    self.files.pop(path, None)
        return result

    def push(self, local, name, timeout=None):
        remote = f'/data/local/tmp/{name}'
        self.files[remote] = Path(local).read_bytes()
        return remote

    def pull(self, path, local, timeout=None):
        Path(local).write_bytes(self.files[path])


class AndroidFilesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'plasma').mkdir()
        self.record = self.root / 'record'
        self.record.mkdir()

    def release(self, sources):
        files = {}
        for path, (source, data) in sources.items():
            (self.root / source).write_bytes(data)
            files[path] = {'source': source, 'sha256': hashlib.sha256(data).hexdigest(), 'mode': '644'}
        return {'version': 'test', 'android': files}

    def patched(self, device):
        return [patch.object(rungic_release, name, getattr(device, name)) for name in ('run', 'push', 'pull')] + \
               [patch.object(rungic_release, 'WORKSPACE', self.root)]

    def test_rollback_restores_replaced_and_removes_added_files(self):
        device = FakeDevice({'/data/adb/x/config': b'old config', '/data/adb/x/same': b'same'})
        info = self.release({'/data/adb/x/config': ('plasma/config', b'new config'),
                             '/data/adb/x/hook': ('plasma/hook', b'new hook'),
                             '/data/adb/x/same': ('plasma/same', b'same')})
        patches = self.patched(device)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        changed = rungic_release.sync_android(info, self.record)
        self.assertEqual(sorted(changed), ['/data/adb/x/config', '/data/adb/x/hook'])
        self.assertEqual(device.files['/data/adb/x/config'], b'new config')
        self.assertEqual(device.files['/data/adb/x/hook'], b'new hook')

        restored = rungic_release.restore_android(self.record)
        self.assertEqual(sorted(restored), ['/data/adb/x/config', '/data/adb/x/hook'])
        self.assertEqual(device.files['/data/adb/x/config'], b'old config')
        self.assertNotIn('/data/adb/x/hook', device.files)
        self.assertEqual(device.files['/data/adb/x/same'], b'same')
        self.assertFalse([p for p in device.files if p.startswith('/data/local/tmp/')])

    def test_nothing_to_restore_without_changes(self):
        device = FakeDevice({'/data/adb/x/same': b'same'})
        info = self.release({'/data/adb/x/same': ('plasma/same', b'same')})
        patches = self.patched(device)
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        self.assertEqual(rungic_release.sync_android(info, self.record), [])
        self.assertEqual(rungic_release.restore_android(self.record), [])


if __name__ == '__main__':
    unittest.main()
