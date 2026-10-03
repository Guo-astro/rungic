# SPDX-License-Identifier: MIT
"""The contracts of the Android interfaces (quality/contracts/*.json, quality/README.md 分层).

A contract lists an interface's queries with an example reply each: every key of the example is
required in a real reply, with the example value's type (null: anything). The same contract checks
both ends: Android's provider on the phone (validate() on its real replies, tools/rungic_acceptance.py)
and the Linux consumers, run against StandIn, a socket that answers as the contract says.

  with StandIn('platform-bridge') as bridge:          # $RUNGIC_PLATFORM_SOCKET for the consumer
      os.environ['RUNGIC_PLATFORM_SOCKET'] = bridge.path
      ...                                              # bridge.requests: what the consumer asked
"""
import json
import os
import socket
import tempfile
import threading
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[1] / 'quality/contracts'


def load(name):
    return json.loads((CONTRACTS / f'{name}.json').read_text())


def kind(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, (int, float)):
        return 'number'
    return {str: 'string', list: 'array', dict: 'object'}.get(type(value), type(value).__name__)


def validate(example, reply, where='reply'):
    """The ways `reply` breaks the contract that `example` stands for ([] when it keeps it)."""
    problems = []
    if not isinstance(reply, dict):
        return [f'{where}: not an object but {kind(reply)}']
    for key, value in example.items():
        if key not in reply:
            problems.append(f'{where}.{key}: missing')
        elif value is not None and kind(reply[key]) != kind(value):
            problems.append(f'{where}.{key}: {kind(reply[key])}, not {kind(value)}')
        elif isinstance(value, dict):
            problems += validate(value, reply[key], f'{where}.{key}')
    return problems


def query(contract, request):
    """The contract's query matching a request (its op and no other fields), or None."""
    for q in contract['queries']:
        if q['request'] == request:
            return q
    return None


class StandIn:
    """The interface as its contract describes it, on a Unix socket of its own: each known query is
    answered with its example (or `replies[name]`, which must keep the contract), anything else with
    an error, as the provider does. Records every request."""

    def __init__(self, name, replies=None):
        self.contract = load(name)
        self.replies = replies or {}
        for qname, reply in self.replies.items():
            q = next(q for q in self.contract['queries'] if q['name'] == qname)
            problems = validate(q['reply'], reply)
            if problems:
                raise ValueError(f'a stand-in reply breaks the contract: {problems}')
        self.requests = []
        self.dir = tempfile.TemporaryDirectory(prefix='rungic-standin-')
        self.path = os.path.join(self.dir.name, f'{name}.sock')
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(8)
        self.thread = threading.Thread(target=self.serve, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.close()
        self.dir.cleanup()

    def answer(self, request):
        q = query(self.contract, request)
        if not q:
            return {'error': f'unknown request {request.get("op")!r}'}
        return self.replies.get(q['name'], q['reply'])

    def serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                line = conn.makefile('rb').readline()
                try:
                    request = json.loads(line)
                except ValueError:
                    request = {'invalid': line.decode(errors='replace')}
                self.requests.append(request)
                conn.sendall((json.dumps(self.answer(request)) + '\n').encode())
