"""Complete analysis only after all30 new6000-frame recordings; no model calls."""
import json
import subprocess
import sys
import time
from pathlib import Path
HERE=Path(__file__).resolve().parent
REFERENCE=HERE.parent/'temporal_filter_study'
while True:
    ms=[json.loads(p.read_text()) for p in (HERE/'runs').glob('*/manifest.json')]
    complete=sum(m['status']=='COMPLETE' and m['frames']==6000 and m['duration_s']==600 for m in ms)
    if complete==30:break
    if any(m['status']=='FAILED' for m in ms):raise RuntimeError('capture failed; investigate without discarding data')
    log=(HERE/'batch.log').read_text()
    if 'Traceback' in log:raise RuntimeError('capture supervisor failed')
    print('WAIT capture %d/30 at6000frames'%complete,flush=True);time.sleep(30)
steps=[(HERE/'analyze_progressive.py',[]),
       (REFERENCE/'diagnose_misses.py',['--root',str(HERE)]),
       (REFERENCE/'audit_labels.py',['--root',str(HERE)]),
       (REFERENCE/'stress.py',['--root',str(HERE)]),
       (REFERENCE/'verify_archive.py',['--root',str(HERE),'--expected-recordings','30']),
       (HERE/'report_progressive.py',[])]
for script,args in steps:
    print('START',script.name,flush=True)
    subprocess.run([sys.executable,str(script)]+args,check=True)
    print('DONE',script.name,flush=True)
print('ALL EXPERIMENTS AND REPORT COMPLETE',flush=True)
