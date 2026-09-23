#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=2.2,<3", "pillow>=11", "perfetto>=0.58", "pandas>=2"]
# ///
# SPDX-License-Identifier: MIT
"""MCP server exposing tools/moto_agent.py to coding agents (stdio transport).

Registered in the workspace .mcp.json. The library functions do the work; this
file only declares tool names, argument schemas and safety annotations.
"""
import json
import sys
from pathlib import Path

# Keep bytecode caches out of tools/ (repository rule: caches live in .work) even
# when a client starts the server without PYTHONPYCACHEPREFIX.
sys.pycache_prefix = sys.pycache_prefix or str(Path(__file__).resolve().parent.parent / '.work/cache/python')
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.mcpserver import Image, MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

import moto_agent  # noqa: E402
import moto_device  # noqa: E402
import build_on_device  # noqa: E402
import moto_trace  # noqa: E402
import moto_trace_report  # noqa: E402

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
ACT = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
server = MCPServer(
    'moto',
    instructions=(
        'Diagnostics for the Moto XT2537-4 phone running Plasma Mobile in an Ubuntu LXC container on Android 16. '
        'Start with device_status; use logs for a merged Android+container+kernel timeline; snapshot saves an '
        'evidence bundle under .work/diag. Architecture and limits: docs/55-agent-native-debugging.md.'),
)


def dump(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=1)


@server.tool(annotations=READ)
def device_status() -> str:
    """Android (APK, wakefulness, thermal, GPU busy/frequency), container (systemd, failed units, KWin and
    plasmashell pid/RSS), desktop (failed user units, KWin renderer) and host bridge state."""
    return dump(moto_agent.status())


@server.tool(annotations=READ)
def logs(since_seconds: float = 300, priority: int = 6, grep: str | None = None,
         sources: list[str] | None = None, scope: str = 'plasma', include_noise: bool = False,
         limit: int = 300) -> str:
    """Merged, time-ordered log lines from Android logcat, the container journal and the kernel.

    priority: syslog level to keep, 3=err 4=warning 6=info 7=debug. grep: case-insensitive regex on tag+message.
    sources: subset of ["logcat", "journal", "kernel"]. scope: "plasma" (desktop APK UID/tags, crash buffers,
    GPU/memory/SELinux kernel lines) or "all" (whole phone). Known harmless noise is counted, not shown,
    unless include_noise. Times are the phone's local time.
    """
    result = moto_agent.logs(since_seconds, tuple(sources or ('logcat', 'journal', 'kernel')), priority,
                             grep, scope, include_noise, limit)
    footer = (f"\n-- {result['total']} entries, {result['truncated']} older truncated, "
              f"noise suppressed: {result['suppressed_noise']}")
    return moto_agent.format_entries(result['entries']) + footer


@server.tool(annotations=READ)
def session_log(lines: int = 200) -> str:
    """Tail of the Plasma session stdout/stderr file (/var/log/plasma/session.log, no timestamps)."""
    return moto_agent.session_log(lines)


@server.tool(annotations=READ)
def crashes(since_seconds: float = 86400) -> str:
    """Android tombstones, container crash/core-dump journal lines and saved container cores."""
    return dump(moto_agent.crashes(since_seconds))


@server.tool(annotations=READ)
def crash_detail(crash_id: str) -> str:
    """Backtrace of a crash listed by `crashes`: an Android tombstone ("tombstone_31"), a container core report
    ("20260923-214119-kalk-32151", gdb backtrace of all threads) or an apport report ("/var/crash/x.crash")."""
    return moto_agent.crash_get(crash_id)


@server.tool(annotations=READ)
def kwin_info() -> str:
    """KWin supportInformation: version, platform, compositing/OpenGL renderer, options, loaded effects."""
    return moto_agent.kwin_info()


@server.tool(annotations=READ)
def host_request(op: str) -> str:
    """Read-only request to the Android host bridge: status, display-get, network-get, capture-info,
    brightness-get, native-stats (Wayland host counters: windows, focus, injected input, presented frames,
    last native error)."""
    return dump(moto_agent.host_request(op))


@server.tool(annotations=READ)
def screenshot() -> list:
    """Capture the phone screen as seen by the user. Returns a 540 px wide JPEG preview; the full-resolution
    PNG path is in the text part."""
    import io
    from PIL import Image as Pil
    path = moto_agent.screenshot()
    with Pil.open(path) as image:
        preview = image.convert('RGB')
        preview.thumbnail((540, 1200))
        buffer = io.BytesIO()
        preview.save(buffer, 'JPEG', quality=80)
    return [f'Full resolution: {path}', Image(data=buffer.getvalue(), format='jpeg')]


