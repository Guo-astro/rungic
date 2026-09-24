---
name: moto-phone-desktop
description: Operate this phone's Linux desktop (KDE Plasma Mobile on Android) and Android-side device functions - brightness, clipboard, orientation, vibration, network/display info, Android settings panels, TV casting, screen recording, GUI apps via AT-SPI, KWin windows and screenshots. Use whenever a request is about the phone, the desktop, apps on screen, or the TV.
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

## Desktop windows and screenshots

- Windows with output and geometry: `moto-a11y windows`.
- Screenshot of everything: `spectacle -b -n -f -o /tmp/shot.png` (use `-m` for the active screen). Look at the image to understand what is on screen.
- Launch an app: `kstart --application <desktop-file-id>` (IDs: `ls /usr/share/applications ~/.local/share/applications /var/lib/flatpak/exports/share/applications`), or `xdg-open <file-or-url>`.
- Send a notification: `notify-send "标题" "内容"`.

## Operating GUI apps (AT-SPI)

1. `moto-a11y enable` (accessibility is off by default for performance; apps started before enabling may need a restart).
2. `moto-a11y apps` -> `moto-a11y find APP --name '正则' [--role 'push button']` -> path like `0/2/5`.
3. `moto-a11y act APP PATH` presses/activates; `moto-a11y text APP PATH '文字'` sets text.
4. Paths change after the UI changes: find again after each action.
5. `moto-a11y disable` when done.

## Screen recording

The quick-settings "录屏" button records the phone and, if cast, the TV (hardware H.264, files in `~/Videos`). There is no command-line trigger; tell the user to use the button.

## Rules

- Ask before changing brightness/orientation or casting state unless the user asked for it.
- Do not uninstall apps, delete user files or change system configuration without an explicit request.
