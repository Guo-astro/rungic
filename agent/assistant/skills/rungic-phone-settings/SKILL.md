---
name: rungic-phone-settings
description: >-
  Read and change Android device functions from Linux.
  They include battery, CPU, memory, storage, network and display.
  They also include brightness, orientation, vibration, the clipboard and Android settings panels.
  Send a notification to the user. Explain screen recording.
  Use when the user asks about the phone's state or settings, for example 电量, 存储, 亮度, 剪贴板, 横屏, 蓝牙 or 录屏.
  Also use when a task needs one of these values.
---

# Phone status and settings

Run all commands as the desktop user inside the Linux container.
Commands return JSON unless stated otherwise.

## When to use this skill

- "还剩多少电", "存储满了吗", "内存够吗", "网络是什么".
- "屏幕太暗了", "横屏", "copy this", "剪贴板里是什么".
- "打开蓝牙", "turn on Bluetooth": open the settings panel. The user changes the setting there.
- "录屏", "record the screen".
- A task needs a value of the phone, or you must tell the user something while they do not look at the chat.

## Android device functions

Use `rungic-platform --request '<json>'`.
The Android hosting app must be in the foreground to answer.
The error “请先返回 Plasma Mobile” means the user left that app.

| Request | Effect |
|---|---|
| `{"op":"status"}` | Android device status summary. |
| `{"op":"network-get"}` | Wi-Fi/mobile network state. |
| `{"op":"display-get"}` | Display modes, refresh rate, render size. |
| `{"op":"brightness-get"}` / `{"op":"brightness","value":0.5}` | Read/set brightness. Range 0.02-1. A value of -1 selects system control. |
| `{"op":"clipboard-get"}` / `{"op":"clipboard-set","text":"..."}` | Read/set Android clipboard. |
| `{"op":"orientation","mode":"portrait"}` | Select `system`, `portrait`, or `landscape`. |
| `{"op":"vibrate"}` | Short vibration. |
| `{"op":"settings","target":"network"}` | Open an Android settings panel: `network`, `bluetooth`, `display`, `sound`, `datetime`, `location`. |

Read battery, CPU, memory, and storage from Linux.
Use `upower -d`, `free -h`, `df -h /`, and `/sys/class/power_supply/*`.

## Notifications

Notify the user in their language with `rungic-user notify-send "Title" "Text"`.
Plain `notify-send` remains in your workspace, where the user does not read it.

## Screen recording

The quick-settings “录屏” button records the phone and the TV when casting.
It uses hardware H.264 and saves files in `~/Videos`.
There is no command-line trigger.
Direct the user to the button.

## Authorization rules

Ask before changing brightness, orientation, or casting unless the user requested the change.
Do not uninstall apps, remove user files, or change system configuration without an explicit request.

For TV casting settings (`cast-desktop`, `cast-controls`), read the `rungic-screens` skill.
