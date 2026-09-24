"""Pointer and keyboard input through the XDG RemoteDesktop portal (docs/60).

The standard way for a Wayland client to inject input. On KDE the portal
drives KWin's fake-input protocol, so clients get ordinary Wayland pointer and
keyboard events. The xdg-desktop-portal frontend (1.21, check_position) only
accepts absolute pointer positions inside a screen-cast stream of the session;
a stream only for positioning would keep KWin producing video, so the pointer
moves relatively from KWin's cursor position (fake-input motion is not
accelerated). The first Start asks the user on screen; the restore token
(persist_mode 2) keeps the grant afterwards.
"""
from __future__ import annotations

import os
import random
import time
from pathlib import Path

from gi.repository import Gio, GLib

PORTAL = ('org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop')
IFACE = 'org.freedesktop.portal.RemoteDesktop'
KEYBOARD, POINTER = 1, 2
BTN_LEFT, BTN_RIGHT = 0x110, 0x111
TOKEN_FILE = Path.home() / '.local/state/moto-cua/remote-desktop-token'

KEYSYMS = {
    'ENTER': 0xff0d, 'ESCAPE': 0xff1b, 'TAB': 0xff09, 'SPACE': 0x20, 'BACKSPACE': 0xff08, 'DELETE': 0xffff,
    'ARROW_UP': 0xff52, 'ARROW_DOWN': 0xff54, 'ARROW_LEFT': 0xff51, 'ARROW_RIGHT': 0xff53,
    'HOME': 0xff50, 'END': 0xff57, 'PAGE_UP': 0xff55, 'PAGE_DOWN': 0xff56,
    'MINUS': ord('-'), 'EQUAL': ord('='), 'LEFT_BRACKET': ord('['), 'RIGHT_BRACKET': ord(']'),
    'BACKSLASH': ord('\\'), 'SEMICOLON': ord(';'), 'QUOTE': ord("'"), 'COMMA': ord(','), 'PERIOD': ord('.'),
    'SLASH': ord('/'), 'GRAVE': ord('`'),
    'MOD': 0xffe3, 'CTRL': 0xffe3, 'ALT': 0xffe9, 'SHIFT': 0xffe1,
}


def keysym(name: str) -> int:
    if name in KEYSYMS:
        return KEYSYMS[name]
    if len(name) == 1 and name.isalnum():
        return ord(name.lower())
    if name.startswith('F') and name[1:].isdigit():
        return 0xffbe + int(name[1:]) - 1
    raise ValueError(f'Unsupported key {name!r}')


class PortalDenied(RuntimeError):
    pass


