#!/bin/sh
# Sub-agent probe: the parent spawns two sub-agents, each calls probe_whoami once.
P=~/Projects/subagent-probe
rm -f $P/probe.log $P/procs.log
( while :; do echo "$(date +%T) $(pgrep -f probe_server.py | tr '\n' ' ') | cua: $(pgrep -f 'rungic-cua mcp' | tr '\n' ' ')" >> $P/procs.log; sleep 1; done ) &
sampler=$!
codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check -C $P \
  -c model_reasoning_effort=low \
  -c mcp_servers.rungic-desktop.enabled=false \
  -c 'mcp_servers.probe.command="python3"' \
  -c "mcp_servers.probe.args=[\"$P/probe_server.py\"]" \
  -c 'mcp_servers.probe.env={RUNGIC_WORKSPACE="1"}' \
  -c 'shell_environment_policy.set={RUNGIC_WORKSPACE="1"}' \
  "这是一个子 Agent 实验。请用 spawn_agent 创建两个子 Agent（标签 A 和 B），它们同时运行。每个子 Agent 只做两件事：调用一次 probe_whoami 工具（label 参数填自己的标签），并在 shell 里运行 echo \$RUNGIC_WORKSPACE；然后把这两个结果原样汇报。你自己也调用一次 probe_whoami（label=parent）。等两个子 Agent 都结束后，用一张表列出三方的 server_pid、calls_in_this_process、threadId 和 RUNGIC_WORKSPACE。不要做其他任何事情，不要打开任何程序。" > $P/exec.log 2>&1
echo "== end: $?" >> $P/exec.log
sleep 2; kill $sampler
