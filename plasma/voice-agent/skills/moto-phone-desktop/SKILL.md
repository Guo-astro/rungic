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

## WeChat (微信) on screen

WeChat exposes its controls; use these names instead of guessing (English UI names):

- Layout: a narrow window hides the chat list and its search box. On the TV WeChat opens desktop-sized; if the chat list (`list 'Chats'`) is missing, `desktop_window ... maximize` first.
- Open a chat: type into the text field named `Search` at the top of the chat list, then choose the person under `Contacts` in the results popup (or click the item in `list 'Chats'`, whose name starts with the chat's name, e.g. `File Transfer`). The navigation-bar button `Search` is WeChat's web search (搜一搜), not contact search.
- Names the user SAID are unreliable: speech recognition picks characters of the same sound (周凯文 for 周楷雯). Never search by the recognized characters. Call `desktop_find_name {"name": "<as heard>"}` for `search_text` (the pinyin, e.g. `zhoukaiwen`; WeChat searches pinyin), type that into `Search`, then call `desktop_find_name` again and take the match with `section` `Contacts` (score 1.0 = same sound, 0.9 = accent-type difference). Ignore `Internet search results`. If two different people score 0.9 or more, or none does, ask the user (say the names you found).
- The message box is the editable text named after the open chat (e.g. `周楷雯`). ENTER there sends. Check the chat header name first, and never type into it unless the goal is to send that text to that chat.
- In a chat: `Voice Call` (chat header), `Send Voice`, `Send File`, `Send`, `Chat Info`. `Voice Input (Hold Ctrl+Super)` is speech-to-text, not a voice message.
- Test on `File Transfer` (文件传输助手, messages go to the user's own devices), never on a real contact.

## Voice messages on the user's behalf (语音代发)

When the user asks you to send a voice message (发语音, 用语音告诉…):

1. `desktop_launch` the chat app and open the chat by the SOUND of the name (see the WeChat section: `desktop_find_name`, pinyin search, pick under `Contacts`). Check the chat header shows that contact before sending. When you tell the user whom you sent it to, use the contact's real name (e.g. "发给了周楷雯").
2. The content is what the user asked to say. Begin it with a short note that the assistant sends it for the user, e.g. `我是凯文的 AI 助理，替他发一条语音：……`. Do not add anything the user did not ask for.
3. `desktop_voice_message {"text": ..., "start": "Send Voice", "finish": "Send voice message", "cancel": "Cancel"}` (WeChat). The tool switches only this app's microphone to the Linux microphone for the recording and back afterwards; the user's real microphone is never sent. For apps where you hold a button to talk, pass `"hold": true` and only `start`.
4. Report that it was sent (the tool returns the length) and to whom.

## Calls on the user's behalf (通话代理)

When the user asks you to call someone for a purpose ("帮我给张三打个微信电话，问他…"), or, during a call they are in, says "你来接" / "你来跟他说":

1. Placing a call: open the chat by the SOUND of the name (WeChat section above) and check the chat header. Do NOT click `Voice Call` yourself.
2. `moto-voice-agent --start-call '{"contact": "<the contact's real name>", "goal": "<what to find out or tell, in the user's words, and what must be confirmed with them first>", "dial": "Voice Call"}'`
   It first sets up the call assistant (audio routing, voice session), then dials: it brings the chat whose header is that contact to the front, lets the executor (JEV) start a voice call there, and counts the call as placed only when WeChat opens its call audio. The reply says `"dialed": true` only then; with `false` the call was NOT placed (see `reason` / `jev_actions`): tell the user so, never claim a call is running. The contact's chat must be open (step 1).
   Taking over a call that is already going: the same without `dial`, with `"incoming": true` if the other side called.
   The call assistant then talks: it introduces itself as the user's AI assistant, sends questions it may not decide to the user, relays their answers, hangs up at the end and reports a summary in this chat. The app's microphone and speaker are switched to the Linux devices only for the call.
3. Tell the user in one sentence that the assistant is on the call; while it is, what they say goes to the call assistant (the other side does not hear it), and the chat has 旁听 / 我来接 / 挂断 buttons. After 我来接 the user talks on the phone themselves and this assistant is paused until the call ends. `moto-voice-agent --call-command take-over|hang-up|monitor-on|monitor-off` does the same.
4. Never call anyone the user did not ask you to call.

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
