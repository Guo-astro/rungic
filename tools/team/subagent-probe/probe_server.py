#!/usr/bin/env python3
"""A stdio MCP server that records who starts it and what each request carries (_meta).
Experiment of 2026-10-01: does each Codex sub-agent get its own server process, and which
thread id reaches the server?"""
import json, os, sys, time

LOG = os.path.expanduser('~/Projects/subagent-probe/probe.log')


def log(**entry):
    entry.update(time=round(time.time(), 3), pid=os.getpid())
    with open(LOG, 'a') as f:
        f.write(json.dumps(entry) + '\n')


log(event='start', ppid=os.getppid(), workspace=os.environ.get('RUNGIC_WORKSPACE'),
    parent=open(f'/proc/{os.getppid()}/cmdline').read().replace('\0', ' ')[:200])
calls = 0
for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    method, mid = msg.get('method'), msg.get('id')
    params = msg.get('params') or {}
    log(event='request', method=method, meta=params.get('_meta'),
        tool=params.get('name'), arguments=params.get('arguments'))
    if mid is None:
        continue
    if method == 'initialize':
        result = {'protocolVersion': params.get('protocolVersion', '2025-06-18'),
                  'capabilities': {'tools': {}}, 'serverInfo': {'name': 'probe', 'version': '1'}}
    elif method == 'tools/list':
        result = {'tools': [{'name': 'probe_whoami', 'description': 'Report which probe server process answered.',
                             'inputSchema': {'type': 'object', 'properties': {'label': {'type': 'string'}}}}]}
    elif method == 'tools/call':
        calls += 1
        text = json.dumps({'server_pid': os.getpid(), 'calls_in_this_process': calls,
                           'threadId': (params.get('_meta') or {}).get('threadId')})
        result = {'content': [{'type': 'text', 'text': text}]}
    else:
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': 'no'}}) + '\n')
        sys.stdout.flush()
        continue
    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': result}) + '\n')
    sys.stdout.flush()
log(event='exit')
