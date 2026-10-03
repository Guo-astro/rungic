# SPDX-License-Identifier: MIT
"""The desktop in Chinese (docs/55): the recovery of the Chinese translations Ubuntu minimal drops
(desktop/restore-chinese-translations.py, run on a real .deb here), and this project's own programs
speaking the desktop language: every text a program marks for translation has a Simplified Chinese
translation in the catalog the program binds, with the same placeholders, and the catalog loads."""
import ast
import gettext
import json
import re
import struct
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESTORE = ROOT / 'desktop/restore-chinese-translations.py'

# The programs, their sources and the catalog (zh_CN) their texts are looked up in.
PROGRAMS = {
    'device page': (['desktop/device-panel.py'], 'desktop/po/zh_CN/rungic-platform.po'),
    'power policy': (['desktop/power-policy.py'], 'desktop/po/zh_CN/rungic-power-policy.po'),
    'recording settings': (['desktop/recording/settings.py'], 'desktop/recording/po/zh_CN/rungic-recording-settings.po'),
    'recording tile': (['desktop/recording/recordutil.cpp', 'desktop/recording/quicksetting/contents/ui/main.qml'],
                       'desktop/recording/po/zh_CN/plasma_com.rungic.quicksetting.record.po'),
    'services page': (['desktop/services/servicessettings.cpp', 'desktop/services/ui/main.qml'],
                      'desktop/services/po/zh_CN/kcm_rungic_services.po'),
    # Not Gallery.qml: the state gallery is a developer's sheet of samples (tools/design_gallery.py).
    'design system': (sorted(str(p.relative_to(ROOT)) for p in (ROOT / 'desktop/design/qml').glob('*.qml')
                             if p.name != 'Gallery.qml'),
                      'desktop/design/po/zh_CN/rungic-design.po'),
    'cast tile': (['desktop/cast/quicksetting/contents/ui/main.qml', 'desktop/cast/quicksetting/contents/ui/CastPicker.qml'],
                  'desktop/cast/po/zh_CN/plasma_com.rungic.quicksetting.cast.po'),
    'camera and media bridges': (['shared/media/media-bridge.py', 'shared/media/camera-source.cpp'],
                                 'shared/po/zh_CN/rungic-shared.po'),
}

C_STRING = r'"((?:[^"\\]|\\.)*)"'


def unescape(text):
    return re.sub(r'\\(.)', lambda m: {'n': '\n', 't': '\t'}.get(m.group(1), m.group(1)), text)


def parse_po(path):
    """{(context, msgid): (msgid_plural, [msgstr...])} of a .po file (fuzzy entries count as missing)."""
    entries, entry, field, fuzzy = {}, {}, None, False

    def flush():
        nonlocal entry, fuzzy
        if 'msgid' in entry and entry['msgid'] and not fuzzy:
            strs = [entry[k] for k in sorted(k for k in entry if k.startswith('msgstr'))]
            entries[(entry.get('msgctxt'), entry['msgid'])] = (entry.get('msgid_plural'), strs)
        elif 'msgid' in entry and not entry['msgid']:
            entries[(None, '')] = (None, [entry.get('msgstr', '')])
        entry, fuzzy = {}, False
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            flush()
            continue
        if line.startswith('#,') and 'fuzzy' in line:
            fuzzy = True
        if line.startswith('#'):
            continue
        m = re.match(r'(msgctxt|msgid_plural|msgid|msgstr(?:\[\d+\])?)\s+' + C_STRING + '$', line)
        if m:
            if m.group(1) in ('msgctxt', 'msgid') and any(k.startswith('msgstr') for k in entry):
                flush()
            field = m.group(1)
            entry[field] = unescape(m.group(2))
        elif re.match(C_STRING + '$', line) and field:
            entry[field] += unescape(line[1:-1])
    flush()
    return entries


