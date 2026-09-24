---
name: moto-phone-desktop
description: Operate this phone's Linux desktop (KDE Plasma Mobile on Android) and Android-side device functions - brightness, clipboard, orientation, vibration, network/display info, Android settings panels, TV casting, screen recording, operating GUI apps (moto-desktop MCP tools: launch, observe, run UI subtasks), windows and screenshots. Use whenever a request is about the phone, the desktop, apps on screen, or the TV.
---

# Phone and desktop control

All commands run as the desktop user inside the Linux container. Output is JSON unless noted.

## Android-side device functions: `moto-platform --request '<json>'`

The Android app that hosts the desktop answers these (it must be in the foreground; an error "请先返回 Plasma Mobile" means the user left the app).

| Request | Effect |
|---|---|
| `{"op":"status"}` | Android device status summary |
| `{"op":"network-get"}` | Wi-Fi / mobile network state |
| `{"op":"display-get"}` | phone display modes, refresh rate, render size |
| `{"op":"brightness-get"}` / `{"op":"brightness","value":0.5}` | read / set screen brightness (0.02-1, -1 = system) |
| `{"op":"clipboard-get"}` / `{"op":"clipboard-set","text":"..."}` | Android clipboard |
| `{"op":"orientation","mode":"portrait"}` | `system`, `portrait` or `landscape` |
| `{"op":"vibrate"}` | short vibration |
| `{"op":"settings","target":"network"}` | open an Android settings panel: `network`, `bluetooth`, `display`, `sound`, `datetime`, `location` |
| `{"op":"cast-desktop"}` / `{"op":"cast-desktop","enabled":true}` | TV desktop state / on-off (a TV must already be connected via Android casting) |
| `{"op":"cast-controls","mode":"touchpad"}` | phone as TV touchpad: `phone`, `touchpad`, `keyboard` |

Battery, CPU, memory and storage come from Linux: `upower -d`, `free -h`, `df -h /`, `/sys/class/power_supply/*`.

## Operating apps on screen: the `moto-desktop` MCP tools (preferred)

Use these tools for anything on screen; they act with ordinary pointer/keyboard input, like the user's own hands.

**Which screen**: when a TV is connected (`desktop_windows` shows `casting: true`), work on the TV (`CAST-1`). The phone (`WL-0`) shows this assistant and must stay undisturbed; use it only when the user asks for the phone.


1. `desktop_windows` - open windows, which is active, on which screen (`WL-0` phone, `CAST-1` TV).
2. `desktop_launch {"app": "系统设置" | "org.kde.dolphin" | "Firefox"}` to start an app (on the TV while casting; `"screen": "phone"` to override). An app already open is brought forward on that screen instead of starting twice, or `desktop_activate {"window_id": ...}` to bring one to the front. The UI tools work on the ACTIVE window.
   - Closing, minimizing, maximizing, restoring or moving a window to the phone/TV: `desktop_window {"window_id": ..., "action": "close"}`. Do not try this through `desktop_run`: the title bar and its buttons belong to the window manager and are not in the app's controls. If `still_open` stays true after close, the app is asking something; observe it.
3. `desktop_observe` (optional) - the active window's controls (role, name, value, state) to plan the step.
4. `desktop_run` - one bounded UI subtask executed by a fast model (JEV):
   `{"goal": "Search System Settings for the query", "verification": ["The search field contains the query", "Results are listed"], "inputs": {"query": "声音"}, "max_actions": 8}`
   - Put every literal text in `inputs`; the executor never invents text.
   - `verification` must be observable in the UI. Split long tasks into several subtasks.
   - Status `SUBTASK_COMPLETE` = done; `NEEDS_AGENT` = look at `final_window` (or a screenshot) and decide the next subtask; `BLOCKED` = no way forward.
   - Before a step that deletes, sends, publishes, pays or changes an account, ask the user to confirm first; never make that the goal of a subtask without their explicit OK.
5. Never start GUI apps from the shell (`firefox &`, `xdg-open`, `kstart`): the window opens on whichever screen is active, usually the phone showing this assistant. Use `desktop_launch`; if it reports no window, check `desktop_windows` once and tell the user instead of retrying other ways. Also prefer these tools over `kill` or similar for apps on screen.
6. Apps without accessibility (some Electron/Flatpak apps, games) show few controls; take a screenshot and tell the user what you see.

## Desktop windows and screenshots (shell)

- Screenshot of everything: `spectacle -b -n -f -o /tmp/shot.png` (use `-m` for the active screen). Look at the image to understand what is on screen.
- To open a URL or file, launch the app with `desktop_launch` and use `desktop_run` (e.g. type into the address bar); `xdg-open` from the shell would open it on the phone.
- Send a notification: `notify-send "标题" "内容"`.
- Low-level AT-SPI tool for debugging only: `moto-a11y` (apps/tree/find/act/text/windows).

## Screen recording

The quick-settings "录屏" button records the phone and, if cast, the TV (hardware H.264, files in `~/Videos`). There is no command-line trigger; tell the user to use the button.

## Rules

- Ask before changing brightness/orientation or casting state unless the user asked for it.
- Do not uninstall apps, delete user files or change system configuration without an explicit request.
