---
name: rungic-phone-desktop
description: >-
  Operate GUI apps on this phone's Linux desktop (KDE Plasma Mobile on Android) with the rungic-desktop MCP tools.
  Launch apps, click and type, manage windows, take screenshots, and select the screen to work on.
  Use for a task inside a desktop app, for example Firefox, LibreOffice, Dolphin, System Settings or Blender, and to render in Blender.
  For SMS, calls and WeChat, use rungic-messages-calls. For the TV, the assistant's screen and desktop mode, use rungic-screens.
---

# Desktop apps on the phone

Run all commands as the desktop user inside the Linux container.
Commands return JSON unless stated otherwise.

## When to use this skill

- The user asks for work inside a desktop app: "打开…", "在 Firefox 里…", "帮我填这个表", "fill in this form".
- A task needs an app on the screen, or the user wants to watch the work.
- You must take a screenshot, read the screen, or manage windows.
- The user asks for a 3D model or a render in Blender.

Other phone skills:

- `rungic-messages-calls`: SMS, phone calls, WeChat messages and calls.
- `rungic-screens`: TV casting, the assistant's screen, desktop mode.
- `rungic-phone-settings`: Android functions, device status, notifications, screen recording.
- `rungic-agent-team`: a team of sub-agents for a large job.

## Visible apps: `rungic-desktop` MCP tools

Prefer these tools for on-screen work with ordinary pointer and keyboard input.
By default, Codex decides each step from screenshots using its current sign-in.
The tools capture images and execute actions without a separate visual model.
Ordinary desktop work does not require an OpenAI API key.
Speech synthesis and voice services still require that key.
Keep progress and verification in the originating task.

### Select the screen

See docs/research/91.
Results identify the working screen whenever it changes.

- User desktop: use it while desktop mode or TV computer mode exposes that desktop.
  Desktop mode is “桌面模式”, workspace 0 with its own KWin, user settings/files, and floating phone window.
  The user can operate it concurrently.
  Apps open there rather than on the phone's own `WL-0` screen.
  For shell commands there, use `rungic-workspace-env 0 <command>`.
- Otherwise, use the agent workspace, visible as the assistant's screen, “助理屏”.
  It has one 1920x1080 screen, separate KWin, Xwayland, and session bus.
  Apps appear there from their first frame.
  The tools present it automatically, as a floating or fullscreen phone window.
- Use `desktop_where {"target": "desktop" | "workspace" | "auto"}` when the user specifies a screen.
  The choice persists for the conversation.
  Without `target`, it reports the current screen and reason.

To show a screen on the phone or the TV, or for desktop mode, read the `rungic-screens` skill.
The main agent's shell runs in its workspace.
`rungic-user <command>` runs in the user's session, for example a notification.

A sub-agent gets its own workspace at its first desktop tool call.
Its shell remains in the parent's workspace.
Use `desktop_where` to get N, then `rungic-workspace-env N <command>` for its programs.
For example: `rungic-workspace-env N spectacle -b -n -f -o /tmp/shot.png`.
Sub-agents must call `desktop_close_workspace` when finished to release the workspace.

### Complete a task in default Codex mode

1. Launch the app.
2. Call `desktop_screenshot`.
3. Describe the next small action batch in `desktop_act.note`.
4. Execute the batch and inspect the returned image.
5. Continue until the authorized result is visible.

Coordinates are pixels in the latest image.
Take a fresh screenshot after popups, resizing, user takeover, or corrections.
A click or successful tool response does not establish completion.
Stop when the user stops the task.
Ask only for missing information or actions outside existing authorization.

### Optional API mode

`desktop_goal` appears only when the user selected a separate API executor, Luna or the alternate OCR path.
Then you can delegate the full goal with literal values, app, and existing authorization.
Check returned evidence and relay questions.
Do not change modes or silently use API mode after an error.

### Visible progress

The floating window presents captions on the working screen, as docs/88 describes.
`desktop_goal` writes one per step.
For `desktop_act`, supply a short `note` in the user's language.
The system also speaks these progress updates.
Perform desktop-app work visibly there rather than headless.

### Screenshot and action tools

`desktop_screenshot` returns the active window, including menus and dialogs.
Use `{"scope": "screen"}` for the complete 1920x1080 screen.

`desktop_act {"actions": [...], "note": "Open the Render menu"}` executes a short batch and returns a fresh screenshot.
A Chinese note can be `"note": "打开“渲染”菜单"`.
Supported actions are:

- `{"type": "click", "x": 700, "y": 400}`: `button` selects left/right and `keys` holds modifiers.
- `double_click`, `move`.
- `drag`: `path` contains points.
- `scroll`: `x`, `y`, and `scroll_y` in pixels, positive downward.
- `keypress`: `keys`, for example `["CTRL", "L"]` or `["ENTER"]`.
- `type`: `text` in any language, sent to the focused field.
- `wait`.

### Windows: both plans

