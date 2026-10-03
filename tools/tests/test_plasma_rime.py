"""rungic-plasma-input: the Chinese layout creates Rime's input method on both pages, and the
Rime session holds the shared user dictionary only while the keyboard is in use (docs/41,
2026-10-03)."""
import importlib.machinery
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RIME = ROOT / 'desktop/rime'
loader = importlib.machinery.SourceFileLoader('rime_layouts', str(RIME / 'layouts.py'))
spec = importlib.util.spec_from_loader('rime_layouts', loader)
layouts = importlib.util.module_from_spec(spec)
loader.exec_module(layouts)


def upstream(tmp_path):
    """A plasma-keyboard layouts directory: the test stand-ins for zh_CN and one other layout."""
    source = tmp_path / 'source'
    shutil.copytree(RIME / 'tests/layouts', source)
    (source / 'zh_CN/handwriting.qml').write_text(
        "Qt.createQmlObject('import QtQuick; import QtQuick.VirtualKeyboard.Plugins; HandwritingInputMethod {}', parent)\n")
    (source / 'en_US').mkdir()
    (source / 'en_US/main.qml').write_text('KeyboardLayout {}\n')
    return source


# covers: desktop.rime/E3
def test_both_chinese_pages_create_rime(tmp_path):
    dest = tmp_path / 'dest'
    layouts.build(upstream(tmp_path), dest)
    for page in ('main.qml', 'symbols.qml'):
        text = (dest / 'zh_CN' / page).read_text()
        assert layouts.RIME in text and 'PinyinInputMethod' not in text
    assert 'HandwritingInputMethod' in (dest / 'zh_CN/handwriting.qml').read_text()
    assert (dest / 'en_US').is_symlink()
    assert (dest / 'en_US').readlink() == Path('/usr/share/plasma/keyboard/layouts/en_US')


# covers: desktop.rime/E3
@pytest.mark.parametrize('change', ['main.qml', 'symbols.qml'])
def test_a_changed_upstream_page_stops_the_build(tmp_path, change):
    source = upstream(tmp_path)
    page = source / 'zh_CN' / change
    page.write_text(page.read_text().replace(layouts.PINYIN, 'PinyinInputMethod { id: pinyin }'))
    with pytest.raises(AssertionError, match='changed'):
        layouts.build(source, tmp_path / 'dest')


# covers: desktop.rime/E3
def test_another_page_creating_pinyin_stops_the_build(tmp_path):
    source = upstream(tmp_path)
    (source / 'zh_CN/extra.qml').write_text(layouts.PINYIN + '\n')
    with pytest.raises(AssertionError, match='extra.qml'):
        layouts.build(source, tmp_path / 'dest')


PLASMA_KEYBOARD = ROOT / '.work/pq/plasma-keyboard/src/layouts'


# covers: desktop.rime/E3
@pytest.mark.skipif(not PLASMA_KEYBOARD.is_dir(), reason='no plasma-keyboard source in .work/pq (tools/pq.py prepare)')
def test_plasma_keyboard_layouts(tmp_path):
    layouts.build(PLASMA_KEYBOARD, tmp_path / 'dest')
    chinese = tmp_path / 'dest/zh_CN'
    assert [p.name for p in sorted(chinese.glob('*.qml')) if layouts.RIME in p.read_text()] == ['main.qml', 'symbols.qml']


def engine_missing():
    if not (shutil.which('cmake') and shutil.which('ninja') and shutil.which('pkg-config')):
        return 'no cmake/ninja/pkg-config'
    if subprocess.run(['pkg-config', '--exists', 'rime'], check=False).returncode:
        return 'no librime-dev'
    if not Path('/usr/share/rime-data/luna_pinyin_simp.schema.yaml').exists():
        return 'no rime-data-luna-pinyin'
    if not Path('/usr/lib/qt6/bin/qmltestrunner').exists():
        return 'no qmltestrunner (qt6-declarative-dev-tools)'
    return None


# covers: desktop.rime/E1 desktop.rime/E3 desktop.rime/E4
@pytest.mark.skipif(engine_missing() is not None, reason=f'engine check needs the build dependencies: {engine_missing()}')
def test_engine_and_session_lifecycle(tmp_path):
    """Builds the plugin; rungic-rime-check and the Qt Virtual Keyboard session test (run.sh)."""
    result = subprocess.run(['sh', str(RIME / 'tests/run.sh'), str(tmp_path)], capture_output=True, text=True,
                            timeout=900, check=False)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    assert 'PASS: Rime engine and session lifecycle' in result.stdout
