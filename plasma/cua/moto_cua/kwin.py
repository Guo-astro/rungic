"""Window information from KWin (docs/60).

KWin's D-Bus API has no "active window" query. A one-shot KWin script reads
`workspace` and calls back into this process with callDBus, which avoids
reading KWin's journal output as moto-a11y does (seconds instead of ~0.1 s).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from gi.repository import Gio, GLib

INTERFACE = '''
<node><interface name="dev.moto.Cua"><method name="Report"><arg type="s" direction="in"/></method></interface></node>
'''
OBJECT_PATH = '/dev/moto/Cua'

WINDOW_JS = '''
function info(w) {
  if (!w) return null;
  const c = w.clientGeometry, f = w.frameGeometry;
  return {pid: w.pid, caption: w.caption, resource_class: String(w.resourceClass), active: w.active,
    minimized: w.minimized, normal: w.normalWindow, output: w.output ? w.output.name : "",
    client: [c.x, c.y, c.width, c.height], frame: [f.x, f.y, f.width, f.height], id: String(w.internalId)};
}
const wins = workspace.windowList();
const out = {active: info(workspace.activeWindow), windows: []};
for (let i = 0; i < wins.length; i++) if (wins[i].normalWindow) out.windows.push(info(wins[i]));
callDBus("SERVICE", "/dev/moto/Cua", "dev.moto.Cua", "Report", JSON.stringify(out));
'''

CURSOR_JS = '''
const c = workspace.cursorPos;
callDBus("SERVICE", "/dev/moto/Cua", "dev.moto.Cua", "Report", JSON.stringify({x: c.x, y: c.y}));
'''

ACTIVATE_JS = '''
const wins = workspace.windowList();
let done = false;
for (let i = 0; i < wins.length; i++) {
  if (String(wins[i].internalId) === "TARGET") { wins[i].minimized = false; workspace.activeWindow = wins[i]; done = true; }
}
callDBus("SERVICE", "/dev/moto/Cua", "dev.moto.Cua", "Report", JSON.stringify({activated: done}));
'''


class KWin:
    def __init__(self) -> None:
        self.session = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.context = GLib.MainContext.default()
        self.reports: list[str] = []
        node = Gio.DBusNodeInfo.new_for_xml(INTERFACE)
        self.session.register_object(OBJECT_PATH, node.interfaces[0], self._on_call, None, None)
        runtime = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'moto-cua'
        runtime.mkdir(mode=0o700, exist_ok=True)
        self.dir = runtime

    def _on_call(self, connection, sender, path, interface, method, args, invocation):
        self.reports.append(args.unpack()[0])
        invocation.return_value(None)

    def _kwin(self, method: str, path: str, interface: str, args=None):
        return self.session.call_sync('org.kde.KWin', path, interface, method, args, None, 0, 3000).unpack()

    def _script(self, source: str, timeout: float = 3.0) -> dict:
        name = f'motocua{os.getpid()}x{time.monotonic_ns()}'
        script = self.dir / f'{name}.js'
        script.write_text(source.replace('SERVICE', self.session.get_unique_name()))
        self.reports.clear()
        try:
            number = self._kwin('loadScript', '/Scripting', 'org.kde.kwin.Scripting',
                                GLib.Variant('(ss)', (str(script), name)))[0]
            self._kwin('run', f'/Scripting/Script{number}', 'org.kde.kwin.Script')
            deadline = time.monotonic() + timeout
            while not self.reports and time.monotonic() < deadline:
                self.context.iteration(True)
            if not self.reports:
                raise RuntimeError('KWin script did not report')
            return json.loads(self.reports[0])
        finally:
            try:
                self._kwin('unloadScript', '/Scripting', 'org.kde.kwin.Scripting', GLib.Variant('(s)', (name,)))
            except GLib.Error:
                pass
            script.unlink(missing_ok=True)

    def windows(self) -> dict:
        """{'active': window or None, 'windows': [normal windows]}; geometry is global logical."""
        return self._script(WINDOW_JS)

    def cursor(self) -> tuple[float, float]:
        position = self._script(CURSOR_JS)
        return float(position['x']), float(position['y'])

    def activate(self, window_id: str) -> bool:
        return bool(self._script(ACTIVATE_JS.replace('TARGET', window_id)).get('activated'))
