#!/usr/bin/python3
"""pa-gap.py [stock|fixed]: play a 997 Hz tone with Qt 6.10's stock buffer attributes (maxlength 1024 frames, the rest
server-chosen) while recording android.monitor; report zero runs inside the tone."""
import ctypes, math, struct, subprocess, sys, time, array
pa = ctypes.CDLL('libpulse-simple.so.0')
class Spec(ctypes.Structure):
    _fields_ = [('format', ctypes.c_int), ('rate', ctypes.c_uint32), ('channels', ctypes.c_uint8)]
class Attr(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint32) for n in ('maxlength', 'tlength', 'prebuf', 'minreq', 'fragsize')]
mode = sys.argv[1] if len(sys.argv) > 1 else 'stock'
spec = Spec(3, 48000, 2)            # PA_SAMPLE_S16LE
M = 0xffffffff
attr = Attr(1024 * 4, M, M, M, M) if mode == 'stock' else Attr(M, 1024 * 4, M, M, M)
err = ctypes.c_int()
pa.pa_simple_new.restype = ctypes.c_void_p
rec = subprocess.Popen(['parec', '-d', 'android.monitor', '--format=s16le', '--rate=48000', '--channels=1', '--raw'],
                       stdout=subprocess.PIPE)
time.sleep(0.5)
s = pa.pa_simple_new(None, b'gap-test', 1, None, b'tone', ctypes.byref(spec), None, ctypes.byref(attr), ctypes.byref(err))
assert s, err.value
n = 48000 * 4
buf = array.array('h', (int(12000 * math.sin(2 * math.pi * 997 * i / 48000)) for i in range(n) for _ in range(2)))
data = buf.tobytes()
step = 4096
for i in range(0, len(data), step):
    pa.pa_simple_write(ctypes.c_void_p(s), data[i:i + step], len(data[i:i + step]), ctypes.byref(err))
pa.pa_simple_drain(ctypes.c_void_p(s), ctypes.byref(err))
time.sleep(0.3)
rec.terminate(); raw = rec.stdout.read()
x = array.array('h'); x.frombytes(raw[:len(raw) // 2 * 2])
# The tone's span: first/last sample above 1000.
idx = [i for i, v in enumerate(x) if abs(v) > 1000]
a, b = idx[0], idx[-1]
runs, run = [], 0
for v in x[a:b]:
    if abs(v) < 20:
        run += 1
    else:
        if run >= 8: runs.append(run)
        run = 0
print(f'{mode}: tone {(b - a) / 48000:.2f}s, zero runs >=8 samples: {len(runs)}, lengths {sorted(set(runs))[:8]}')