@server.tool(annotations=ACT)
def snapshot(label: str = 'manual', since_seconds: float = 300) -> str:
    """Save an evidence bundle (status, full logs, crashes, KWin info, session log, screenshot) to
    .work/diag/<time>-<label>/ on this computer, and return its warnings/errors summary. Changes nothing
    on the phone."""
    result = moto_agent.snapshot(label, since_seconds)
    problems = result.pop('warnings_and_errors')
    text = dump(result)
    if problems:
        text += '\n\nWarnings and errors in the window:\n' + moto_agent.format_entries(problems['entries'])
    return text


@server.tool(annotations=READ)
def ui_apps() -> str:
    """Applications registered on the AT-SPI bus, and KWin's windows with global logical geometry.
    Enables accessibility if it is off (Qt apps then register within ~2 s; it costs some CPU)."""
    if not moto_agent.a11y('state')['enabled']:
        moto_agent.ui_enable(True)
        import time
        time.sleep(2)
    return dump({'apps': moto_agent.a11y('apps'), 'windows': moto_agent.ui_windows()})


@server.tool(annotations=READ)
def ui_find(app: str, role: str | None = None, name: str | None = None, include_hidden: bool = False) -> str:
    """Find UI elements of an application (name from ui_apps, e.g. "plasmashell", "kalk") by AT-SPI role
    ("button", "label", "text", "filler", ...) and/or case-insensitive name regex. Returns path, role, name,
    states, window-relative extents, actions. Paths change when the UI changes: find again after acting.
    Plasma launcher icons are "filler" elements whose child "label" holds the app name."""
    return dump(moto_agent.ui_find(app, role, name, include_hidden))


@server.tool(annotations=ACT)
def ui_press(app: str, path: str, action: str | None = None) -> str:
    """Invoke an element's accessibility action (default: first, normally "Press"). Prefer this over ui_tap."""
    return dump(moto_agent.ui_press(app, path, action))


@server.tool(annotations=ACT)
def ui_tap(app: str, path: str) -> str:
    """Tap the centre of an element through Android touch input, for elements without actions (launcher
    icons, custom keypads). Window position comes from KWin; fails if the element is off screen."""
    return dump(moto_agent.ui_tap(app, path))


@server.tool(annotations=ACT)
def ui_set_text(app: str, path: str, text: str) -> str:
    """Replace the contents of an editable text element."""
    return dump(moto_agent.a11y('text', app, path, text))


@server.tool(annotations=ACT)
def ui_accessibility(enabled: bool) -> str:
    """Turn AT-SPI registration on or off for all applications. Turn it off before performance measurements."""
    return dump(moto_agent.ui_enable(enabled))


@server.tool(annotations=ACT)
def trace(duration_s: float = 10, label: str = 'trace', swipes: int = 0) -> str:
    """Record a system-wide perfetto trace (Android + Plasma container + KGSL GPU) and summarise it.

    swipes: vertical swipes performed during the capture (0 = observe only). KWin FTrace markers are enabled
    for the capture and restored afterwards. Returns host buffer queueing, SurfaceFlinger present intervals,
    KWin Paint/GpuWait/Import durations, CPU % per process, GPU time per process and GPU frequency. The trace
    (.pftrace, open in ui.perfetto.dev) and KGSL text are kept under .work/diag."""
    path = moto_trace.capture(duration_s, label, during=moto_trace.swipes(swipes) if swipes else None)
    return dump(moto_trace_report.analyse(path))


@server.tool(annotations=READ)
def build_status(component: str) -> str:
    """State of an on-phone package build started by tools/build_on_device.py (e.g. "kwin", "plasma-mobile"):
    systemd unit state, progress lines, errors and the produced .debs."""
    return build_on_device.status(component)


@server.tool(annotations=READ)
def trace_report(path: str, start_s: float | None = None, end_s: float | None = None) -> str:
    """Summarise an existing capture (.pftrace path), optionally for a window in seconds from trace start."""
    return dump(moto_trace_report.analyse(Path(path), start_s, end_s))


if __name__ == '__main__':
    try:
        moto_device.transport()
    except moto_device.DeviceError as error:
        print(f'warning: {error}', file=sys.stderr)  # tools report it again when called
    server.run('stdio')
