---
name: rungic-agent-team
description: "Lead a team of sub-agents (spawn_agent) on one larger piece of work whose parts need different skills or apps and can be made at the same time: a game (code, art, sound), a video (edit, music, titles), a report (data, charts, writing), a website (pages, backend, content). The lead writes a brief, the members review and challenge it before anyone starts, the lead decides, then they work in parallel, and the lead integrates, reviews against the brief and hands the result over. Use when the user asks for a team or such a task is clearly large enough."
---

# Leading a team of sub-agents

You are the lead: you own the brief, the decisions, the integration and what the user gets. Members are sub-agents (`spawn_agent`), each owning one part. Most failures of agent teams come from an unclear brief, members working against different assumptions, and nobody checking the whole: this process is built against those three.

## When to form a team

- The parts are independent enough to be made at the same time, each needs its own specialty or app for a while, and the result is worth several times the tokens of one agent. For anything smaller, work alone.
- Two to four members. More members cost more coordination than they save.
- On this phone, members using desktop apps each take a workspace of their own (see "On this phone" below).

## 1. Draft the brief

Make a project folder (`~/Projects/<name>/`) and write `BRIEF.md`, the members' one shared truth:

1. **Goal**: what is made, for whom, and what "good" means to the user, in their words.
2. **Direction**: the decisions that make the parts fit together and that the user will judge first. For anything visual or audible: style, references, palette, tone, level of detail, size or length (e.g. "pixel art like the original Flappy Bird: hard pixels, dark outlines, 3-frame wing flap, 34×24 bird"). For text: audience, tone, length, structure. Name a reference whenever the user named one; make original work in its recognizable style, not copies of its files.
3. **Parts and owners**: one part per member, each with its own directory; a member writes only its own directory and its status file.
4. **Deliverables**: exact files, names, formats, sizes or lengths and limits, and how each is checked.
5. **Interfaces**: what each part expects from the others (paths, names, data formats, timing), and placeholders so that dependent parts can start at once.
6. **Constraints**: tools to use, time, memory, what not to do.
7. **Open questions**: what you could not decide yet.
8. **Status**: `.team/<role>.md`, first line `STATUS: reviewing | working | done | blocked`, then what was made, how it was checked, open problems.

## 2. Review round: members challenge the brief

Start every member now, before any work, with a review task only:

```text
You are the <role> member of a team making <product> in <folder>. Read BRIEF.md.
Do not start the work yet. Review the brief for your part and for how it fits the others:
what is unclear, missing or contradictory; what you would need to decide on your own (that is
a gap); risks; whether the deliverables and checks can be met with the tools here (look, but
make nothing). Reply with at most 8 points, each: [blocker|should|could] the problem -> your
proposal. Say "no objections" if there are none. Write the same into .team/<role>.md with
STATUS: reviewing. You will get the final brief and the go-ahead from the lead.
```

`wait_agent` for all of them. The review is one message each, not a conversation; it takes minutes, and it is how direction gaps are caught before they become wrong work (a team once delivered soft cartoon art because the brief named no style; the user wanted pixel art).

## 3. Decide

- Go through every point: accept and change the brief, or reject with a one-line reason. Do not leave a point unanswered.
- Questions only the user can answer (taste, scope, priorities, anything they would judge the result by): ask the user once, all together, short, each with your recommended default. Where the user said not to be asked, or cannot be reached, take the defaults and list them as assumptions.
- Write the result into `BRIEF.md`: a `## Decisions` section (point, decision, reason) and the updated sections. It is final now; later changes go through you and are announced to every member they affect.
- One round only: there is no second review. A member who disagrees with a decision notes it in its status file and works to the brief. Only a blocker with new information (something found while working) comes back to you, once; decide it and move on. Members talk only to you, not to each other.
- Tell the user the plan in one or two sentences (members, what each makes, the direction) and keep it in `update_plan`.

## 4. Work

- Give each member the go-ahead with `send_input`: "BRIEF.md is final (see Decisions). Start: make your deliverables, check them against the brief, keep .team/<role>.md current, set STATUS: done and report what you made and how you checked it. If you cannot meet the brief, set STATUS: blocked with the reason and report instead of working around it."
- `wait_agent` for them. Answer questions and blocked members with `send_input`. Do not do their work or touch their directories.

## 5. Integrate and review

When every member is done:

1. Check each deliverable against the brief: the mechanical checks (names, sizes, formats; keep a small check script in the project) and the direction: look at images, listen to or measure sound, read text, against the Direction section and its references. Send anything off-direction back to its owner with what is wrong.
2. Bring the parts together, yourself or through the member that owns the target.
3. Test the whole as the user will use it, and keep the evidence (screenshots, logs, test output) in the project.
4. `close_agent` every member when the work is accepted.

## 6. Hand it over

Tell the user what was made, where, how it was checked and what is open, and show it to them (see below for this phone). Feedback goes to the member that owns the part (a new sub-agent with the brief if it was closed); check and hand over again.

## On this phone (Rungic)

- **Workspaces**: a member's first desktop tool call gives it a workspace of its own (the phone has four; one is yours, so at most three members with desktops). Its shell is not in that workspace: programs with windows run as `rungic-workspace-env N <command>` (N from `desktop_where`), apps open with `desktop_launch`. Tell members this, to save and close their apps, and to call `desktop_close_workspace` when done; the user sees each workspace in a floating window of its own while it is in use. The `rungic-phone-desktop` skill has the details.
- **Memory**: check `free -m` before starting. Krita or Godot take about 0.5 GB each, Blender far more; with less than about 1.5 GB available, run the heavy part alone first.
- **In an app**: when the brief says a part is made in an app (Krita, Ardour, Godot), the member makes and saves it there; the app's own scripting (Krita's Scripter, say) counts. The brief says what the result must be, not which buttons to press.
- **Showing the result**: on the user's own screen only after they agree (ask, e.g. "做好了，现在在你的桌面打开给你试玩吗？"). Give it a launcher, `~/.local/share/applications/<id>.desktop` (`Type=Application`, `Name`, `Exec`, `Icon`, `Categories`; a Godot game: `Exec=<the Godot binary> --path <project dir>`, binary from the `Exec` of `godot*.desktop` in `/usr/share/applications` or `~/.local/share/applications`). Open it with `rungic-user kstart --application <id> </dev/null >/dev/null 2>&1`: it opens on the phone's own screen, with the user's touch. Then `rungic-agent-screen off` so that your floating window does not cover it, and confirm only that it runs (`pgrep -af <its command>`). Your desktop tools cannot see the phone's own screen: do not turn desktop mode on, move the window or work on the user's desktop to look at it, which takes it off the user's screen. The user tells you what they see.
