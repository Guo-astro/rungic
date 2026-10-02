#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run against a built native wrapper; no device, network, model or GUI access."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time


def identity(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].strip().split()[19]


def main(binary):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        leases = root / 'rungic-task-leases'
        leases.mkdir()
        worker = root / 'worker.py'
        worker.write_text('''import json,sys,subprocess,time,os
from pathlib import Path
for line in sys.stdin:
 o=json.loads(line)
 if o.get('method')=='tools/call':
  if os.environ.get('PROBE_STUBBORN')=='1':
   child=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready",flush=True);time.sleep(30)'],stdout=subprocess.PIPE,text=True)
   assert child.stdout.readline().strip()=='ready'
  else: child=subprocess.Popen(['sleep','30'])
  Path(os.environ['PROBE_MARKER']).write_text(json.dumps([os.getpid(),child.pid]))
  if os.environ.get('PROBE_CRASH')=='1': os._exit(1)
  child.wait()
 elif 'id' in o: print(json.dumps({'jsonrpc':'2.0','id':o['id'],'result':{}}),flush=True)
''')
        unrelated = subprocess.Popen(['sleep', '30'])
        try:
            for mode in ('notification', 'lease', 'stubborn_notification', 'stubborn_lease', 'worker_exit', 'denied'):
                task = f'task_{mode}'
                lease = leases / f'{task}.json'
                marker = root / f'{mode}.marker'
                if mode != 'denied':
                    lease.write_text(json.dumps({'taskId': task, 'exclusive': True,
                                     'pid': os.getpid(), 'startTime': identity(os.getpid())}))
                process = subprocess.Popen([binary, '--task', task, '--', sys.executable, str(worker)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env={**os.environ, 'XDG_RUNTIME_DIR': directory, 'PROBE_MARKER': str(marker),
                         'PROBE_STUBBORN': str(int(mode.startswith('stubborn') or mode=='worker_exit')),
                         'PROBE_CRASH': str(int(mode=='worker_exit'))}, text=True)
                def send(message):
                    process.stdin.write(json.dumps(message) + '\n');process.stdin.flush()
                def reply():
                    assert select.select([process.stdout], [], [], 3)[0], 'wrapper did not reply'
                    return json.loads(process.stdout.readline())
                try:
                    send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})
                    assert reply()['id'] == 1
                    send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'run'}})
                    if mode == 'denied':
                        assert reply()['result']['isError'] and not marker.exists()
                    else:
                        deadline = time.monotonic() + 3
                        while not marker.exists() and time.monotonic() < deadline:
                            time.sleep(0.01)
                        assert marker.exists(), 'worker did not start'
                        started = time.monotonic()
                        if 'lease' in mode: lease.unlink()
                        elif mode!='worker_exit': send({'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': {'requestId': 2}})
                        assert reply()['result']['isError']
                        elapsed = time.monotonic() - started
                        assert elapsed < 1.5
                        for pid in json.loads(marker.read_text()):
                            stat = Path(f'/proc/{pid}/stat')
                            while stat.exists() and stat.read_text().rsplit(')', 1)[1].strip().split()[0] not in ('Z','X') and time.monotonic()-started<1.5:
                                time.sleep(.005)
                            assert not stat.exists() or stat.read_text().rsplit(')', 1)[1].strip().split()[0] in ('Z', 'X'), 'task-owned process still running'
                        assert unrelated.poll() is None, 'unrelated user process was killed'
                        print(f'{mode}: task process group stopped in {elapsed*1000:.1f} ms; unrelated process alive')
                finally:
                    process.stdin.close();process.wait(timeout=3)
            print('No-lease tool request rejected; all native worker probes passed')
        finally:
            unrelated.terminate();unrelated.wait()


if __name__ == '__main__':
    main(sys.argv[1])
