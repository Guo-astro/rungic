# Plan two: accessibility tree + OCR + JEV

Not the default. The `rungic-desktop` tools below are listed only after `rungic-cua plan atspi` (and a
restart of the voice assistant); `rungic-cua plan luna` goes back to plan one (screenshots, GPT-6 Luna).
Plan two reads the accessibility tree (AT-SPI) and OCR; a fast executor (JEV) chooses the step. It
needs apps that expose their controls; it does not see apps that do not (some Electron/Flatpak apps,
games).

**Whole tasks: `desktop_goal` (preferred for anything that takes several steps).** Give the goal as the user said it, with every literal value in it, and the app: `{"goal": "在文件传输助手里发一条消息：今晚七点见", "app": "微信"}`. JEV then decides every click, scroll and key from the screen; a writer model types text. Results: `outcome`, `achieved`, `answer` (what the screen shows about the goal), `steps`. Outcome `question`: ask the user `question`, then call again with the same goal and `replies: [{"question": ..., "answer": ...}]`. Ask the user before a goal that sends, pays, deletes or changes an account. Use the step tools below for a single known action or when `desktop_goal` reports it could not finish.


1. `desktop_windows` - open windows, which is active, on which screen (`WL-0` phone, `CAST-1` TV).
2. `desktop_launch {"app": "系统设置" | "org.kde.dolphin" | "Firefox"}` to start an app (on the assistant's screen while it is on: run `rungic-agent-screen on` first if needed; `"screen": "phone"` to override). An app already open is brought forward on that screen instead of starting twice, or `desktop_activate {"window_id": ...}` to bring one to the front. The UI tools work on the ACTIVE window.
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

## WeChat under plan two

- Names the user SAID are unreliable: speech recognition picks characters of the same sound (周凯文 for 周楷雯). Never search by the recognized characters. Call `desktop_find_name {"name": "<as heard>"}` for `search_text` (the pinyin, e.g. `zhoukaiwen`; WeChat searches pinyin), type that into `Search`, then call `desktop_find_name` again and take the match with `section` `Contacts` (score 1.0 = same sound, 0.9 = accent-type difference). Ignore `Internet search results`. If two different people score 0.9 or more, or none does, ask the user (say the names you found).

Voice message: `desktop_voice_message {"text": ..., "start": "Send Voice", "finish": "Send voice message", "cancel": "Cancel"}` (WeChat). The tool switches only this app's microphone to the Linux microphone for the recording and back afterwards; the user's real microphone is never sent. For apps where you hold a button to talk, pass `"hold": true` and only `start`.
