# SPDX-License-Identifier: MIT
"""The phone's save dialog (xdg-desktop-portal-kde's FilePicker.qml with
packages/xdg-desktop-portal-kde/debian/patches/rungic/mobile-dialog-full-path.patch, docs/103): the
file name field and the save button, as the patch leaves them, run in Qt Quick (PySide6, offscreen).
The upstream file is not in this repository; the patch's hunk carries both whole elements, so they are
taken from it and placed in a page with the folder model the dialog shows. What the button hands the
portal is checked as the application gets it (a file URL, read back with QUrl)."""
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / 'packages/xdg-desktop-portal-kde/debian/patches/rungic/mobile-dialog-full-path.patch'
FOLDER = 'file:///home/me/Pictures'
APP = QGuiApplication.instance() or QGuiApplication([])


def patched_elements():
    """The new side of the patch's FilePicker.qml hunk: the end of the name field and the save button."""
    text = PATCH.read_text()
    hunk = text[text.index('+++ b/src/kirigami-filepicker/declarative/FilePicker.qml'):]
    lines = hunk.splitlines()[1:]
    assert lines[0].startswith('@@')
    body = [line[1:] for line in lines[1:] if line[:1] in (' ', '+')]
    return '\n'.join(body)


PAGE = '''
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
Item {
    id: root
    width: 400; height: 100
    property var fileUrls: []
    property int acceptedCount: 0
    signal accepted(var urls)
    onAccepted: acceptedCount++
    readonly property var field: fileNameField
    readonly property var button: saveButton
    function i18n(text) { return text }
    QtObject { id: dirModel; property string folder: "%s" }
    RowLayout {
        anchors.fill: parent
        Controls.TextField {
%s
'''


@pytest.fixture
def dialog():
    elements = patched_elements()
    source = PAGE % (FOLDER, elements)
    source += '\n}' * (source.count('{') - source.count('}'))
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    component.setData(source.encode(), QUrl())
    page = component.create()
    assert page is not None, component.errorString()
    yield page
    page.deleteLater()


def field_and_button(page):
    return page.property('field'), page.property('button')


def urls(page):
    value = page.property('fileUrls')
    return list(value.toVariant() if hasattr(value, 'toVariant') else value)


def save(page, typed, enter=False):
    field, button = field_and_button(page)
    field.setProperty('text', typed)
    if enter:
        field.accepted.emit()
    else:
        button.clicked.emit()
    return [QUrl(u).toLocalFile() if str(u).startswith('file:') else u for u in urls(page)]


# covers: apps.file-dialog/E2
@pytest.mark.parametrize('typed, saved', [
    ('/home/me/Documents/drawing.kra', '/home/me/Documents/drawing.kra'),      # a full path, as given
    ('file:///home/me/Desktop/a.kra', '/home/me/Desktop/a.kra'),              # a file URL, as given
    ('drawing.kra', '/home/me/Pictures/drawing.kra'),                          # a name, in the folder shown
    ('my #1 draft?.kra', '/home/me/Pictures/my #1 draft?.kra'),               # not cut at # or ?
    ('/home/me/My Pictures/a #b?.kra', '/home/me/My Pictures/a #b?.kra'),
])
def test_the_typed_name_or_path_is_where_it_saves(dialog, typed, saved):
    assert save(dialog, typed) == [saved]
    assert dialog.property('acceptedCount') == 1


# covers: apps.file-dialog/E3
def test_an_empty_name_does_not_save_and_enter_saves(dialog):
    field, button = field_and_button(dialog)
    field.setProperty('text', '')
    assert button.property('enabled') is False
    button.clicked.emit()
    assert dialog.property('acceptedCount') == 0 and urls(dialog) == []
    field.setProperty('text', 'x.kra')
    assert button.property('enabled') is True
    assert save(dialog, 'x.kra', enter=True) == ['/home/me/Pictures/x.kra']
    assert dialog.property('acceptedCount') == 1


def test_the_hunk_is_the_whole_save_row():
    """If upstream moves these elements, the hunk no longer holds them whole and this test must be redone."""
    elements = patched_elements()
    assert re.search(r'id: fileNameField', elements) and re.search(r'id: saveButton', elements)
    assert elements.count('{') - elements.count('}') == -1     # it closes the field it starts in
