#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The design system's behaviour (desktop/design/qml, docs/87, docs/102), offline with PySide6:
the real QML controls in a window of their own, the module staged as tools/design_gallery.py does
(SystemTheme and DesignI18n are stand-ins: the system's dark comes from a property the test sets,
not from kdeglobals).

Requires PySide6 (sh tools/dev-setup.sh); QT_QPA_PLATFORM=offscreen runs it without a desktop.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlProperty
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import design_gallery  # noqa: E402

APP = QGuiApplication.instance() or QGuiApplication([])
QQuickStyle.setStyle('Basic')


# ---------------------------------------------------------------- helpers

def wait(condition, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        APP.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    return condition()


def items(root):
    stack, out = [root], []
    while stack:
        item = stack.pop()
        out.append(item)
        stack.extend(item.childItems())
    return out


def kind(item):
    return item.metaObject().className()


def find(root, cls, **props):
    for item in items(root):
        if kind(item).startswith(cls) and all(item.property(k) == v for k, v in props.items()):
            return item
    raise LookupError(f'no {cls} with {props}')


def centre(item):
    p = item.mapToScene(item.boundingRect().center())
    return QPoint(round(p.x()), round(p.y()))


def shown(item):
    while item is not None:
        if not item.isVisible() or item.opacity() == 0:
            return False
        item = item.parentItem()
    return True


# WCAG 2.2 relative luminance and contrast ratio.
def luminance(rgb):
    def channel(v):
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def over(top, alpha, below):
    return tuple(t * alpha + b * (1 - alpha) for t, b in zip(top, below))


def rgb(colour):
    return (colour.redF(), colour.greenF(), colour.blueF())


PAGE_SWIPE = '''import QtQuick
Item {
    property bool active: false
    property bool dragging: false
    signal started()
    signal moved(real distance)
    signal released(real distance, bool forward)
    signal cancelled()
}
'''


class Scene(unittest.TestCase):
    """Each test loads a QML window that imports the staged com.rungic.design."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        module = design_gallery.stage_module(cls.base / 'qml')
        # PageStack's gesture is C++ (pageswipe.cpp, not built here): a stand-in with its
        # properties and signals, which a test emits as the C++ does once it has recognised a swipe.
        (module / 'PageSwipe.qml').write_text(PAGE_SWIPE)
        with open(module / 'qmldir', 'a') as qmldir:
            qmldir.write('PageSwipe 1.0 PageSwipe.qml\n')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def load(self, body, name='scene.qml'):
        path = self.base / name
        path.write_text('import QtQuick\nimport QtQuick.Controls as QQC2\nimport com.rungic.design\n'
                        'QQC2.ApplicationWindow { id: window; visible: true; width: 390; height: 844\n'
                        ' function setSystemDark(v) { SystemTheme.dark = v }\n'
                        ' function setMode(m) { Theme.mode = m }\n'
                        f'{body}\n}}\n')
        self.engine = QQmlApplicationEngine()
        self.engine.addImportPath(str(self.base / 'qml'))
        self.engine.load(QUrl.fromLocalFile(str(path)))
        self.assertTrue(self.engine.rootObjects(), f'{name} did not load')
        self.window = self.engine.rootObjects()[0]
        self.assertTrue(wait(lambda: self.window.isExposed()))
        return self.window

    def tearDown(self):
        window, engine = getattr(self, 'window', None), getattr(self, 'engine', None)
        self.window = self.engine = None            # a test may tear down itself between subtests
        if window is not None and shiboken6.isValid(window):
            window.close()
            window.deleteLater()
        if engine is not None and shiboken6.isValid(engine):
            engine.deleteLater()
        # Gone now, not at some later module's event processing (GLib's main loop dispatches Qt's
        # events too: a window deleted under test_platform_bridges crashed in its backing store).
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()

    def root(self):
        return self.window.contentItem()

    def tap(self, item):
        """A quick tap: pressed and let go at once."""
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, centre(item))


# ---------------------------------------------------------------- E1: dark and light

class ThemeTest(Scene):
    # Theme.qml's half of desktop.design-system/E1 (SystemTheme here is a stand-in: reading
    # kdeglobals is systemtheme.cpp, keeping the choice is each app's Settings; neither is examined).
    def test_follows_the_system_until_the_app_pins_a_look(self):
        self.load('ListGroup { width: 300; ListRow { text: "Row"; accessory: "chevron" } }\n'
                  'property color ink: Theme.text\nproperty color ground: Theme.background')
        w = self.window
        row = find(self.root(), 'ListRow', text='Row')
        light = (w.property('ground').name(), row.property('ink').name())
        self.assertEqual(light, ('#ffffff', '#232629'))
        # The system turns dark: an app on "system" turns with it, its controls too.
        w.setSystemDark(True)
        self.assertTrue(wait(lambda: w.property('ground').name() == '#141618'))
        self.assertEqual(row.property('ink').name(), '#fcfcfc')
        w.setSystemDark(False)
        self.assertTrue(wait(lambda: w.property('ground').name() == '#ffffff'))
        # Pinned in the app, the look stays whatever the system does.
        w.setMode('dark')
        for system in (False, True, False):
            w.setSystemDark(system)
            APP.processEvents()
            self.assertEqual(w.property('ground').name(), '#141618')
        w.setMode('light')
        for system in (True, False, True):
            w.setSystemDark(system)
            APP.processEvents()
            self.assertEqual(w.property('ground').name(), '#ffffff')
            self.assertEqual(row.property('ink').name(), '#232629')
        # Back to following: the system is dark now.
        w.setMode('system')
        self.assertTrue(wait(lambda: w.property('ground').name() == '#141618'))


# ---------------------------------------------------------------- E2: pressed feedback

class PressedTest(Scene):
    ROWS = '''ListGroup {
        width: 360
        ListRow { text: "Link"; accessory: "chevron" }
        ListRow { text: "Info"; value: "1.0" }
        ChoiceRow { text: "Choice" }
        ToggleRow { text: "Toggle" }
    }'''

    def held(self, row, tap):
        """How long `row` shows its pressed state after `tap`, in seconds."""
        tap()
        tapped = time.monotonic()
        self.assertEqual(row.property('visualState'), 'pressed', 'the tap is seen at once')
        self.assertTrue(wait(lambda: row.property('visualState') != 'pressed', 2))
        return time.monotonic() - tapped

    # covers: desktop.design-system/E2
    def test_a_quick_tap_shows_pressed_at_least_150_ms(self):
        self.load(self.ROWS)
        self.assertGreaterEqual(self.engine.rootObjects()[0].property('visible'), True)
        for text in ('Link', 'Choice', 'Toggle'):
            with self.subTest(row=text):
                row = find(self.root(), 'ListRow' if text == 'Link' else text + 'Row', text=text)
                seconds = self.held(row, lambda: self.tap(row))
                # Qt's coarse timers may fire up to 5% early.
                self.assertGreaterEqual(seconds, 0.150 * 0.95)
                self.assertLess(seconds, 0.6, 'and then goes back to normal')
                self.assertEqual(row.property('visualState'), 'normal')

    # covers: desktop.design-system/E2
    def test_a_quick_touch_tap_shows_pressed_too(self):
        self.load(self.ROWS)
        device = QTest.createTouchDevice()
        row = find(self.root(), 'ChoiceRow', text='Choice')

        def touch():
            QTest.touchEvent(self.window, device).press(0, centre(row), self.window).commit()
            QTest.touchEvent(self.window, device).release(0, centre(row), self.window).commit()
        clicked = []
        row.clicked.connect(lambda: clicked.append(1))
        self.assertGreaterEqual(self.held(row, touch), 0.150 * 0.95)
        self.assertEqual(clicked, [1])

    # covers: desktop.design-system/E2
    def test_the_switch_presses_with_its_row_and_the_row_flips_it(self):
        self.load(self.ROWS)
        row = find(self.root(), 'ToggleRow', text='Toggle')
        switch = find(row, 'Toggle_QMLTYPE')
        switched = []
        row.switched.connect(lambda on: switched.append(on))
        self.tap(row)
        self.assertEqual(row.property('visualState'), 'pressed')
        self.assertEqual(switch.property('visualState'), 'pressed-on')
        self.assertTrue(row.property('checked'))
        self.assertEqual(switched, [True])
        self.assertTrue(wait(lambda: switch.property('visualState') == 'on'))

    # covers: desktop.design-system/E2
    def test_a_row_that_does_nothing_shows_no_press(self):
        self.load(self.ROWS)
        row = find(self.root(), 'ListRow', text='Info')
        QTest.mousePress(self.window, Qt.LeftButton, Qt.NoModifier, centre(row))
        APP.processEvents()
        self.assertEqual(row.property('visualState'), 'normal')
        QTest.mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, centre(row))


# ---------------------------------------------------------------- E3: the choice sheet

class ChoiceSheetTest(Scene):
    SHEET = '''property var picked: []
    ChoiceSheet {
        id: sheet
        objectName: "sheet"
        title: "Theme"
        choices: [{ value: "system", text: "System" }, { value: "light", text: "Light" }, { value: "dark", text: "Dark" }]
        current: "system"
        onChosen: value => { window.picked = window.picked.concat([value]); current = value }
    }
    function openSheet() { sheet.open() }
    function pickedList() { return picked.join(",") }
    function sheetOpen() { return sheet.opened }
    function sheetVisible() { return sheet.visible }
    function sheetY() { return sheet.y }
    function sheetHeight() { return sheet.height }'''

    def open_sheet(self):
        w = self.load(self.SHEET)
        w.openSheet()
        self.assertTrue(wait(lambda: w.sheetOpen()))
        return w

    def choice(self, text):
        overlay = self.window.contentItem()
        return find(overlay, 'ChoiceRow', text=text)

    def marked(self):
        overlay = self.window.contentItem()
        return [r.property('text') for r in items(overlay) if kind(r).startswith('ChoiceRow') and r.property('checked')]

    def closed(self, w):
        return wait(lambda: not w.sheetVisible(), 3)

    # covers: desktop.design-system/E3
    def test_a_pick_is_marked_at_once_then_the_sheet_closes(self):
        w = self.open_sheet()
        self.assertEqual(self.marked(), ['System'])
        light = self.choice('Light')
        self.tap(light)
        tapped = time.monotonic()
        self.assertEqual(w.pickedList(), 'light')
        self.assertEqual(self.marked(), ['Light'], 'the tapped choice is marked at once')
        self.assertTrue(w.sheetVisible(), 'and still shown')
        # A second tap while it closes changes nothing.
        self.tap(self.choice('Dark'))
        self.assertEqual(w.pickedList(), 'light')
        self.assertEqual(self.marked(), ['Light'])
        self.assertTrue(wait(lambda: not w.sheetOpen(), 2))
        self.assertGreaterEqual(time.monotonic() - tapped, 0.25, 'shown chosen for a moment first')
        self.assertTrue(self.closed(w))

    # covers: desktop.design-system/E3
    def test_the_scrim_closes_without_a_choice(self):
        w = self.open_sheet()
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(195, 40))
        self.assertTrue(self.closed(w))
        self.assertEqual(w.pickedList(), '')

    # covers: desktop.design-system/E3
    def test_escape_closes_without_a_choice(self):
        w = self.open_sheet()
        QTest.keyClick(self.window, Qt.Key_Escape)
        self.assertTrue(self.closed(w))
        self.assertEqual(w.pickedList(), '')
        self.assertEqual(self.marked(), [])

    # covers: desktop.design-system/E3
    def test_dragging_it_down_closes_without_a_choice(self):
        w = self.open_sheet()
        top = round(w.sheetY())
        x, start = 195, top + 6           # the handle
        # A short drag lets it spring back; one down most of its height closes it.
        for distance, closes in ((24, False), (min(round(w.sheetHeight() * 0.8), 843 - start), True)):
            QTest.mousePress(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(x, start))
            for dy in range(8, distance + 1, 8):
                QTest.mouseMove(self.window, QPoint(x, start + dy), 10)
            QTest.mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, QPoint(x, start + distance), 10)
            if closes:
                self.assertTrue(self.closed(w))
            else:
                self.assertTrue(wait(lambda: w.sheetOpen() and abs(w.sheetY() - top) < 1), 'a short drag springs back')
        self.assertEqual(w.pickedList(), '')


# ---------------------------------------------------------------- E4: PageStack, its QML side

class PageStackTest(Scene):
    """What PageStack.qml does with a swipe that PageSwipe (C++) reports: here the stand-in's
    signals. Recognising the swipe (three drag distances right before any up or down, the control
    under the finger cancelled, a vertical drag left to the page) is pageswipe.cpp and not tested
    here."""
    STACK = '''PageStack {
        id: stack
        anchors.fill: parent
        initialItem: Rectangle { objectName: "first"; color: "red" }
    }
    Component { id: second; Rectangle { objectName: "second"; color: "blue" } }
    function pushSecond() { stack.push(second) }
    function depth() { return stack.depth }
    function busy() { return stack.busy }
    function swipeActive() { return stack.active }
    function setSwipeBack(on) { stack.swipeBack = on }
    function start() { stack.started() }
    function move(d) { stack.moved(d) }
    function release(d, forward) { stack.released(d, forward) }
    function cancel() { stack.cancelled() }
    function current() { return stack.currentItem.objectName }
    function currentX() { return stack.currentItem.x }
    function belowItem() { return stack.view.get(stack.depth - 2, QQC2.StackView.DontLoad) }
    function belowVisible() { return belowItem().visible }
    function belowX() { return belowItem().x }'''

    def two_pages(self):
        w = self.load(self.STACK)
        self.assertFalse(w.swipeActive(), 'no swipe back from the first page')
        w.pushSecond()
        self.assertTrue(wait(lambda: w.depth() == 2 and not w.busy()))
        self.assertTrue(w.swipeActive())
        return w

    def test_the_page_follows_the_finger_and_the_one_below_comes_back(self):
        w = self.two_pages()
        w.start()
        self.assertTrue(w.belowVisible(), 'the page below is shown while swiping')
        self.assertAlmostEqual(w.belowX(), -390 * 0.3)
        for distance in (40, 120, 260):
            w.move(distance)
            self.assertEqual(w.currentX(), distance)
            self.assertAlmostEqual(w.belowX(), -390 * 0.3 * (1 - distance / 390))

    def test_let_go_moving_right_goes_back(self):
        w = self.two_pages()
        w.start()
        w.move(120)
        w.release(120, True)
        self.assertTrue(wait(lambda: w.depth() == 1))
        self.assertEqual(w.current(), 'first')
        self.assertEqual(w.currentX(), 0)
        self.assertFalse(w.swipeActive(), 'nothing to go back to')

    def test_let_go_moving_left_stays(self):
        for distance, forward, how in ((300, False, 'last movement to the left'), (0, True, 'never moved right'),
                                       (200, None, 'cancelled')):
            with self.subTest(how=how):
                w = self.two_pages()
                w.start()
                w.move(distance)
                if forward is None:
                    w.cancel()
                else:
                    w.release(distance, forward)
                self.assertTrue(wait(lambda: w.currentX() == 0 and not w.belowVisible()))
                self.assertEqual((w.depth(), w.current()), (2, 'second'))
                self.assertTrue(wait(lambda: w.swipeActive()), 'and can be swiped again')
                self.tearDown()

    def test_a_page_with_its_own_horizontal_drags_turns_the_swipe_off(self):
        w = self.two_pages()
        w.setSwipeBack(False)
        self.assertFalse(w.swipeActive())

    def test_alt_left_goes_back(self):
        """Android's right-edge back (docs/46, desktop.edge-back/E3)."""
        w = self.two_pages()
        QTest.keyClick(self.window, Qt.Key_Left, Qt.AltModifier)
        self.assertTrue(wait(lambda: w.depth() == 1))


# ---------------------------------------------------------------- E5: contrast in every state

def theme_colours(look):
    """Theme.qml's colours in a look ('dark' or 'light'), read from the file."""
    text = (design_gallery.QML / 'Theme.qml').read_text()
    pick = 0 if look == 'dark' else 1
    return {name: tuple(int(c[pick][i:i + 2], 16) / 255 for i in (1, 3, 5))
            for name, *c in re.findall(r'property color (\w+): dark \? "(#[0-9a-f]{6})" : "(#[0-9a-f]{6})"', text)}


class ContrastTest(Scene):
    """WCAG 2.2: words 4.5:1 (SC 1.4.3), the marks that show a control and its state 3:1 (SC 1.4.11),
    each against what is painted under it, measured on the state gallery's controls (every state
    forced, light and dark). Disabled controls are exempt from both criteria; theirs only has to be
    fainter than the enabled state's, so the state reads as off."""

    def gallery(self, look):
        self.engine = QQmlApplicationEngine()
        self.engine.addImportPath(str(self.base / 'qml'))
        self.engine.setInitialProperties({'initialTheme': look, 'section': ''})
        self.engine.load(QUrl.fromLocalFile(str(self.base / 'qml/com/rungic/design/Gallery.qml')))
        self.window = self.engine.rootObjects()[0]
        self.assertTrue(wait(lambda: self.window.isExposed()))
        QTest.qWait(600)        # colour and size behaviours settle
        return self.window

    @staticmethod
    def chain(item):
        while item is not None:
            yield item
            item = item.parentItem()

    def ground(self, item):
        """The colour painted under `item`: its ancestors' fills and their controls' backgrounds,
        over the window's colour."""
        layers = []
        for above in list(self.chain(item))[1:]:
            painted = []
            if above.metaObject().indexOfProperty('background') >= 0:
                background = above.property('background')
                if background is not None and kind(background).startswith('QQuickRectangle'):
                    painted.append(background)
            if kind(above).startswith(('QQuickRectangle', 'ListGroup')):
                painted.append(above)
            for layer in painted:
                colour = layer.property('color')
                if colour.alphaF() > 0:
                    layers.append((rgb(colour), colour.alphaF() * layer.opacity()))
        colour = rgb(self.window.property('color'))
        for top, alpha in reversed(layers):
            colour = over(top, alpha, colour)
        return colour

    def ink(self, item, colour, ground=None):
        opacity = colour.alphaF()
        for above in self.chain(item):
            opacity *= above.opacity()
        ground = ground or self.ground(item)
        return contrast(over(rgb(colour), opacity, ground), ground)

    @staticmethod
    def state(item):
        for above in ContrastTest.chain(item):
            if above.metaObject().indexOfProperty('visualState') >= 0:
                return str(above.property('visualState'))
        return ''

    def measure(self, look):
        """[(ratio, 'text' | 'mark', state, what)] for the words and marks of the gallery's controls."""
        w = self.gallery(look)
        out = []
        for item in items(w.contentItem()):
            if not shown(item):
                continue
            parent = kind(item.parentItem()) if item.parentItem() else ''
            if parent.startswith(('Variant', 'Section')):
                continue        # the gallery's own labels, not a control's
            if any(kind(a).startswith('Section') and a.property('name') == 'Icon colours' for a in self.chain(item)):
                continue        # icons in sample colours on a fixed ground, to see Icon's colouring
            name, state = kind(item), self.state(item)
            if name in ('QQuickText', 'QQuickTextInput') and item.property('text'):
                out.append((self.ink(item, item.property('color')), 'text', state, item.property('text')))
            elif name.startswith('Icon_QMLTYPE') and item.property('name'):
                out.append((self.ink(item, item.property('color')), 'mark', state, 'icon ' + item.property('name')))
            elif name.startswith('RadioMark'):
                out.append((self.ink(item, QQmlProperty.read(item, 'border.color')), 'mark', state, 'radio mark'))
            elif name.startswith('Toggle_QMLTYPE'):
                track = item.property('track')
                ground = self.ground(item)       # under the switch, not its own track
                if state.endswith('on'):
                    out.append((self.ink(item, track, ground), 'mark', state, 'switch track'))
                else:
                    on_track = over(rgb(track), track.alphaF(), ground)
                    edge = item.property('knobEdge')
                    out.append((self.ink(item, edge, on_track), 'mark', state, 'switch knob edge'))
        return out

    # covers: desktop.design-system/E5
    def test_words_and_marks_of_every_enabled_state_stand_out(self):
        for look in ('light', 'dark'):
            with self.subTest(look=look):
                measured = self.measure(look)
                kinds = {what for _, _, _, what in measured}
                self.assertGreater(len(measured), 150, 'the gallery shows its controls')
                self.assertTrue({'radio mark', 'switch track', 'switch knob edge', 'Read answers aloud'} <= kinds)
                failing = [f'{r:.2f} {what!r} ({state})' for r, what_kind, state, what in measured
                           if not state.startswith('disabled') and r < (4.5 if what_kind == 'text' else 3.0)]
                self.assertEqual(failing, [])
                self.tearDown()

    # covers: desktop.design-system/E5
    def test_disabled_reads_fainter_than_enabled(self):
        for look in ('light', 'dark'):
            with self.subTest(look=look):
                measured = self.measure(look)
                enabled = {}
                for r, _, state, what in measured:
                    if not state.startswith(('disabled', 'pressed')):
                        enabled[what] = max(r, enabled.get(what, 0))
                compared = [(what, r, enabled[what]) for r, _, state, what in measured
                            if state.startswith('disabled') and what in enabled]
                self.assertGreater(len(compared), 10)
                self.assertEqual([c for c in compared if c[1] >= c[2]], [])
                self.tearDown()

    # covers: desktop.design-system/E5
    def test_theme_tokens_keep_their_documented_contrast(self):
        """Theme.qml's promise: every text colour 4.5:1 on all four grounds, faint 3:1; the inks
        on the strong and negative fills 4.5:1; the focus ring (link) 3:1."""
        for look in ('light', 'dark'):
            c = theme_colours(look)
            for ground in ('background', 'side', 'fill', 'fill2'):
                for ink in ('text', 'dim', 'link', 'negative', 'positive'):
                    with self.subTest(look=look, ink=ink, ground=ground):
                        self.assertGreaterEqual(contrast(c[ink], c[ground]), 4.5)
                with self.subTest(look=look, ink='faint', ground=ground):
                    self.assertGreaterEqual(contrast(c['faint'], c[ground]), 3.0)
            self.assertGreaterEqual(contrast(c['strongInk'], c['strong']), 4.5)
            self.assertGreaterEqual(contrast(c['negativeInk'], c['negative']), 4.5)


class GalleryPictureTest(unittest.TestCase):
    # covers: desktop.design-system/E5
    def test_the_state_gallery_renders_offline_in_both_looks(self):
        from PySide6.QtGui import QImage
        with tempfile.TemporaryDirectory() as out:
            subprocess.run([sys.executable, str(ROOT / 'tools/design_gallery.py'), 'local', out, '--section', 'ToggleRow'],
                           check=True, capture_output=True, timeout=120)
            light, dark = (QImage(str(Path(out) / f'01-{look}.png')) for look in ('light', 'dark'))
            self.assertFalse(light.isNull() or dark.isNull())
            self.assertTrue((Path(out) / 'sheet.png').exists())
            # Each look on its own ground (Theme.background).
            self.assertEqual(light.pixelColor(2, 2).name(), '#ffffff')
            self.assertEqual(dark.pixelColor(2, 2).name(), '#141618')


if __name__ == '__main__':
    unittest.main()
