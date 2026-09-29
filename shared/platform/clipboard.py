#!/usr/bin/python3
"""Synchronize plain text through wl-clipboard and the private Android host API.
No clipboard history or content logs. Android access is independent of APK windows.
"""
import json, os, signal, socket, struct, subprocess, sys, threading

LIMIT=262144
SOCKET='\0com.rungic.clipboard.v1'

def request(value):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as c:
        c.settimeout(35 if value.get("op")=="watch" else 4);c.connect(SOCKET)
        _, uid, _ = struct.unpack("3i", c.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if uid!=2000:raise PermissionError("Unexpected clipboard backend")
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
# Android current text is authoritative when opening a session or reconnecting.
try:
    result=request({'op':'clipboard-get'})
    if result.get('available'):
        value=result['text']
        if value is None:subprocess.run(['wl-copy','--clear'],timeout=2,check=True)
        else:subprocess.run(['wl-copy','--type','text/plain;charset=utf-8'],input=value.encode(),timeout=2,check=True)
        last=value
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
            if last is initial:
                # wl-paste emits the existing selection on subscription. If Android is
                # unavailable (e.g. sensitive/locked), that stale Linux value is a baseline,
                # not a new copy: do not overwrite the private Android clipboard on startup.
                last=value
                continue
            if value==last:continue
            try:request({'op':'clipboard-set','text':value})
            except Exception:continue
            last=value
    stopped.set()
    changed.set()

threading.Thread(target=from_linux,daemon=True).start()
# Android's own callback wakes this channel even while another application has focus.
# A bounded long poll also recovers after daemon restarts; never fallback to Activity access.
def from_android():
    epoch, seen = None, None
    while not stopped.is_set():
        try:
            result=request({'op':'watch','epoch':epoch,'seen':seen,'timeout':30000})
            epoch,seen=result['epoch'],result['versions']
        except Exception:
            stopped.wait(2)
        changed.set()
threading.Thread(target=from_android,daemon=True).start()
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
        pass # Backend may be restarting, locked, or serving another Android user.
    changed.wait()
    changed.clear()
stop()
