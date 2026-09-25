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
| `{"op":"cast-desktop"}` / `{"op":"cast-desktop","enabled":true}` | whether a connected TV shows the Linux desktop (on by default; to connect a TV use `moto-cast`) |
| `{"op":"cast-controls","mode":"touchpad"}` | phone as TV touchpad: `phone`, `touchpad`, `keyboard` |

Battery, CPU, memory and storage come from Linux: `upower -d`, `free -h`, `df -h /`, `/sys/class/power_supply/*`.

## TV casting: `moto-cast`

Casting connects the phone to the TV over Wi-Fi Display; the TV then becomes the desktop's second screen (`CAST-1`). Run it yourself when the user asks to cast or stop casting ("投屏", "投到电视", "断开投屏").

| Command | Effect |
|---|---|
| `moto-cast connect` | connect the TV used last (about 5-10 s; up to a minute if the TV was just disconnected) |
| `moto-cast connect "<name>"` | a specific TV, by name as `moto-cast scan` lists it |
| `moto-cast disconnect` | stop casting; windows return to the phone |
| `moto-cast status` | `active_state` 2 = connected, `active.name`, `reconnecting` |
| `moto-cast scan` | TVs in reach (about 8 s) |

- A failed connect prints `{"error": ...}`: run `moto-cast scan`; if the TV is not listed, it is off or its screen-mirroring input is closed; say so.
- When the TV drops the session by itself, the phone reconnects automatically for up to three minutes (`reconnecting: true`). A disconnect by the user (this command, the quick-settings "投屏" button, Android's cast controls) is never reconnected.
- The quick-settings "投屏" button does the same by hand.

## Operating apps on screen: the `moto-desktop` MCP tools (preferred)

Use these tools for anything on screen; they act with ordinary pointer/keyboard input, like the user's own hands. Every step is decided from **screenshots** (GPT-6 Luna computer use): no accessibility tree and no OCR, so any app works, whatever toolkit it uses.

**Which screen**: your own screen is the **assistant's screen** (`CAST-1`, 1920x1080): the user watches it in a floating window on the phone, or on the TV when one is connected (the same screen either way: nothing moves when it switches). The phone (`WL-0`) shows this assistant and must stay undisturbed; use it only when the user asks for the phone. `moto-agent-screen on|off|status` turns the assistant's screen on or off; the tools below turn it on by themselves, and apps you launch go there.

**Whole tasks: `desktop_goal` (preferred for anything that takes several steps).** Give the goal as the user said it, with every literal value in it, and the app: `{"goal": "在文件传输助手里发一条消息：今晚七点见", "app": "微信"}`. GPT-6 Luna then looks at the screen and decides every click, key and text (it types any language). Results: `outcome` (`done`, `question`, `failed`, `unfinished`, `stopped`), `achieved`, `answer` (what the screen shows about the goal), `steps`. Outcome `question`: ask the user `question`, then call again with the same goal and `replies: [{"question": ..., "answer": ...}]`. Ask the user before a goal that sends, pays, deletes or changes an account, and then say in the goal that it is confirmed.

**Look and act yourself** (a single known step, or checking a result):
- `desktop_screenshot` returns the active window on the assistant's screen as an image (with its open menus and dialogs); `{"scope": "screen"}` for the whole screen (1920x1080).
- `desktop_act {"actions": [...]}` carries out a short batch in that image's pixels and returns the new screenshot. Actions: `{"type": "click", "x": 700, "y": 400}` (`button` left/right, `keys` held modifiers), `double_click`, `move`, `drag` (`path` of points), `scroll` (`x`, `y`, `scroll_y` in pixels, positive = down), `keypress` (`keys`: `["CTRL", "L"]`, `["ENTER"]`), `type` (`text`, any language, into the focused field), `wait`.

**Windows** (the window manager, not the app; same in both plans):
1. `desktop_windows` - open windows, which is active, on which screen (`WL-0` phone, `CAST-1` assistant/TV).
2. `desktop_launch {"app": "系统设置" | "org.kde.dolphin" | "Firefox"}` starts an app on the assistant's screen (`"screen": "phone"` to override); an app already open is brought forward there instead of starting twice. `desktop_activate {"window_id": ...}` brings one to the front.
3. `desktop_window {"window_id": ..., "action": "close" | "minimize" | "maximize" | "restore" | "to_phone" | "to_tv"}`. The title bar belongs to the window manager: close windows this way. If `still_open` stays true after close, the app is asking something: look at it.
4. Never start GUI apps from the shell (`firefox &`, `xdg-open`, `kstart`): the window opens on whichever screen is active, usually the phone showing this assistant. Use `desktop_launch`; if it reports no window, check `desktop_windows` once and tell the user instead of retrying other ways. Also prefer these tools over `kill` or similar for apps on screen.

**Plan two** (accessibility tree + OCR + JEV: `desktop_observe`, `desktop_run`, `desktop_find_name`) is not the default and its tools are not listed unless it was chosen (`moto-cua plan atspi`, then the voice assistant restarts). Only when the user asks for it or it is active: read `plan-two.md` next to this file.

## WeChat (微信) on screen

WeChat exposes its controls; use these names instead of guessing (English UI names):

- Layout: a narrow window hides the chat list and its search box. On the TV WeChat opens desktop-sized; if the chat list (`list 'Chats'`) is missing, `desktop_window ... maximize` first.
- Open a chat: type into the text field named `Search` at the top of the chat list, then choose the person under `Contacts` in the results popup (or click the item in `list 'Chats'`, whose name starts with the chat's name, e.g. `File Transfer`). The navigation-bar button `Search` is WeChat's web search (搜一搜), not contact search.
- Names the user SAID are unreliable: speech recognition picks characters of the same sound (周凯文 for 周楷雯). Never search by the recognized characters: search the pinyin (`zhoukaiwen`; WeChat searches pinyin) and take the contact whose name sounds the same. `desktop_goal` does this by itself when the goal says the name came from speech; its `answer` names the contact actually opened. If two different people fit, or none, ask the user (say the names you found).
- The message box is the editable text named after the open chat (e.g. `周楷雯`). ENTER there sends. Check the chat header name first, and never type into it unless the goal is to send that text to that chat.
- In a chat: `Voice Call` (chat header), `Send Voice`, `Send File`, `Send`, `Chat Info`. `Voice Input (Hold Ctrl+Super)` is speech-to-text, not a voice message.
- Test on `File Transfer` (文件传输助手, messages go to the user's own devices), never on a real contact.

## Voice messages on the user's behalf (语音代发)

When the user asks you to send a voice message (发语音, 用语音告诉…):

1. Open the chat by the SOUND of the name with `desktop_goal` (`{"goal": "在微信里打开和周凯文的聊天（名字来自语音识别，按读音找），不要发送任何内容", "app": "微信"}`; see the WeChat section). Check the chat header in its `answer` shows that contact before sending. When you tell the user whom you sent it to, use the contact's real name (e.g. "发给了周楷雯").
2. The content is what the user asked to say. Begin it with a short note that the assistant sends it for the user, e.g. `我是凯文的 AI 助理，替他发一条语音：……`. Do not add anything the user did not ask for.
3. `desktop_voice_message {"text": ...}` with the chat open on the assistant's screen: the model finds the record control on screen (WeChat: the round "Send Voice" icon right of the message box, not the microphone, which is dictation), the tool speaks once the app records from the Linux microphone, then the model presses send. Only this app's microphone is switched, for the recording; the user's real microphone is never sent. Under plan two the tool takes control names instead (`plan-two.md`).
4. Report that it was sent (the tool returns the length) and to whom.

## Calls on the user's behalf (通话代理)

The call's audio must be switched to the assistant before the call starts; `--start-call` does that first and then dials, so never start a call yourself.

1. Open the chat with the person (`desktop_goal`), so it is the active window on the assistant's screen.
2. `moto-voice-agent --start-call '{"contact": "<name in the chat header>", "goal": "<what to say or find out>", "dial": "Voice Call"}'`: switches WeChat's microphone and speaker to the call assistant, then dials. `"dialed": true` means the call audio opened; otherwise the call was not placed.
   A call already going: the same without `dial` (`"incoming": true` if they called).
3. With `"dialed": true`, tell the user in one sentence that the call assistant is calling, and end your turn: you stay quiet during the call (your speech does not play), the call assistant talks on its own, asks the user when needed, and its summary comes to the chat when the call ends. `moto-voice-agent --call-command take-over|hang-up|monitor-on|monitor-off` for the user's 我来接 / 挂断 / 旁听.

## Desktop windows and screenshots (shell)

- Screenshot of everything: `spectacle -b -n -f -o /tmp/shot.png` (use `-m` for the active screen). Look at the image to understand what is on screen.
- To open a URL or file, launch the app with `desktop_launch` and use `desktop_goal` or `desktop_act` (e.g. type into the address bar); `xdg-open` from the shell would open it on the phone.
- Send a notification: `notify-send "标题" "内容"`.
- Low-level AT-SPI tool for debugging only: `moto-a11y` (apps/tree/find/act/text/windows).

## Screen recording

The quick-settings "录屏" button records the phone and, if cast, the TV (hardware H.264, files in `~/Videos`). There is no command-line trigger; tell the user to use the button.

## Rules

- Ask before changing brightness/orientation or casting state unless the user asked for it.
- Do not uninstall apps, delete user files or change system configuration without an explicit request.
