#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Paired compositor diagnostic. Call after selecting a renderer and restarting.

Only Android surface presentation is measured here; Qt's separate native API
probe records client frameSwapped. Keep their conclusions separate.
"""
import argparse, json, re, statistics, subprocess, threading, time
from pathlib import Path
import profile_plasma_frames as frames

PLASMA=['python3','tools/rungic_plasma.py']
def user(*args,check=True):
    return subprocess.run(PLASMA+['user-exec',*args],check=check,text=True,capture_output=True)
def mobile(method):
    user('qdbus6','org.kde.plasmashell','/Mobile','org.kde.plasmashell.'+method)
def drawer():
    mobile('openHomeScreen'); mobile('resetHomeScreenPosition'); time.sleep(.45)
    frames.shell('input','swipe','540','2140','540','600','650'); time.sleep(.8)
def shot(path):
    with path.open('wb') as f:
        subprocess.run(frames.ADB[:-1]+['exec-out','screencap','-p'],check=True,stdout=f)
def percentile(v,p):
    return sorted(v)[int((len(v)-1)*p)] if v else None
def summary(intervals):
    return {'intervals':len(intervals),'median_ms':statistics.median(intervals) if intervals else None,
        'p95_ms':percentile(intervals,.95),'p99_ms':percentile(intervals,.99),
        'over_16_9_ms':sum(x>16.9 for x in intervals),'over_33_7_ms':sum(x>33.7 for x in intervals)}
def measure(scenario,out):
    layers=frames.shell('dumpsys','SurfaceFlinger','--list')
    matches=[x for x in layers.splitlines() if 'SurfaceView[dev.moto.plasma/' in x and '(BLAST)' in x]
    if len(matches)!=1: raise RuntimeError(matches)
    layer=re.search(r'\{(.*?) parentId=',matches[0])[1] if 'RequestedLayerState{' in matches[0] else matches[0]
    frames.shell('dumpsys','SurfaceFlinger','--latency-clear')
    raw=[]; actions=[]; errors=[]
    def gestures():
        try:
            if scenario=='scroll':
                for i in range(12):
                    start,end=(1800,700) if i%2==0 else (700,1800)
                    actions.append({'start':time.monotonic(),'action':'swipe','from':start,'to':end})
                    frames.shell('input','swipe','500',str(start),'500',str(end),'900')
                    actions[-1]['end']=time.monotonic(); time.sleep(.15)
            else:
                for i in range(6):
                    # The desktop is reset between cycles; no blind clicks into a
                    # drawer left scrolled by the preceding test.
                    drawer()
                    actions.append({'start':time.monotonic(),'action':'launch-calculator'})
                    frames.shell('input','tap','180','465'); time.sleep(1.8)
                    pid=user('pgrep','-x','kalk',check=False)
                    if pid.returncode: raise RuntimeError('Calculator did not launch; invalidate run')
                    actions[-1].update(end=time.monotonic(),pid=pid.stdout.strip())
                    actions.append({'start':time.monotonic(),'action':'close-calculator'})
                    frames.shell('input','tap','810','2340'); time.sleep(1)
                    if user('pgrep','-x','kalk',check=False).returncode==0:
                        raise RuntimeError('Calculator did not close; invalidate run')
                    actions[-1]['end']=time.monotonic()
        except Exception as e: errors.append(str(e))
    worker=threading.Thread(target=gestures); worker.start()
    while worker.is_alive():
        raw.append({'monotonic':time.monotonic(),'text':frames.shell('dumpsys','SurfaceFlinger','--latency',layer)})
        time.sleep(.20)
    worker.join(); pts=set()
    for sample in raw:
        for line in sample['text'].splitlines()[1:]:
            values=line.split()
            if len(values)==3 and all(x.isdigit() for x in values):
                n=int(values[1])
                if 0<n<9223372036854775807: pts.add(n)
    pts=sorted(pts); intervals=[(b-a)/1e6 for a,b in zip(pts,pts[1:])]
    result={'valid':not errors,'errors':errors,'layer':layer,'scenario':scenario,
        'actions':actions,'samples':raw,'present_ns':pts,'summary':summary(intervals),
        'note':'Includes identical gesture pauses/setup. Surface presentation is not client repaint completion.'}
    out.write_text(json.dumps(result,indent=2)+'\n'); print(out.name,json.dumps(result['summary']),errors,flush=True)
    if errors: raise RuntimeError(errors)
def main():
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);p.add_argument('--backend',choices=['gles','zink'],required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    frames.shell('input','keyevent','224'); frames.shell('wm','dismiss-keyguard')
    subprocess.run(PLASMA+['open'],check=True,capture_output=True); time.sleep(1)
    info=user('qdbus6','org.kde.KWin','/KWin','supportInformation').stdout
    (a.out/'kwin.txt').write_text(info)
    if ('zink Vulkan' in info)!=(a.backend=='zink'): raise SystemExit('Unexpected actual renderer')
    if 'Geometry: 0,0,360x800' not in info or 'Refresh Rate: 120000' not in info: raise SystemExit('Unexpected display configuration')
    user('pkill','-x','kalk',check=False)
    # Warm application/shader caches outside measurement.
    user('systemd-run','--user','--collect','--unit=rungic-bench-warm','kalk'); time.sleep(2)
    shot(a.out/'warm-calculator.png')
    frames.shell('input','tap','810','2340'); time.sleep(1)
    drawer(); shot(a.out/'drawer.png')
    sampler=subprocess.Popen(PLASMA+['user-exec','python3','/opt/rungic-gpu-bench/sample-cpu.py',
        '.cache/rungic-bench-cpu.json','120'],stdout=subprocess.DEVNULL)
    try:
        measure('scroll',a.out/'scroll.json')
        measure('launch',a.out/'launch.json')
    finally:
        # The sampler completes independently; wait only for collection time.
        user('pkill','-f','^python3 /opt/rungic-gpu-bench/sample-cpu.py',check=False)
        sampler.wait(timeout=10)
        cpu=user('cat','.cache/rungic-bench-cpu.json').stdout
        (a.out/'cpu.json').write_text(cpu)
    shot(a.out/'final.png')
if __name__=='__main__': main()