class RemoteInput:
    def __init__(self, cursor=None) -> None:
        """`cursor` returns the pointer's current global position (KWin)."""
        self.cursor = cursor
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.context = GLib.MainContext.default()
        self.session: str | None = None
        self.position: tuple[float, float] | None = None
        self._sender = self.bus.get_unique_name()[1:].replace('.', '_')

    # ---- session ------------------------------------------------------------------------
    def _request(self, method: str, args: GLib.Variant, token: str, timeout: float) -> dict:
        """Call a portal method returning a Request and wait for its Response."""
        handle = f'/org/freedesktop/portal/desktop/request/{self._sender}/{token}'
        response: list = []

        def on_response(connection, sender, path, interface, signal, params):
            response.append(params.unpack())

        subscription = self.bus.signal_subscribe(PORTAL[0], 'org.freedesktop.portal.Request', 'Response', handle,
                                                 None, Gio.DBusSignalFlags.NO_MATCH_RULE, on_response)
        try:
            self.bus.call_sync(PORTAL[0], PORTAL[1], IFACE, method, args, None, 0, 10000)
            deadline = time.monotonic() + timeout
            while not response and time.monotonic() < deadline:
                self.context.iteration(True)
        finally:
            self.bus.signal_unsubscribe(subscription)
        if not response:
            raise PortalDenied(f'RemoteDesktop.{method}: no answer (is the permission dialog open on screen?)')
        code, results = response[0]
        if code != 0:
            raise PortalDenied(f'RemoteDesktop.{method} refused (code {code})')
        return results

    def start(self, timeout: float = 60.0) -> None:
        if self.session:
            return
        stamp = f'motocua{os.getpid()}{time.monotonic_ns() % 1000000}'
        results = self._request('CreateSession', GLib.Variant('(a{sv})', ({
            'handle_token': GLib.Variant('s', stamp + 'c'),
            'session_handle_token': GLib.Variant('s', stamp + 's')},)), stamp + 'c', 10)
        session = results['session_handle']
        options = {'handle_token': GLib.Variant('s', stamp + 'd'), 'types': GLib.Variant('u', KEYBOARD | POINTER),
                   'persist_mode': GLib.Variant('u', 2)}
        if TOKEN_FILE.exists():
            options['restore_token'] = GLib.Variant('s', TOKEN_FILE.read_text().strip())
        self._request('SelectDevices', GLib.Variant('(oa{sv})', (session, options)), stamp + 'd', 10)
        results = self._request('Start', GLib.Variant('(osa{sv})', (session, '', {
            'handle_token': GLib.Variant('s', stamp + 't')})), stamp + 't', timeout)
        if results.get('restore_token'):
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_FILE.write_text(results['restore_token'])
            TOKEN_FILE.chmod(0o600)
        self.session = session

    def close(self) -> None:
        if self.session:
            try:
                self.bus.call_sync(PORTAL[0], self.session, 'org.freedesktop.portal.Session', 'Close', None, None, 0,
                                   2000)
            except GLib.Error:
                pass
            self.session = None

    def _notify(self, method: str, signature: str, *args) -> None:
        self.start()
        try:
            self.bus.call_sync(PORTAL[0], PORTAL[1], IFACE, method,
                               GLib.Variant(f'(oa{{sv}}{signature})', (self.session, {}, *args)), None, 0, 3000)
        except GLib.Error:
            # The portal drops sessions (e.g. after a restart); start again once.
            self.session = None
            self.start()
            self.bus.call_sync(PORTAL[0], PORTAL[1], IFACE, method,
                               GLib.Variant(f'(oa{{sv}}{signature})', (self.session, {}, *args)), None, 0, 3000)

    # ---- input ----------------------------------------------------------------------------
    def _step(self, dx: float, dy: float) -> None:
        self._notify('NotifyPointerMotion', 'dd', float(dx), float(dy))

    def glide(self, x: float, y: float) -> None:
        """Move there in a few steps (~0.1 s) instead of jumping, as a hand would."""
        start = self.cursor() if self.cursor else self.position
        if start is None:
            raise RuntimeError('Pointer position unknown')
        steps, done = 6, (0.0, 0.0)
        for i in range(1, steps + 1):
            t = i / steps
            t = t * t * (3 - 2 * t)  # ease in and out
            target = ((x - start[0]) * t, (y - start[1]) * t)
            self._step(target[0] - done[0], target[1] - done[1])
            done = target
            if i < steps:
                time.sleep(0.016 + random.random() * 0.008)
        # KWin's edge barrier holds the pointer ~100 px when it crosses from one
        # screen to another (phone and TV): correct from the actual position.
        for _ in range(3):
            if not self.cursor:
                break
            now = self.cursor()
            if abs(now[0] - x) < 1.5 and abs(now[1] - y) < 1.5:
                break
            self._step(x - now[0], y - now[1])
        self.position = (x, y)

    def click(self, x: float, y: float, *, button: int = BTN_LEFT, count: int = 1) -> None:
        self.glide(x, y)
        time.sleep(0.04 + random.random() * 0.04)
        for i in range(count):
            self._notify('NotifyPointerButton', 'iu', button, 1)
            time.sleep(0.05 + random.random() * 0.04)
            self._notify('NotifyPointerButton', 'iu', button, 0)
            if i + 1 < count:
                time.sleep(0.08 + random.random() * 0.04)

    def press(self, x: float, y: float, *, button: int = BTN_LEFT) -> None:
        """Move there and hold the button down (hold-to-talk controls); see release()."""
        self.glide(x, y)
        time.sleep(0.04 + random.random() * 0.04)
        self._notify('NotifyPointerButton', 'iu', button, 1)

    def release(self, *, button: int = BTN_LEFT) -> None:
        self._notify('NotifyPointerButton', 'iu', button, 0)

    def type_text(self, text: str) -> None:
        """Latin text as individual key events with a typing rhythm."""
        for ch in text:
            sym = ord(ch)  # X keysyms equal Latin-1 code points
            self.key(sym, True)
            time.sleep(0.02 + random.random() * 0.03)
            self.key(sym, False)
            time.sleep(0.03 + random.random() * 0.05)

    def scroll(self, x: float, y: float, direction: str, steps: int = 3) -> None:
        self.glide(x, y)
        axis = 0 if direction in ('UP', 'DOWN') else 1
        delta = -steps if direction in ('UP', 'LEFT') else steps
        self._notify('NotifyPointerAxisDiscrete', 'ui', axis, delta)

    def key(self, sym: int, pressed: bool) -> None:
        self._notify('NotifyKeyboardKeysym', 'iu', sym, 1 if pressed else 0)

    def chord(self, keys: list[str]) -> None:
        syms = [keysym(k) for k in keys]
        for sym in syms:
            self.key(sym, True)
            time.sleep(0.02 + random.random() * 0.02)
        for sym in reversed(syms):
            self.key(sym, False)
            time.sleep(0.01 + random.random() * 0.02)
