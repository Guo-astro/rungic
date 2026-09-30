#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Rungic rename of the repository's own names (docs/70), phase B: everything whose readers and
writers are all inside the container (or host tools). Names the Android side reads, writes or
creates (APK, native host, Magisk scripts, /data/adb, bind mounts it creates, SELinux, dm) are
protected and move in phase C with the APK. Hardware names (Motorola, moto g100s) and history
(docs records, benchmarks, provenance, changelogs) are never touched.

  rebrand.py list                 files and paths the rename would change
  rebrand.py apply [--paths]      rewrite contents; --paths also git-mv renamed paths
  rebrand.py residue              occurrences left (protected ones excluded)

The rewritten tree is reviewed by hand before it is committed: the rules are mechanical. `apply`
ran once for phase B (2026-09-26); the review then restored names the rules cannot tell apart
(state written before the rename that migrations read, Motorola's and the APK's log tags), so
`list` shows those files again and `apply` must not run again over them.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Whole files or trees left as they are: history, phase C (Android side), upstream text.
SKIP = [
    r'^docs/', r'^benchmarks/', r'^provenance/', r'^signing/', r'^\.work/',
    r'(^|/)debian/changelog$', r'^tools/pq-history/', r'^tools/rebrand\.py$',
    r'^(?!packages/).*\.patch$',          # historical patches: import evidence the pq-history plans name
    r'^packages/(android-host|smithay|winit)/', r'^plasma/android-host/',
    r'^plasma/native-apk/', r'^shared/android/', r'^docker/', r'^lxc/', r'^cutout/', r'^kernel/', r'^plasma/build-apk\.sh$', r'^plasma/build-native-core\.sh$',
    r'^tools/moto-magisk-bootstrap\.', r'^tools/moto_.*enter', r'enter\.c$',
    r'^plasma/rootfs-image$', r'^plasma/rootfs-mount-hook$', r'^plasma/rootfs\.sepolicy\.rule$',
    r'^plasma/build-launcher\.sh$',        # builds the Android-side enter program
    r'^plasma/android-audio(\.pa)?$',     # Termux PulseAudio on Android; the enter program binds its directory
    # ROM and product-partition tools: host directories that exist, the delta file format's magic
    r'^tools/(assemble_clean_rom|build_offline_magisk|build_product_delta|product_delta|test_product_delta|'
    r'restore_gki_module_certificate|verify_clean_rom|verify_offline_device|verify_offline_product)\.py$',
    r'\.(png|jpg|jpeg|webp|ico|jar|apk|so|a|p12|keystore|ttf|otf|gz|xz|zst|deb|bin|img|pcm|wav|ogg|mp4)$',
]

# Protected spans (phase C, hardware, other words). Matched first and restored unchanged.
PROTECT = [
    r'/data/adb/moto-[A-Za-z0-9_./-]*', r'/data/user/0/dev\.moto\.plasma[A-Za-z0-9_./-]*',
    r'dev\.moto\.plasma[A-Za-z0-9_.]*', r'dev/moto/plasma', r'Java_dev_moto_plasma\w*',
    r'moto-plasma-enter', r'moto-lxc[A-Za-z0-9_-]*', r'moto[-_]docker[A-Za-z0-9_-]*', r'moto-wfd[A-Za-z0-9_.-]*',
    r'moto_plasma_image', r'moto-plasma-root', r'debug\.moto\.[a-z_]+', r'moto-magisk-bootstrap[A-Za-z0-9_.-]*',
    r'moto-gpu-alloc', r'moto-zero-copy', r'moto-android-sdk',
    r'(?:/?var/lib/)moto-(?:host|cores|apt)\b', r'\bmoto-(?:cores|apt):',
    r'lxc\.uts\.name\s*=\s*moto-plasma',
    r'MOTO_(?:ANDROID|APK)_[A-Z_]+', r'MOTO_NATIVE_LIBS', r'MOTO_JNI_LIBS_DIR', r'MOTO_XKBCOMMON_LIB',
    r'QLatin1String\("Moto"\)',           # the APK host's cast outputs (make "Moto", model "Cast")
    # the Magisk launcher itself: bare "moto-plasma" (not moto-plasma-X) and its directory
    r'\bmoto-plasma(?![A-Za-z0-9_-])',
    # hardware and unrelated words
    r'[Mm]otorola\w*', r'MOTOROLA\w*', r'moto g\d+\w*', r'\bmoto\s+g\b',
]

