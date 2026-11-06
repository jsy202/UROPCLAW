"""Capture30 fresh6000-frame recordings; no VLM and no calendar timestamps."""
import atexit
import itertools
import json
import subprocess
import sys
import time
from pathlib import Path
import carla
HERE=Path(__file__).resolve().parent
REFERENCE=HERE.parent/'temporal_filter_study'
sys.path.insert(0,str(REFERENCE))
from server_lifecycle import stop_process_group,ensure_map,ports_free

JOBS=list(itertools.product(('Town10HD_Opt',),('clear','low_sun','rain'),(30,70),(101,102,201,202,203)))
server=None

def stop_server():
    global server
    if server is not None:
        stop_process_group(server)
        server=None


def start_server(town):
    stop_server()
    if not ports_free():raise RuntimeError('CARLA ports already in use; do not disturb unowned processes')
    log=(HERE/('server_'+town+'.log')).open('a')
    proc=subprocess.Popen(['/home/jsy202/carla-0.9.13/CarlaUE4.sh','-RenderOffScreen','-quality-level=Low','-nosound','-carla-rpc-port=2000'],
                          stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        for _ in range(120):
            if proc.poll() is not None:raise RuntimeError('CARLA wrapper exited during startup')
            try:
                client=carla.Client('127.0.0.1',2000);client.set_timeout(1.)
                client.get_world();client.set_timeout(90.)
                ensure_map(client,town)
                return proc
            except RuntimeError:
                if proc.poll() is not None:raise
                time.sleep(1)
        raise RuntimeError('CARLA readiness timeout')
    except BaseException:
        stop_process_group(proc)
        raise


def main():
    global server
    policy=json.loads((REFERENCE/'execution_policy.json').read_text())
    assert policy['allow_real_vlm'] is False and int(policy['max_recordings'])==30
    current_map=None
    for index,(town,weather,vehicles,seed) in enumerate(JOBS):
        name='%s_%s_v%d_s%d'%(town,weather,vehicles,seed)
        out=HERE/'runs'/name
        if (out/'manifest.json').exists():
            old=json.loads((out/'manifest.json').read_text())
            if old.get('status')=='COMPLETE' and old.get('duration_s')==600 and old.get('frames')==6000:
                print('SKIP',index+1,name,flush=True);continue
            raise RuntimeError('Preserve/investigate partial or incompatible capture: '+str(out))
        if current_map!=town:
            server=start_server(town);current_map=town
        out.mkdir(parents=True,exist_ok=True)
        print('START %d/30 %s frames6000 duration600s Hz10'%(index+1,name),flush=True)
        command=[sys.executable,str(REFERENCE/'capture.py'),'--map',town,'--weather',weather,'--vehicles',str(vehicles),
                 '--seed',str(seed),'--split','dev' if seed<200 else 'test','--duration','600','--output',str(out)]
        with (out/'capture.log').open('a') as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError('Capture failed: '+name+' returncode'+str(result.returncode))
        print('DONE',index+1,name,flush=True)
    print('ALL30 CAPTURES COMPLETE',flush=True)

atexit.register(stop_server)
if __name__=='__main__':main()
