#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Read-only CPU/RSS sampler, run inside LXC. One process, no per-tick su calls."""
import json, os, signal, sys, time
from pathlib import Path
out=Path(sys.argv[1]); duration=float(sys.argv[2]); rows=[]
start=time.monotonic(); ticks=os.sysconf('SC_CLK_TCK'); running=True
def stop(*args):
    global running
    running=False
signal.signal(signal.SIGTERM,stop)
while running and time.monotonic()-start < duration:
    procs={}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit(): continue
        try:
            stat=(entry/'stat').read_text(); end=stat.rindex(')')
            comm=stat[stat.index('(')+1:end]; fields=stat[end+2:].split()
            if comm not in ('kwin_wayland','plasmashell','kalk','quick-render'): continue
            procs[entry.name]={'name':comm,'cpu_ticks':int(fields[11])+int(fields[12]),
                'start_ticks':int(fields[19]),'rss_pages':int(fields[21])}
        except (OSError,ValueError,IndexError): pass
    rows.append({'monotonic':time.monotonic(),'processes':procs})
    time.sleep(0.5)
out.write_text(json.dumps({'hz':ticks,'page_size':os.sysconf('SC_PAGE_SIZE'),'samples':rows}))