# Ordered rewrites applied to the unprotected text.
RULES = [
    (r'dev\.moto\.', 'com.rungic.'),
    (r'\bMOTO_', 'RUNGIC_'),
    (r'_MOTO_', '_RUNGIC_'),
    (r'\bMoto(?=[A-Z])', 'Rungic'),                    # MotoDisplay, MotoEncoder, MotoVoiceAssistant
    (r'\bMoto(?= \(docs/| \(docs|:)', 'Rungic'),        # "Moto (docs/59):" and "Moto:" markers
    (r'(?<![A-Za-z])moto(?=h26|vp9|codec|rime|cua|ocr)', 'rungic'),   # motoh264enc, libmotocodec
    (r'(?<=[a-z0-9])_moto(?=\b|_)', '_rungic'),          # ff_h264_moto_decoder, h264_moto
    (r'_MOTO(?=_|\b)', '_RUNGIC'),
    (r'(?<![A-Za-z])moto_', 'rungic_'),
    (r'(?<![A-Za-z])moto-', 'rungic-'),
    (r'(?<![A-Za-z])moto\.(?=[a-z])', 'rungic.'),       # moto.upd, moto.sources, moto.camera.0
    (r'(?<=/share/)moto\b', 'rungic'),                  # /usr/share/moto
    (r'(?<=[0-9])moto(?=-)', 'rungic'),                 # 80moto-proxy
]

PATH_RULES = [
    (r'dev\.moto\.', 'com.rungic.'),
    (r'(?<![A-Za-z])moto(?=h26|vp9|codec|rime|cua|ocr)', 'rungic'),
    (r'(?<![A-Za-z])moto_', 'rungic_'),
    (r'(?<![A-Za-z])moto-', 'rungic-'),
    (r'(?<![A-Za-z])moto\.(?=[a-z])', 'rungic.'),
    (r'(?<![A-Za-z])Moto(?=[A-Z])', 'Rungic'),
]

KEEP_PATHS = [r'^plasma/moto-plasma$']    # the Magisk launcher (phase C)


def files():
    out = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, check=True).stdout
    for name in out.decode().split('\0'):
        if name and not any(re.search(p, name) for p in SKIP) and not (ROOT / name).is_symlink():
            yield name


PROTECT_RE = re.compile('|'.join(f'(?:{p})' for p in PROTECT))


def rewrite(text):
    saved = []

    def hold(m):
        saved.append(m.group(0))
        return f'\x00{len(saved) - 1}\x00'
    text = PROTECT_RE.sub(hold, text)
    for pattern, repl in RULES:
        text = re.sub(pattern, repl, text)
    return re.sub('\x00(\\d+)\x00', lambda m: saved[int(m.group(1))], text)


def new_path(name):
    if any(re.search(p, name) for p in KEEP_PATHS):
        return name
    parts = []
    for part in name.split('/'):
        if not PROTECT_RE.fullmatch(part):
            for pattern, repl in PATH_RULES:
                part = re.sub(pattern, repl, part)
        parts.append(part)
    return '/'.join(parts)


def read(name):
    try:
        return (ROOT / name).read_text(encoding='utf-8')
    except (UnicodeDecodeError, FileNotFoundError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action', choices=('list', 'apply', 'residue'))
    ap.add_argument('--paths', action='store_true')
    args = ap.parse_args()
    names = list(files())
    if args.action == 'residue':
        for name in names:
            text = read(name)
            if text is None:
                continue
            masked = PROTECT_RE.sub('', text)
            for n, line in enumerate(masked.splitlines(), 1):
                if re.search(r'(?<![A-Za-z])[Mm]oto(?![a-qs-z])|MOTO', line) and not re.search(r'[Mm]otor', line):
                    print(f'{name}:{n}: {line.strip()[:160]}')
        return
    changed = 0
    for name in names:
        text = read(name)
        if text is not None:
            new = rewrite(text)
            if new != text:
                changed += 1
                if args.action == 'list':
                    print('content', name)
                else:
                    (ROOT / name).write_text(new, encoding='utf-8')
    moves = [(n, new_path(n)) for n in names if new_path(n) != n]
    for old, new in moves:
        if args.action == 'list':
            print('path', old, '->', new)
        elif args.paths:
            (ROOT / new).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['git', 'mv', old, new], cwd=ROOT, check=True)
    print(f'{changed} files with content changes, {len(moves)} paths', file=sys.stderr)


if __name__ == '__main__':
    main()
