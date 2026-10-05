---
name: rungic-screens
description: >-
  Show work on the TV and in the phone's floating windows: TV casting (rungic-cast), the assistant's screen (rungic-agent-screen) and the user's desktop mode (rungic-desktop-mode).
  Use when the user says 投屏, 投到电视, 断开投屏, 助理屏, 桌面模式 or 电脑模式, or wants to see your work on the TV or the phone.
---

# TV, the assistant's screen and desktop mode

Run all commands as the desktop user inside the Linux container.
Commands return JSON unless stated otherwise.

## When to use this skill

- "投屏", "投到电视", "在电视上看", "断开投屏", "cast it to the TV".
- "让我看看你在做什么", "打开助理屏", "把助理屏投到电视", "关掉助理屏".
- "打开桌面模式", "电脑模式", "关掉桌面模式". Use desktop mode only on the user's request.
- A result is better on a big screen. Offer the TV. Do not connect it without a request.

## The two screens

- The assistant's screen (助理屏) is your own workspace as the user sees it.
  It shows in a floating window on the phone.
  The user can pinch it, move it to the edge, or make it full screen.
  A live caption tells what you do.
  The `desktop_*` tools show it while you work there.
- Desktop mode (桌面模式) is the user's own full desktop.
  It is a separate session: workspace 0, with the user's settings and files.
  It shows in a floating window on the phone, or on the TV in computer mode.
  It belongs to the user: start or stop it only on the user's request.
  When it stops, it asks its apps to close. An app with unsaved work stays open.
  Start programs for it with `rungic-workspace-env 0 COMMAND`.

## Assistant's screen and desktop mode commands

Use `rungic-agent-screen on|off|status|tv|notv` for the assistant's screen.
For TV presentation, run `rungic-agent-screen tv` alone.
It selects the assistant's source first and connects a TV if necessary.
`"shown_on": "tv"` establishes the selected destination.
Do not first run `rungic-cast connect`, which would initially present the user desktop.

Use `rungic-desktop-mode on|off|status` for the user desktop only when requested.

In computer mode, the TV shows the user's desktop (desktop mode). `rungic-desktop-mode tv` puts it there, and you work there.
To show your workspace on the TV instead ("把助理屏投到电视", or "投到电视" about what you made there), run only `rungic-agent-screen tv`.
It points the TV at your workspace first. If the phone has no TV connection, it connects the TV. The desktop never shows on the way.
Its JSON (`"shown_on": "tv"`) is the confirmation. Do not make status calls or screenshots to check it.

## TV casting: `rungic-cast`

Casting connects through Wi-Fi Display and creates the second desktop screen, `CAST-1`.
Connect or disconnect when the user requests it, for example “投屏”, “投到电视”, or “断开投屏”.

| Command | Effect |
|---|---|
| `rungic-cast connect` | Connect the last TV. Usually 5-10 s. Up to one minute immediately after disconnection. |
| `rungic-cast connect "<name>"` | Connect a named TV from the scan results. |
| `rungic-cast disconnect` | Stop casting and return windows to the phone. |
| `rungic-cast status` | Report `active_state`, `active.name`, and `reconnecting`. State 2 means connected. |
| `rungic-cast scan` | Scan reachable TVs, about 8 s. |

A failed connection prints `{"error": ...}`.
Run `rungic-cast scan`.
If the TV is absent, report that it is off or its screen-mirroring input does not accept connections.

After a TV drops the connection, the phone reconnects automatically for up to three minutes with `reconnecting: true`.
A user disconnection never triggers automatic reconnection.
This includes the command, quick-settings “投屏” button, and Android casting controls.
The quick-settings button provides the same manual operation.

## TV settings: `rungic-platform`

Use `rungic-platform --request '<json>'`.
The Android hosting app must be in the foreground to answer.

| Request | Effect |
|---|---|
| `{"op":"cast-desktop"}` / `{"op":"cast-desktop","enabled":true}` | Read/set whether a connected TV presents the desktop. Default on. Connect TVs with `rungic-cast`. |
| `{"op":"cast-controls","mode":"touchpad"}` | Phone control mode for TV: `phone`, `touchpad`, `keyboard`. |

## Authorization rules

Ask before casting unless the user requested it.
