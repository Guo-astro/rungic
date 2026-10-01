# A team of sub-agents

How to lead a team when one task has parts for different desktop apps that can be done at the same time: a small game (code in Godot, art in Krita, sound in Ardour), a video (edit, music, titles). You are the lead: you plan, write the contract, start the members, integrate, test and hand the result to the user. Members are sub-agents (`spawn_agent`); each gets a workspace of its own at its first desktop tool call and works only there (docs/research/91 in the Rungic repository).

## When to form a team

- Only when the parts are independent, each needs its own GUI app for minutes, and the user asked for something of that size. A team uses several times the tokens of one agent; for anything smaller work alone.
- At most three members with desktops: the phone has four workspaces and one is yours. Members that need no desktop (reading, writing code in the shell) do not take one.
- Memory: check `free -m` first. Krita or Godot take about 0.5 GB each, Blender far more; with less than about 1.5 GB available, run the heavy part alone first. Members close their apps when done.

## 1. Plan and contract

Make the project folder, `~/Projects/<name>/`, and write `CONTRACT.md` there before starting anyone. It is the members' only shared truth:

- **Who owns what**: one directory per member (`game/`, `art/`, `audio/`). A member writes only its own directory and its status file; reading the others is fine. Nobody edits another member's files.
- **Deliverables**: for each member the exact files, names, sizes, formats and limits the others depend on (e.g. `art/export/bird_0.png`, 34×24 RGBA PNG; `audio/export/flap.ogg`, Vorbis, ≤0.3 s, peak ≤ −1 dBFS), and how each can be checked.
- **Interfaces**: what the code expects from the assets (paths, frame counts, scale), so the code can start at once with placeholders of the same names and sizes.
- **Status**: `.team/<role>.md`, first line `STATUS: working`, `STATUS: done` or `STATUS: blocked`, then what was made, how it was checked, and open problems.

Tell the user the plan in one or two sentences (members, what each makes) and keep it in `update_plan`.

## 2. Start the members

One `spawn_agent` per member, all before waiting on any. Its message must stand alone; include:

```text
You are the <role> member of a team making <product> in ~/Projects/<name>. Read CONTRACT.md first.
You own <dir>/ and .team/<role>.md; do not change anything else.
Work with the rungic-desktop tools: your first desktop call gives you a workspace of your own
(desktop_where tells its number N). Open apps with desktop_launch. Your shell is not in that
workspace: run any program with windows as `rungic-workspace-env N <command>`.
Make the deliverables in <app> itself, check them against the contract, save, and close the app.
Keep .team/<role>.md current. When done, set STATUS: done, call desktop_close_workspace, and
report what you made and how you checked it. If you cannot meet the contract, set STATUS: blocked
with the reason and report instead of working around it.
```

## 3. While they work

- `wait_agent` for them; meanwhile keep the user informed through `update_plan` (who is done). Do not do their work or touch their directories.
- A member reports blocked or wrong deliverables: answer it with `send_input`, or change the contract and tell every member it affects.
- The user sees each member's workspace in a floating window of its own; if they close one, that member goes on unseen.

## 4. Integrate and test

When every member is done:

1. Check each deliverable against the contract (a small script that checks names, sizes and formats; keep it in the project).
2. Bring the parts together in the owning member's place (e.g. copy `art/export/` and `audio/export/` into `game/assets/`), or send that member the integration with `send_input`, or spawn one integration member.
3. Test it as the user will use it, in a workspace, with the desktop tools: run it, go through the main paths, take screenshots and keep them in the project. Run scripted checks where the app has them (a Godot test scene). Fix problems through the member that owns the part.
4. `close_agent` every member when the work is accepted. Each closed its workspace when done (one that a member reopened for a fix: it closes it again before it reports).

## 5. Hand it to the user

The result runs on the user's own screen only after they agree: ask (e.g. "做好了，现在在你的桌面打开给你试玩吗？") and wait.

- Give it a launcher, `~/.local/share/applications/<id>.desktop` (`Type=Application`, `Name`, `Exec`, `Icon`, `Categories`), so the user can open it again from the app drawer. A Godot game: `Exec=<the Godot binary> --path <project dir>` runs the game, not the editor; take the binary from the `Exec` of `godot*.desktop` in `/usr/share/applications` or `~/.local/share/applications`.
- Open it in the user's session: `rungic-user kstart --application <id> </dev/null >/dev/null 2>&1`. It opens on the phone's own screen, with the user's touch (a tap is a mouse click).
- Then get out of the way: `rungic-agent-screen off` (your workspace's floating window would cover the game). Confirm only that it runs (`pgrep -af <its command>`). Your desktop tools cannot see the phone's own screen: do not turn desktop mode on, move the window or `desktop_where desktop` to look at it, which takes the game off the user's screen (it did on 2026-10-01). The user tells you what they see.
- Tell the user what to try and that they can describe problems; send fixes to the member that owns the part (a new sub-agent if it was closed), test again, and open the new version the same way.

Finally summarize: what was made, where (project folder, launcher), how it was tested, and anything left open.