def texts(source):
    """The (context, msgid, plural) a source marks for translation."""
    path = ROOT / source
    out = set()
    if path.suffix == '.py':
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            args = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if node.func.id == '_' and args:
                out.add((None, args[0], None))
            elif node.func.id == 'pgettext' and len(args) == 2:
                out.add((args[0], args[1], None))
        return out
    text = path.read_text()
    s = r'\s*' + C_STRING + r'\s*'
    for m in re.finditer(r'\bi18n\(' + s + r'[,)]', text):
        out.add((None, unescape(m.group(1)), None))
    for m in re.finditer(r'\bi18nc\(' + s + ',' + s + r'[,)]', text):
        out.add((unescape(m.group(1)), unescape(m.group(2)), None))
    for m in re.finditer(r'\bi18np\(' + s + ',' + s + ',', text):
        out.add((None, unescape(m.group(1)), unescape(m.group(2))))
    for m in re.finditer(r'\bi18ncp\(' + s + ',' + s + ',' + s + ',', text):
        out.add((unescape(m.group(1)), unescape(m.group(2)), unescape(m.group(3))))
    for m in re.finditer(r'\btr\(' + s + r'\)', text):          # dgettext wrapper (camera-source.cpp)
        out.add((None, unescape(m.group(1)), None))
    return out


def placeholders(text):
    return sorted(re.findall(r'%\d+|\{[a-z_]*(?::[^}]*)?\}|%[sd]', text))


def policy_texts():
    policy = json.loads((ROOT / 'desktop/services/policy.json').read_text())
    out = set()
    for group in policy['groups']:
        for key in ('name', 'summary', 'warning'):
            # A group named after its program (NetworkManager, cloud-init) keeps the name.
            if group.get(key) and not (key == 'name' and re.fullmatch(r'[\w.-]+', group[key])):
                out.add((None, group[key], None))
    return out


def write_mo(entries, path):
    """A GNU .mo file of the catalog (msgfmt's format), for gettext to load."""
    pairs = []
    for (ctx, msgid), (plural, strs) in entries.items():
        key = (ctx + '\x04' if ctx else '') + msgid + ('\0' + plural if plural else '')
        pairs.append((key.encode(), '\0'.join(strs).encode()))
    pairs.sort()
    n = len(pairs)
    ids = b''.join(k + b'\0' for k, _ in pairs)
    strs = b''.join(v + b'\0' for _, v in pairs)
    start = 7 * 4 + 16 * n
    table_ids, table_strs, offset = [], [], start
    for k, _ in pairs:
        table_ids += [len(k), offset]
        offset += len(k) + 1
    for _, v in pairs:
        table_strs += [len(v), offset]
        offset += len(v) + 1
    path.write_bytes(struct.pack('Iiiiiii', 0x950412de, 0, n, 7 * 4, 7 * 4 + 8 * n, 0, 0)
                     + struct.pack(f'{2 * n}i', *table_ids) + struct.pack(f'{2 * n}i', *table_strs) + ids + strs)


# covers: desktop.chinese/E2
@pytest.mark.parametrize('program', sorted(PROGRAMS))
def test_every_text_of_the_program_has_its_chinese(program, tmp_path):
    sources, po = PROGRAMS[program]
    catalog = parse_po(ROOT / po)
    header = catalog.get((None, ''), (None, ['']))[1][0]
    assert 'charset=UTF-8' in header and 'Language: zh_CN' in header
    wanted = set().union(*(texts(s) for s in sources))
    if program == 'services page':
        wanted |= policy_texts()
    assert wanted, f'{program}: no texts found in {sources}'
    missing, broken = [], []
    for ctx, msgid, plural in sorted(wanted, key=str):
        found = catalog.get((ctx, msgid))
        if not found or not all(found[1]) or (plural and found[0] != plural):
            missing.append((ctx, msgid))
            continue
        for translated in found[1]:
            if plural:      # Chinese has one form, written with the plural's placeholders
                ok = set(placeholders(translated)) == set(placeholders(plural))
            else:
                ok = placeholders(translated) == placeholders(msgid)
            if not ok:
                broken.append((msgid, translated))
    assert not missing, f'{program}: not translated: {missing}'
    assert not broken, f'{program}: placeholders differ: {broken}'
    # The catalog loads as gettext reads it at run time.
    domain = Path(po).stem
    mo = tmp_path / 'zh_CN/LC_MESSAGES' / f'{domain}.mo'
    mo.parent.mkdir(parents=True)
    write_mo(catalog, mo)
    translation = gettext.translation(domain, localedir=tmp_path, languages=['zh_CN'])
    ctx, msgid, plural = sorted(wanted, key=str)[0]
    got = translation.pgettext(ctx, msgid) if ctx else translation.gettext(msgid)
    assert got == catalog[(ctx, msgid)][1][0] and got != msgid or plural


