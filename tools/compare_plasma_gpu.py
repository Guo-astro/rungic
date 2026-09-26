#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run controlled, interleaved GPU comparisons; restore the original KWin backend.

One device at a time. No clock locking, thermal changes, or security changes.
"""
import argparse, json, shlex, subprocess, time
from pathlib import Path

import rungic_device

ADB=rungic_device.adb()
PLASMA=['python3','tools/rungic_plasma.py']
DROP='/run/user/1000/systemd/user/plasma-kwin_wayland.service.d/90-rungic-zink-audit.conf'
def user(*args,check=True,combined=False):
    result=subprocess.run(PLASMA+['user-exec',*args],check=check,text=True,capture_output=True)
    return result.stdout+(result.stderr if combined else '')
def root(command):
    return subprocess.check_output(ADB+['shell','su -c '+shlex.quote(command)],text=True)
def health(out):
    out.write_text(root('dumpsys thermalservice; cat /sys/class/kgsl/kgsl-3d0/gpubusy; cat /sys/class/kgsl/kgsl-3d0/devfreq/cur_freq'))
def renderer(name):
    if name=='zink':
        text='[Service]\nEnvironment=MESA_LOADER_DRIVER_OVERRIDE=zink\nEnvironment=GALLIUM_DRIVER=zink\n'
        user('sh','-c','mkdir -p '+shlex.quote(str(Path(DROP).parent))+'; printf %s '+shlex.quote(text)+' > '+shlex.quote(DROP))
    else: user('rm','-f',DROP)
    user('systemctl','--user','daemon-reload')
    subprocess.run(PLASMA+['restart-session'],check=True,capture_output=True)
    time.sleep(8)
def wake():
    subprocess.run(ADB+['shell','input','keyevent','224'],check=True)
    subprocess.run(ADB+['shell','wm','dismiss-keyguard'],check=True)
    subprocess.run(PLASMA+['open'],check=True,capture_output=True)
def main():
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);p.add_argument('--phase',choices=['compositor','quick'],required=True)
    p.add_argument('--scene',choices=['all','scroll','layers'],default='all')
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    if a.phase=='compositor':
        # ABBAAB, three independently restarted and warmed sessions per path.
        sequence=['gles','zink','zink','gles','gles','zink']
        try:
            for i,backend in enumerate(sequence,1):
                print('START compositor',i,backend,flush=True)
                renderer(backend);wake()
                dest=a.out/f'{i}-{backend}';dest.mkdir(exist_ok=True)
                health(dest/'health-before.txt')
                subprocess.run(['python3','tools/benchmark_plasma_compositor.py',str(dest),'--backend',backend],check=True)
                health(dest/'health-after.txt')
                print('DONE compositor',i,backend,flush=True)
        finally:
            renderer('gles');wake()
    else:
        renderer('gles');wake()
        # The compositor stays identical for the native API comparison.
        for scene in (['scroll','layers'] if a.scene=='all' else [a.scene]):
            for i,backend in enumerate(['opengl','vulkan','vulkan','opengl','opengl','vulkan'],1):
                wake();tag=f'{scene}-{i}-{backend}';print('START quick',tag,flush=True)
                health(a.out/(tag+'-health.txt'))
                remote='/home/rungic/.cache/rungic-bench-'+tag+'.json'
                result=user('systemd-run','--user','--wait','--pipe','--collect','--unit=rungic-quick-bench',
                    'env','QSG_RHI_BACKEND='+backend,'QSG_INFO=1',
                    '/opt/rungic-gpu-bench/quick-render','/opt/rungic-gpu-bench/'+scene+'-scene.qml',remote,combined=True)
                (a.out/(tag+'.log')).write_text(result)
                raw=user('cat',remote);data=json.loads(raw)
                (a.out/(tag+'.json')).write_text(raw)
                if len(data['swapped_ms']) < 60: raise RuntimeError('No valid rendered frame sequence')
                print('DONE quick',tag,'frames',len(data['swapped_ms']),'CPU ms',data['cpu_ms'],flush=True)
                time.sleep(2)
if __name__=='__main__':main()
