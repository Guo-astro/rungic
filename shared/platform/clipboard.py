#!/usr/bin/python3
"""Synchronize plain text through wl-clipboard and the private Android host API.
No clipboard history or content logs. Android access is limited to foreground.
"""
import json, os, signal, socket, subprocess, sys, threading, time

import rungic_host_watch
from pathlib import Path

LIMIT=262144
SOCKET='/mnt/android-wayland/platform.sock'

def request(value):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as c:
        c.settimeout(4);c.connect(SOCKET)
        c.sendall(json.dumps(value,ensure_ascii=False).encode()+b'\n')
        with c.makefile('rb') as f: raw=f.readline(524289)
        if len(raw)>524288:raise ValueError('Response too large')
        result=json.loads(raw)
        if 'error' in result:raise RuntimeError('Host unavailable')
        return result

if len(sys.argv)>1 and sys.argv[1]=='--event':
    state=os.environ.get('CLIPBOARD_STATE','data')
    if state in ('nil','clear'):value=None
    elif state=='data':
        raw=sys.stdin.buffer.read(LIMIT+1)
        if len(raw)>LIMIT:raise SystemExit()
        try:value=raw.decode('utf-8')
        except UnicodeDecodeError:raise SystemExit()
        if len(value)>65536:raise SystemExit()
    else:raise SystemExit()
    print(json.dumps({'text':value},ensure_ascii=False),flush=True)
    raise SystemExit()

# One supervisor per desktop bus; exits with the Wayland compositor.
lock=threading.Lock()
initial=object()
last=initial
stopped=threading.Event()
# The foreground Android clipboard is authoritative when opening a session.
try:
    result=request({'op':'clipboard-get'})
    if result.get('available'):
        last=result['text']
        if last is None:subprocess.run(['wl-copy','--clear'],timeout=2,check=True)
        else:subprocess.run(['wl-copy','--type','text/plain;charset=utf-8'],input=last.encode(),timeout=2,check=True)
except Exception:pass
watch=subprocess.Popen(['wl-paste','--type','text','--watch',sys.argv[0],'--event'],stdout=subprocess.PIPE,text=True)

changed=threading.Event()

def stop(*_):
    stopped.set()
    changed.set()
    watch.terminate()
    signal.signal(signal.SIGTERM,signal.SIG_DFL)

signal.signal(signal.SIGTERM,stop)
signal.signal(signal.SIGINT,stop)

def from_linux():
    global last
    for line in watch.stdout:
        try:value=json.loads(line)['text']
        except (ValueError,KeyError):continue
        with lock:
            if value==last or (last is initial and value is None):continue
            try:request({'op':'clipboard-set','text':value})
            except Exception:continue
            last=value
    stopped.set()
    changed.set()

threading.Thread(target=from_linux,daemon=True).start()
# Android's clipboard is read when the app reports a change or the focus it needs (docs/49), not every second.
rungic_host_watch.watch(('clipboard',),changed.set,legacy=1,name='clipboard-watch')
while not stopped.is_set():
    try:
        with lock:
            result=request({'op':'clipboard-get'})
            if result.get('available') and result['text']!=last:
                value=result['text']
                if value is None:
                    subprocess.run(['wl-copy','--clear'],check=True,timeout=2)
                else:
                    subprocess.run(['wl-copy','--type','text/plain;charset=utf-8'],input=value.encode(),check=True,timeout=2)
                last=value
    except Exception:
        pass # Android may be paused, locked, or replacing its socket on restart.
    changed.wait()
    changed.clear()
stop()
