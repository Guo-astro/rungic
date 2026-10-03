#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The development environment in one step (docs/52): tools/work-env.sh puts caches and build output
in .work/ and turns on .work/venv; tools/dev-setup.sh makes that venv; the Android cross-compiler
wrappers follow the variables that point them at this machine's clang and sysroot. Each script is run
for real, in a copy of the repository's layout, with stand-ins for what would download or compile."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def copy_tree(root, names):
    for name in names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


class WorkEnvTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'repo'
        copy_tree(self.root, ['tools/work-env.sh', '.cargo/config.toml'])
        (self.root / 'src').mkdir()
        (self.root / 'src/module.py').write_text('VALUE = 1\n')

    def source(self, script):
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPYCACHEPREFIX', 'CARGO_TARGET_DIR', 'VIRTUAL_ENV',
                                                              'PYTHONDONTWRITEBYTECODE')}
        return subprocess.run(['bash', '-c', f'cd /tmp && source {self.root}/tools/work-env.sh && {script}'],
                              capture_output=True, text=True, env=env)

    # covers: delivery.dev-env/E1
    def test_caches_and_build_output_go_to_work(self):
        executable(self.root / '.work/venv/bin/python', '#!/bin/sh\nexec python3 "$@"\n')
        (self.root / '.work/venv/bin/activate').write_text(
            f'VIRTUAL_ENV={self.root}/.work/venv; export VIRTUAL_ENV; PATH="$VIRTUAL_ENV/bin:$PATH"; export PATH\n')
        result = self.source(f'echo "$PYTHONPYCACHEPREFIX"; echo "$CARGO_TARGET_DIR"; command -v python; '
                             f'cd {self.root}/src && python -c "import module"')
        self.assertEqual(result.returncode, 0, result.stderr)
        cache, target, python = result.stdout.splitlines()[:3]
        self.assertEqual(cache, f'{self.root}/.work/cache/python')
        self.assertEqual(target, f'{self.root}/.work/build/native-target')
        self.assertEqual(python, f'{self.root}/.work/venv/bin/python')
        self.assertTrue(Path(cache).is_dir() and Path(target).is_dir())
        self.assertEqual(sorted(p.name for p in (self.root / 'src').iterdir()), ['module.py'], 'no cache in the source tree')
        self.assertTrue(list(Path(cache).rglob('module.*.pyc')))
        # Cargo run without the environment builds into the same place (.cargo/config.toml).
        self.assertIn('target-dir = ".work/build/native-target"', (self.root / '.cargo/config.toml').read_text())

    # covers: delivery.dev-env/E1
    def test_without_a_venv_it_says_how_to_make_one(self):
        result = self.source('echo "$PYTHONPYCACHEPREFIX"')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), f'{self.root}/.work/cache/python')
        self.assertIn('sh tools/dev-setup.sh', result.stderr)


class DevSetupTests(unittest.TestCase):
    # covers: delivery.dev-env/E2
    def test_one_run_makes_the_venv_and_says_the_pyside6_version(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'repo'
            copy_tree(root, ['tools/dev-setup.sh', 'tools/dev-requirements.txt'])
            log = Path(temp) / 'log'
            # python3 -m venv makes a venv whose python logs what it is asked (no download here).
            venv_python = ('#!/bin/sh\necho "venv-python $*" >> "$LOG"\n'
                           'case "$1" in -c) echo "PySide6 6.10.0 in $(dirname $(dirname $0))" ;; esac\n')
            executable(Path(temp) / 'bin/python3',
                       f'#!/bin/sh\necho "python3 $*" >> "$LOG"\n'
                       f'[ "$1 $2" = "-m venv" ] || exit 1\nmkdir -p "$4/bin"\n'
                       f'cat > "$4/bin/python" <<\'EOF\'\n{venv_python}EOF\nchmod 755 "$4/bin/python"\n')
            env = {**os.environ, 'PATH': f'{temp}/bin:{os.environ["PATH"]}', 'LOG': str(log)}
            result = subprocess.run(['sh', str(root / 'tools/dev-setup.sh')], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), f'PySide6 6.10.0 in {root}/.work/venv')
            lines = log.read_text().splitlines()
            self.assertEqual(lines[0], f'python3 -m venv --system-site-packages {root}/.work/venv')
            self.assertIn(f'venv-python -m pip install --quiet -r {root}/tools/dev-requirements.txt', lines)
            # A second run reuses the venv.
            subprocess.run(['sh', str(root / 'tools/dev-setup.sh')], capture_output=True, text=True, env=env, check=True)
            self.assertEqual(sum(l.startswith('python3 -m venv') for l in log.read_text().splitlines()), 1)

        wanted = [l.split('>=')[0].strip() for l in (ROOT / 'tools/dev-requirements.txt').read_text().splitlines()
                  if l.strip() and not l.startswith('#')]
        self.assertEqual(wanted, ['PySide6', 'pytest'])

    # covers: delivery.dev-env/E2
    def test_the_development_python_goes_into_no_image_or_package(self):
        shipped = [(ROOT / 'system/ubuntu-packages.txt').read_text().lower()]
        for path in sorted((ROOT / 'packaging').glob('*/package.json')):
            package = json.loads(path.read_text())
            for entry in package.get('paths', []):
                self.assertFalse(entry.startswith(('tools/dev-', '.work')), f'{path}: {entry}')
            shipped.append(str(package.get('depends', '')).lower())
        for text in shipped:
            self.assertNotIn('pyside6', text)
            self.assertNotIn('python3-pytest', text)


class AndroidClangTests(unittest.TestCase):
    # covers: delivery.dev-env/E3
    def test_the_wrappers_use_this_machines_clang_and_sysroot(self):
        with tempfile.TemporaryDirectory() as temp:
            fake = Path(temp) / 'clang'
            executable(fake, '#!/bin/sh\nfor a in "$0" "$@"; do echo "$a"; done\n')
            env = {**os.environ, 'RUNGIC_ANDROID_CLANG': str(fake), 'RUNGIC_ANDROID_CLANGXX': str(fake) + '++',
                   'RUNGIC_ANDROID_SYSROOT': f'{temp}/sysroot', 'RUNGIC_ANDROID_LINK_LIBS': f'{temp}/link',
                   'RUNGIC_JNI_LIBS_DIR': f'{temp}/jni'}
            shutil.copy(fake, str(fake) + '++')
            for wrapper, compiler in (('android-clang', str(fake)), ('android-clang++', str(fake) + '++')):
                with self.subTest(wrapper):
                    out = subprocess.run([str(ROOT / 'tools/toolchains' / wrapper), '-c', 'a b.c', '-o', 'x.o'],
                                         capture_output=True, text=True, env=env, check=True).stdout.splitlines()
                    self.assertEqual(out, [compiler, '--target=aarch64-linux-android31', f'--sysroot={temp}/sysroot',
                                           f'-L{temp}/link', f'-L{temp}/jni', '-Wl,--allow-shlib-undefined',
                                           '-c', 'a b.c', '-o', 'x.o'])
            # Without the variables: the libraries the build prepared in .work.
            env = {k: v for k, v in env.items() if k not in ('RUNGIC_ANDROID_LINK_LIBS', 'RUNGIC_JNI_LIBS_DIR')}
            out = subprocess.run([str(ROOT / 'tools/toolchains/android-clang')], capture_output=True, text=True, env=env,
                                 check=True).stdout.splitlines()
            self.assertIn(f'-L{ROOT}/.work/deps/android-link-libs', out)


if __name__ == '__main__':
    unittest.main()
