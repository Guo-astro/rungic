#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The repository's scope (docs/52): the candidate check before a commit (tools/audit_git_scope.py) on
a small repository of its own, local material ignored into .work/, the development signing identity
the APK build uses by default, and the records of every pinned upstream."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import audit_git_scope

ROOT = Path(__file__).resolve().parents[1]
KEY = 'signing/development/launcher-signing.p12'
# The APK's signing certificate (keytool -list): the identity the phone's installed Rungic was signed with.
CERTIFICATE_SHA256 = '61:FD:32:47:8F:49:20:16:BF:83:40:11:52:AE:DA:83:A1:C8:47:ED:AC:BF:FE:EA:97:80:2C:4D:7C:88:D4:C8'


def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, check=True, capture_output=True).stdout


class CandidateCheckTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'repo'
        self.root.mkdir()
        files = {'.gitignore': (ROOT / '.gitignore').read_bytes(),
                 'README.md': b'# repo\n', KEY: b'\x30\x82 pkcs12',
                 'third_party/upstream.pem': b'-----BEGIN PRIVATE KEY-----\nexample from upstream tests\n',
                 'third_party/changed.pem': b'-----BEGIN PRIVATE KEY-----\nchanged since review\n',
                 'notes/id_ed25519': b'not a key really\n',
                 'notes/token.txt': b'token ghp_' + b'a' * 36 + b'\n',
                 'notes/aws.txt': b'AKIA' + b'B' * 16 + b'\n',
                 '.work/build/x.o': b'object', '.work/secret.key': b'local',
                 'tools/__pycache__/x.cpython-314.pyc': b'cache', 'rootfs.img': b'image'}
        for name, data in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.root / 'notes/big.bin').write_bytes(b'\0' * (11 << 20))
        (self.root / 'notes/outside').symlink_to('/etc/hostname')
        exceptions = {'third_party/upstream.pem': {'sha256': hashlib.sha256(files['third_party/upstream.pem']).hexdigest(),
                                                   'kinds': ['private-key', 'sensitive-or-generated-filename']},
                      'third_party/changed.pem': {'sha256': '0' * 64, 'kinds': ['private-key', 'sensitive-or-generated-filename']}}
        (self.root / 'provenance').mkdir()
        (self.root / 'provenance/audit-exceptions.json').write_text(json.dumps(exceptions))
        git(self.root, 'init', '-q')
        git(self.root, 'add', 'README.md', '.gitignore')
        # Force-added files are candidates whatever their names: the development key, upstream test
        # fixtures, and one that should not be there.
        git(self.root, 'add', '-f', KEY, 'third_party', 'notes/id_ed25519')
        git(self.root, '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'base')

    def audit(self):
        out = self.root.parent / 'audit.json'
        with patch.object(audit_git_scope, 'ROOT', self.root), patch.object(sys, 'argv', ['audit', '--output', str(out)]), \
                patch('builtins.print'):
            failed = audit_git_scope.main()
        return failed, json.loads(out.read_text())

    # covers: delivery.repo-scope/E1
    def test_candidates_are_listed_and_the_risky_ones_named(self):
        index = (self.root / '.git/index').read_bytes()
        status = git(self.root, 'status', '--porcelain', '--ignored')
        failed, result = self.audit()
        self.assertTrue(failed)
        findings = {(f['path'], f['kind']) for f in result['findings']}
        for finding in (('notes/id_ed25519', 'sensitive-or-generated-filename'), ('notes/token.txt', 'github-token'),
                        ('notes/aws.txt', 'aws-access-key'), ('notes/big.bin', 'larger-than-10-MiB'),
                        ('notes/outside', 'symlink-outside-workspace'), ('third_party/changed.pem', 'private-key'),
                        ('third_party/changed.pem', 'sensitive-or-generated-filename')):
            self.assertIn(finding, findings)
        # The development key is the one allowed key; a reviewed upstream file only at its exact bytes.
        self.assertEqual(result['authorized_development_keys'], [KEY])
        self.assertFalse([f for f in findings if f[0] in (KEY, 'third_party/upstream.pem')])
        self.assertEqual(result['verified_upstream_exceptions'], ['third_party/upstream.pem'])
        # Candidates as Git's own ignore rules see them: untracked files that would be added, not ignored ones.
        paths = {p['path'] for p in result['paths']}
        self.assertIn('notes/token.txt', paths)
        self.assertFalse({'.work/build/x.o', 'rootfs.img', 'tools/__pycache__/x.cpython-314.pyc'} & paths)
        # Read only: the repository's index and status are as before.
        self.assertEqual((self.root / '.git/index').read_bytes(), index)
        self.assertEqual(git(self.root, 'status', '--porcelain', '--ignored'), status)

    # covers: delivery.repo-scope/E2
    def test_ignored_files_outside_work_are_named(self):
        _, result = self.audit()
        local = sorted(f['path'] for f in result['findings'] if f['kind'] == 'local-only-file-outside-work')
        self.assertEqual(local, ['rootfs.img', 'tools/__pycache__/x.cpython-314.pyc'])
        self.assertFalse([f for f in result['findings'] if f['path'].startswith('.work/')])

    # covers: delivery.repo-scope/E2
    def test_local_material_is_ignored_wherever_a_tool_writes_it(self):
        names = ['.work/anything', 'out/rootfs.img', 'x/system.img.0', 'a.apk', 'b.deb', 'c.tar.zst', 'rec.mp4', 'v.wav',
                 'k.p12', 'k.pem', 'id_ed25519', '.env', 'tools/__pycache__/m.pyc', 'build/x', 'target/debug/y']
        result = subprocess.run(['git', 'check-ignore', '--no-index', '--stdin'], cwd=ROOT, input='\n'.join(names),
                                capture_output=True, text=True)
        self.assertEqual(sorted(result.stdout.split()), sorted(names))
        # The exceptions are named: the XKB asset and the development key.
        for name in ('android/app/assets/xkb.zip', KEY):
            self.assertEqual(subprocess.run(['git', 'check-ignore', '--no-index', '-q', name], cwd=ROOT).returncode, 1, name)


class SigningTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('keytool'), 'needs keytool')
    # covers: delivery.repo-scope/E3
    def test_the_repository_key_is_the_apks_identity(self):
        listing = subprocess.run(['keytool', '-list', '-keystore', str(ROOT / KEY), '-storetype', 'PKCS12',
                                  '-storepass', 'android'], capture_output=True, text=True, check=True).stdout
        self.assertIn('launcher, ', listing)
        self.assertIn(f'Certificate fingerprint (SHA-256): {CERTIFICATE_SHA256}', listing)

    # covers: delivery.repo-scope/E3
    def test_the_apk_build_signs_with_it_on_any_machine(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            tools, log = temp / 'build-tools', temp / 'log'
            tools.mkdir()
            fake = {'aapt2': 'case "$1" in link) out=$3; python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1],\'w\').writestr(\'AndroidManifest.xml\',\'x\')" "$out";; esac',
                    'd8': 'while [ $# -gt 0 ]; do [ "$1" = --output ] && touch "$2/classes.dex"; shift; done',
                    'zipalign': 'cp "$3" "$4"',
                    'apksigner': '[ "$1" = sign ] && cp "${10}" "$9"; true',
                    'javac': 'true'}
            for name, body in fake.items():
                (tools / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "$LOG"\n{body}\n')
                (tools / name).chmod(0o755)
            (temp / 'android.jar').write_bytes(b'')
            (temp / 'native/lib/arm64-v8a').mkdir(parents=True)
            (temp / 'native/lib/arm64-v8a/libx.so').write_bytes(b'x')
            for home in ('/nonexistent/home-a', str(temp / 'home-b')):
                env = {'PATH': f'{tools}:{os.environ["PATH"]}', 'HOME': home, 'LOG': str(log),
                       'RUNGIC_ANDROID_BUILD_TOOLS': str(tools), 'RUNGIC_ANDROID_JAR': str(temp / 'android.jar'),
                       'RUNGIC_APK_OUT': str(temp / 'out'), 'RUNGIC_NATIVE_LIBS': str(temp / 'native'), 'RUNGIC_APK_OCR': 'none'}
                log.write_text('')
                build = subprocess.run(['bash', str(ROOT / 'android/build-apk.sh')], capture_output=True, text=True, env=env)
                self.assertEqual(build.returncode, 0, build.stderr[-2000:])
                [sign] = [l for l in log.read_text().splitlines() if l.startswith('apksigner sign')]
                self.assertIn(f'--ks {ROOT / KEY} --ks-key-alias launcher ', sign)
            version = re.search(r'android:versionName="([^"]+)"', (ROOT / 'android/app/AndroidManifest.xml').read_text())[1]
            self.assertTrue((temp / f'out/Rungic-{version}.apk').exists())


class ProvenanceTests(unittest.TestCase):
    # covers: delivery.repo-scope/E4
    def test_every_pinned_upstream_has_source_version_checksum_and_licence(self):
        recipes = sorted((ROOT / 'packages').glob('*/recipe.json'))
        self.assertGreater(len(recipes), 20)
        for path in recipes:
            recipe = json.loads(path.read_text())
            with self.subTest(path.parent.name):
                self.assertTrue(recipe.get('upstream') and recipe.get('version') and recipe.get('source'))
                self.assertTrue(str(recipe.get('licenses', '')).strip(), 'licence recorded')
                if recipe.get('kind') == 'git':
                    self.assertRegex(recipe['commit'], r'^[0-9a-f]{40}$')
                    self.assertRegex(recipe['tree'], r'^[0-9a-f]{40}$')
                else:
                    self.assertTrue(recipe['files'] and recipe.get('fetch'))
                    for name, digest in recipe['files'].items():
                        self.assertRegex(digest, r'^[0-9a-f]{64}$', name)

    # covers: delivery.repo-scope/E4
    def test_audit_exceptions_are_exact_hashes_of_individual_files(self):
        exceptions = json.loads((ROOT / 'provenance/audit-exceptions.json').read_text())
        for name, entry in exceptions.items():
            self.assertFalse(name.endswith('/') or any(c in name for c in '*?['), f'{name}: one file, not a pattern')
            self.assertRegex(entry['sha256'], r'^[0-9a-f]{64}$')
            self.assertTrue(entry['kinds'])


if __name__ == '__main__':
    unittest.main()
