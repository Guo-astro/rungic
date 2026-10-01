# A team of agents in workspaces (docs/research/91, "团队验收")

The acceptance run of 2026-10-01: three `codex exec` members on the phone, each in its own agent
workspace with its desktop tools, sharing one project directory and handing over by the contract.
The lead (Claude on the development host) starts them, watches, and starts the integration.

On the phone (desktop user), with the files of `flappy/` in `~/Projects/flappy-team-run/` and
`flappy/CONTRACT.md` in `~/Projects/flappy-team/`:

    systemd-run --user --collect --unit team-godot sh ~/Projects/flappy-team-run/team-run.sh 2 godot
    systemd-run --user --collect --unit team-art   sh ~/Projects/flappy-team-run/team-run.sh 3 art
    systemd-run --user --collect --unit team-audio sh ~/Projects/flappy-team-run/team-run.sh 4 audio
    sh ~/Projects/flappy-team-run/monitor.sh        # units, .team statuses, logs, memory
    # all three done: the integration, in the game's workspace
    systemd-run --user --collect --unit team-integrate sh ~/Projects/flappy-team-run/team-run.sh 2 integrate
    for n in 2 3 4; do RUNGIC_WORKSPACE=$n rungic-agent-screen on; done   # watch them, one window each

`team-run.sh N ROLE` starts workspace N, marks it busy (rungic-workspace-N.busy: not frozen, not
closed, its window's close button only hides it) and dismissed (its tools do not take the assistant
screen over), and runs `codex exec` with the workspace's environment for its shell and its
`rungic-desktop` MCP server, the prompt `prompt-common.md` + `prompt-ROLE.md`, the log `ROLE.log`.