# covers: desktop.chinese/E2
def test_the_programs_bind_the_catalogs_their_packages_install():
    # Python programs: gettext domain named in the source; installed to /usr/share/locale.
    for source, domain in (('desktop/device-panel.py', 'rungic-platform'),
                           ('desktop/power-policy.py', 'rungic-power-policy'),
                           ('desktop/recording/settings.py', 'rungic-recording-settings'),
                           ('shared/media/media-bridge.py', 'rungic-shared')):
        assert f"gettext.translation('{domain}'" in (ROOT / source).read_text(), source
    builds = '\n'.join(p.read_text() for p in (ROOT / 'packaging').glob('*/build.sh'))
    assert 'rungic-power-policy.mo' in builds and 'for domain in rungic-platform' in builds
    assert 'rungic-shared.mo' in builds
    # C++/QML programs: KI18n's TRANSLATION_DOMAIN, the catalog installed by ki18n_install(po).
    for cmake, domain in (('desktop/recording/CMakeLists.txt', 'plasma_com.rungic.quicksetting.record'),
                          ('desktop/services/CMakeLists.txt', 'kcm_rungic_services')):
        text = (ROOT / cmake).read_text()
        assert f'TRANSLATION_DOMAIN="{domain}"' in text and 'ki18n_install(po)' in text
    assert 'translationDomain: "rungic-design"' in (ROOT / 'desktop/design/qml/DesignI18n.qml').read_text()
    assert 'ki18n_install(po)' in (ROOT / 'desktop/design/CMakeLists.txt').read_text()


def make_deb(tmp_path, name, files):
    tree = tmp_path / f'{name}-tree'
    for relative, data in files.items():
        path = tree / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.parent.chmod(0o775)                      # not what / or /usr have
    (tree / 'DEBIAN').mkdir()
    (tree / 'DEBIAN/control').write_text(f'Package: {name}\nVersion: 1\nArchitecture: all\n'
                                         'Maintainer: test <t@example.org>\nDescription: test\n')
    debs = tmp_path / 'archives'
    debs.mkdir(exist_ok=True)
    # Built as the test user: the members are owned by this UID, as a builder's tree would be.
    subprocess.run(['dpkg-deb', '--build', '-Zgzip', str(tree), str(debs / f'{name}.deb')], check=True,
                   capture_output=True)


# covers: desktop.chinese/E1
def test_only_chinese_catalogs_are_recovered_as_root_owned_files(tmp_path):
    make_deb(tmp_path, 'plasma-workspace', {
        'usr/share/locale/zh_CN/LC_MESSAGES/plasma_shell.mo': b'zh-cn catalog',
        'usr/share/locale/zh_CN/LC_MESSAGES/README': b'not a catalog',
        'usr/share/locale/de/LC_MESSAGES/plasma_shell.mo': b'german',
        'usr/bin/plasmashell': b'#!/bin/sh\n',
    })
    make_deb(tmp_path, 'xdg-desktop-portal-kde', {
        'usr/share/locale/zh_Hans/LC_MESSAGES/xdg-desktop-portal-kde.mo': b'zh-hans catalog',
    })
    archive = tmp_path / 'translations.tar'
    out = subprocess.run([sys.executable, str(RESTORE), str(tmp_path / 'archives'), str(tmp_path / 'stage'), str(archive)],
                         capture_output=True, text=True, check=True).stdout
    assert 'Chinese translation files recovered: 2' in out
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        assert sorted(m.name for m in members) == ['usr/share/locale/zh_CN/LC_MESSAGES/plasma_shell.mo',
                                                   'usr/share/locale/zh_Hans/LC_MESSAGES/xdg-desktop-portal-kde.mo']
        # Regular files only: extracting it into / creates no directory entry, so it cannot change
        # the owner or mode of /, /usr or any other existing directory.
        assert all(m.isfile() for m in members)
        assert all((m.uid, m.gid, m.uname, m.gname, m.mode) == (0, 0, 'root', 'root', 0o644) for m in members)
        assert tar.extractfile('usr/share/locale/zh_CN/LC_MESSAGES/plasma_shell.mo').read() == b'zh-cn catalog'
