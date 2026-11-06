"""Sequential resumable capture supervisor. Never runs simultaneous CARLA clients."""
import itertools
import os
import signal
import carla
from server_lifecycle import stop_process_group, ensure_map
import json
import subprocess
import sys
import time
from pathlib import Path
HERE=Path(__file__).resolve().parent
jobs=list(itertools.product(('Town10HD_Opt','Town03_Opt'),('clear','low_sun','rain'),(30,70),(101,102,201,202,203)))
server=None
current_map=None
def stop_server():
    global server
    if server is not None:
        stop_process_group(server)
    server=None

def start_server(town):
    stop_server()
    log=(HERE/('server_%s.log'%town)).open('a')
    proc=subprocess.Popen(['/home/jsy202/carla-0.9.13/CarlaUE4.sh','/Game/Carla/Maps/'+town,
                           '-RenderOffScreen','-quality-level=Low','-nosound','-carla-rpc-port=2000'],
                          stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    for attempt in range(120):
        if proc.poll() is not None: raise RuntimeError('server exited during startup')
        try:
            client=carla.Client('127.0.0.1',2000); client.set_timeout(1.)
            client.get_world()  # wait for RPC readiness before the longer map request
            client.set_timeout(90.)
            ensure_map(client,town)
            return proc
        except RuntimeError: pass
        time.sleep(1)
    os.killpg(proc.pid,signal.SIGTERM)
    raise RuntimeError('server readiness timeout')

import atexit
atexit.register(stop_server)
policy=json.loads((HERE/'execution_policy.json').read_text())
jobs=jobs[:int(policy.get('max_recordings',40))]
for index,(town,weather,vehicles,seed) in enumerate(jobs):
    name='%s_%s_v%d_s%d'%(town,weather,vehicles,seed)
    out=HERE/'runs'/name
    if (out/'manifest.json').exists() and json.loads((out/'manifest.json').read_text()).get('status')=='COMPLETE':
        print('SKIP COMPLETE',index+1,name,flush=True)
        continue
    if current_map != town:
        server=start_server(town)
        current_map=town
    out.mkdir(parents=True,exist_ok=True)
    print('START %d/%d %s'%(index+1,len(jobs),name),flush=True)
    command=[sys.executable,str(HERE/'capture.py'),'--map',town,'--weather',weather,'--vehicles',str(vehicles),
             '--seed',str(seed),'--split','dev' if seed<200 else 'test','--duration','180','--output',str(out)]
    with (out/'capture.log').open('a') as log:
        result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
    if result.returncode:
        print('FAILED',name,'returncode',result.returncode,flush=True)
        sys.exit(result.returncode)
    print('DONE',index+1,name,flush=True)
print('ALL CAPTURES COMPLETE',flush=True)
