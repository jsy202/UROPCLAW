"""Wait for scheduled capture, then finish analysis, VLM audit and report."""
import json
import subprocess
import sys
import time
from pathlib import Path
HERE=Path(__file__).resolve().parent
while True:
    manifests=[json.loads(p.read_text()) for p in (HERE/'runs').glob('*/manifest.json')]
    complete=sum(m['status']=='COMPLETE' for m in manifests)
    if complete==40:break
    if any(m['status']=='FAILED' for m in manifests):raise RuntimeError('capture failed; preserve evidence and investigate')
    log=(HERE/'batch.log').read_text()
    if 'Traceback' in log or '\nFAILED' in log:raise RuntimeError('capture supervisor failed')
    print('WAIT capture %d/40'%complete,flush=True)
    time.sleep(30)
for script,args in [('analyze.py',[]),('diagnose_misses.py',[]),('stress.py',[]),('make_cases.py',[]),('audit_labels.py',[]),('report.py',[])]:
    print('START',script,flush=True)
    subprocess.run([sys.executable,str(HERE/script)]+args,check=True)
    print('DONE',script,flush=True)
print('PIPELINE COMPLETE',flush=True)