1. `desktop_windows` lists workspace windows and the active window.
2. `desktop_launch {"app": "系统设置" | "org.kde.dolphin" | "Firefox"}` launches an app on the working screen.
   An existing app window comes to the foreground instead of launching twice.
   Use `args` for a file or options in a new window.
   Examples: `{"app": "Koko", "args": ["/home/…/Pictures/a.png"]}` and `{"app": "Blender", "args": ["--python", "/home/…/make.py"]}`.
   A visible Blender script lets the user watch construction and rendering.
   Use `desktop_activate {"window_id": ...}` to select a window.
3. Use `desktop_window {"window_id": ..., "action": "close" | "minimize" | "maximize" | "restore"}` for window-manager actions.
   Title bars belong to the window manager.
   If `still_open` remains true after close, inspect the app's question.
4. Launch GUI apps with `desktop_launch`, not shell commands.
   It waits for the window, returns its ID, and opens it on the working screen.
   Shell-launched windows appear in your workspace even while you work on the user desktop.
   If launch reports no window, check `desktop_windows` once and report the result.
   Do not retry through other entry points or prefer `kill` for visible apps.

Most apps, including Blender, Kalk, and Dolphin, use independent workspace instances.
If the user has the same file open, save a new file or tell them about your changes.
Nothing locks the shared file.

Unless the caller specifies a profile, Firefox uses a separate profile per workspace.
The wrapper copies user sign-ins and settings into that profile before launch, unless the workspace Firefox already runs.
This transfer is one-way.
Workspace sign-ins do not return to the user profile.
A later launch copies the user state again.
Copy errors do not prevent Firefox from launching.

See docs/research/97 section 19.12.

For WeChat chats, messages and calls, read the `rungic-messages-calls` skill.
Apps with one instance per user, such as WeChat or Telegram, can require moving from the user's phone.
`desktop_launch`, or `desktop_goal` with `app`, returns `needs_confirmation` and a `question`.
Ask that question and wait for agreement.
Only then repeat with `"switch": true`.

The app closes on the phone, opens in the workspace, and automatically returns about two minutes after work ends.
Do not close the user's apps through `kill`, `pkill`, or `desktop_window`.
Never move them during a call: `blocked: in_call`.

Close apps you opened in your workspace when finished, with `desktop_window` close.
Each app consumes phone memory.

### Teams and plan two

For large independent parts requiring different skills/apps, or a requested team, read `rungic-agent-team` before using `spawn_agent`.

Plan two uses accessibility, OCR, and JEV.
Its `desktop_observe`, `desktop_run`, and `desktop_find_name` tools are absent unless selected through `rungic-cua plan atspi`.
Restart the voice assistant after selection.
Read [plan-two.md](plan-two.md) only when the user requests it or it is active.

## Blender

Use Cycles on the CPU, the phone's system default from docs/90.
New scenes use CPU Cycles, with at most half the CPU cores for each render.
Retain both defaults.
Do not select EEVEE, a GPU device, or `--gpu-backend` unless the user requests GPU rendering.
The GPU shares phone memory.
EEVEE used about 0.9 GB more than Cycles in a small scene, and memory previously ran out during rendering.

Use the user's default 512×512 resolution and 64 samples.
This took about 20 s and 0.3 GB here.
`rungic_render` does not yet denoise.
Use larger images, 900 or more, only when requested.
Time grows with pixel count.

Render visibly with the phone's `rungic_render` module rather than `bpy.ops.render.render`:

```python
import rungic_render
rungic_render.render('/home/…/Pictures/篮球.png')   # use the scene's Cycles samples in passes
```

Build the scene before calling the renderer.
For a script executed at startup, use a timer:
`bpy.app.timers.register(lambda: rungic_render.render(path) and None, first_interval=1)`.
Launch it visibly with `desktop_launch {"app": "Blender", "args": ["--python", "/home/…/make.py"]}`.

Rendering uses a background Blender to keep the visible window responsive.
The render window and chat task card present successive passes at 4, 12, 28, and 64 samples.
Wait for `<image>.status.json` with `"phase": "done"` or `"error"` before answering.
For example:
`timeout 600 sh -c 'until grep -q "\"done\"\|\"error\"" /home/…/篮球.png.status.json; do sleep 2; done'`.
Then include the image as `![…](<path>)`.

For “投到电视上看” from your workspace, run only `rungic-agent-screen tv`.
It presents the assistant's screen and render window, connecting if necessary.
From the user desktop, use `rungic-cast connect` instead.
Never close or kill a working Blender because it reports “Not Responding”.
Use the status file to judge progress.

## Shell screenshots and URLs

Use `spectacle -b -n -f -o /tmp/shot.png` for a workspace screenshot.
Inspect the image before interpreting screen state.

Open URLs/files with `desktop_launch`, passing the path/URL in `args`.
Then use `desktop_act`, or `desktop_goal` when available.

Use `rungic-a11y` only for low-level debugging: apps/tree/find/act/text/windows.

## Authorization rules

Do not uninstall apps, remove user files, or change system configuration without an explicit request.
