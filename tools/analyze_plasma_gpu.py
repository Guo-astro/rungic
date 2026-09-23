#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Summarize captured data; never label submission timing as GPU execution time."""
import argparse,json,statistics
from pathlib import Path

def quantile(values,q):
    values=sorted(values)
    return values[int((len(values)-1)*q)] if values else None
def stats(values):
    return {'count':len(values),'median_ms':quantile(values,.5),'p95_ms':quantile(values,.95),
        'p99_ms':quantile(values,.99),'over_12_6_pct':100*sum(x>12.6 for x in values)/len(values) if values else None,
        'over_16_9_pct':100*sum(x>16.9 for x in values)/len(values) if values else None,
        'over_33_7_pct':100*sum(x>33.7 for x in values)/len(values) if values else None}
def cpu(data):
    rows=data['samples'];results={}
    for pid,first in rows[0]['processes'].items():
        if first['name'] not in ['kwin_wayland','plasmashell']:continue
        last=next((r for r in reversed(rows) if pid in r['processes']),None)
        if not last:continue
        end=last['processes'][pid]
        if end['start_ticks']!=first['start_ticks']:continue
        duration=last['monotonic']-rows[0]['monotonic']
        results[first['name']]={'cpu_pct_one_core':(end['cpu_ticks']-first['cpu_ticks'])/data['hz']/duration*100,
            'rss_MiB':end['rss_pages']*data['page_size']/1024**2}
    return results
def main():
    parser=argparse.ArgumentParser();parser.add_argument('base',type=Path);args=parser.parse_args();base=args.base
    offset=None;clockfile=base/'clock-calibration.json'
    if clockfile.exists():
        clocks=json.loads(clockfile.read_text());best=sorted(clocks,key=lambda x:x['rtt_ms'])[:5]
        offset=statistics.median(x['host_minus_device_s'] for x in best)
    desktop=[];quick=[]
    for path in sorted((base/'compositor').glob('*-*')):
        entry={'name':path.name,'backend':path.name.split('-')[1]}
        complete=True
        for scenario in ['scroll','launch']:
            file=path/(scenario+'.json')
            if not file.exists():complete=False;break
            data=json.loads(file.read_text())
            if not data['valid']:complete=False;break
            pts=[x/1e9 for x in data['present_ns']]
            entry[scenario]={'whole_macro':data['summary']}
            if offset is not None:
                windows=[]
                for action in data['actions']:
                    start=action['start']-offset
                    # Trim command dispatch at the beginning. Fixed windows
                    # exclude the explicit inter-action pause/setup period.
                    if scenario=='scroll': end=action['end']-offset
                    else: end=start+(1.20 if action['action'].startswith('launch') else .85)
                    windows.append((start+.10,end))
                intervals=[];counts=[]
                for start,end in windows:
                    selected=[x for x in pts if start<=x<=end]
                    counts.append(len(selected))
                    intervals.extend((b-a)*1000 for a,b in zip(selected,selected[1:]))
                entry[scenario]['action_windows']=stats(intervals)
                entry[scenario]['frames_per_window']=counts
        if complete:
            entry['cpu']=cpu(json.loads((path/'cpu.json').read_text()));desktop.append(entry)
    for path in sorted([*(base/'quick').glob('*.json'),*(base/'quick-controlled').glob('*.json')]):
        data=json.loads(path.read_text())
        pts=data['swapped_ms'];intervals=[b-a for a,b in zip(pts,pts[1:])]
        quick.append({'name':path.stem,'batch':path.parent.name,'backend':data['requested_backend'],'graphics_api':data['graphics_api'],
            'width':data['width'],'height':data['height'],'dpr':data['dpr'],
            'submitted_fps':(len(pts)-1)*1000/(pts[-1]-pts[0]),
            'frame_intervals':stats(intervals),'cpu_pct_one_core':data['cpu_ms']/data['elapsed_ms']*100,
            'cpu_ms_per_submitted_frame':data['cpu_ms']/len(pts),
            'render_command_time':stats(data['render_command_ms']),
            'physical_refresh_hz':sorted({round(v['currentRefresh'],2) for v in data.get('display_samples',[])})})
    result={'host_minus_device_s':offset,'compositor':desktop,'quick':quick}
    (base/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    for entry in desktop:print(entry['name'],entry['scroll'].get('action_windows',entry['scroll']['whole_macro']),entry['cpu'])
    for entry in quick:print(entry['name'],'fps',round(entry['submitted_fps'],2),'p95',round(entry['frame_intervals']['p95_ms'],3),'CPU',round(entry['cpu_pct_one_core'],2),'CPU/frame',round(entry['cpu_ms_per_submitted_frame'],3))
if __name__=='__main__':main()
