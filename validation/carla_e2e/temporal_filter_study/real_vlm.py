"""Small stratified VLM audit using production prompt/parser; no alerts are sent."""
from __future__ import annotations
import argparse
import collections
import json
import queue
import random
import subprocess
import threading
import time
from pathlib import Path
import cv2
import numpy as np
from study import configurations,csv_write,association_details
from core.pipeline import OpenClawWorker
HERE=Path(__file__).resolve().parent


def select():
    choice=json.loads((HERE/'results/dev_selection.json').read_text())['selected']
    pool=collections.defaultdict(lambda:collections.defaultdict(list))
    for p in sorted((HERE/'runs').iterdir()):
        m=json.loads((p/'manifest.json').read_text())
        if m['split']!='test':continue
        target={a['actor_id']:a['is_target_color'] for a in m['traffic']}
        for line in (p/'analysis/events.jsonl').open():
            e=json.loads(line)
            if e['kind']!='request' or e['config'] not in {'n3_dedup',choice}:continue
            key=(m['map'],m['weather'])
            category='target_request' if target.get(e['actor']) else 'nontarget_request' if e['actor'] in target else 'uncertain_request'
            pool[key][category].append(dict(run=p.name,frame=e['frame'],bbox=e['bbox'],actor=e['actor'],expected=target.get(e['actor']),category=category))
        # Negative controls are detected non-blue-painted vehicles, not asserted production requests.
        best={}
        for line in (p/'frames.jsonl').open():
            f=json.loads(line)
            for d in f['detections']:
                actor=association_details(d['bbox'],f['projected'])['actor']
                if actor not in target or target[actor]:continue
                b=d['bbox'];area=(b[2]-b[0])*(b[3]-b[1])
                if area<1200:continue
                if actor not in best or best[actor][0]<area:
                    best[actor]=(area,dict(run=p.name,frame=f['index'],bbox=b,actor=actor,expected=False,category='negative_control'))
        for _,item in best.values():pool[(m['map'],m['weather'])]['negative_control'].append(item)
    rng=random.Random(20261106);selected=[];seen=set()
    for stratum,categories in sorted(pool.items()):
        for category,quota in [('target_request',2),('nontarget_request',1),('uncertain_request',1),('negative_control',2)]:
            candidates=categories[category];rng.shuffle(candidates)
            count=0
            for item in candidates:
                key=(item['run'],item['actor']) if item['actor'] is not None else (item['run'],item['frame'])
                if key in seen:continue
                seen.add(key);selected.append(dict(item,map=stratum[0],weather=stratum[1]));count+=1
                if count>=quota:break
    # At most six per stratum (36 total), explicit exploratory sample rather than population accuracy.
    return selected


def main(execute):
    out=HERE/'results/real_vlm';out.mkdir(parents=True,exist_ok=True)
    path=out/'sample_manifest.json'
    if path.exists():samples=json.loads(path.read_text())
    else:
        samples=select();path.write_text(json.dumps(samples,indent=2)+'\n')
    print('VLM samples:',len(samples),flush=True)
    if not execute:return
    rows=[]
    for i,item in enumerate(samples):
        result_path=out/('%03d.json'%i)
        if result_path.exists():
            rows.append(json.loads(result_path.read_text()));continue
        image=cv2.imread(str(HERE/'runs'/item['run']/'images'/('%06d.jpg'%item['frame'])))
        x1,y1,x2,y2=item['bbox'];crop=image[max(0,y1):y2,max(0,x1):x2]
        if not crop.size:raise ValueError('empty crop')
        crop_path=(out/('%03d.jpg'%i)).resolve();cv2.imwrite(str(crop_path),crop)
        raw={}
        def runner(command,**kwargs):
            command=command+['--allowedTools','Read']
            result=subprocess.run(command,**kwargs)
            raw.update(returncode=result.returncode,stdout=result.stdout.decode(errors='replace'),stderr=result.stderr.decode(errors='replace'))
            return result
        metrics={}
        worker=OpenClawWorker(threading.Event(),queue.Queue(),queue.Queue(),metrics,vlm_runner=runner)
        start=time.perf_counter()
        response=worker._llm_verify({},dict(target_color='blue'),str(crop_path))
        elapsed=time.perf_counter()-start
        failed=bool(metrics.get('openclaw_timeouts') or metrics.get('openclaw_errors') or metrics.get('openclaw_parse_failures'))
        row=dict(item,index=i,wall_s=elapsed,failed=failed,metrics=metrics,response=response,raw=raw,
                 correct=None if failed or item['expected'] is None else bool(response['confirmed'])==item['expected'])
        result_path.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n');rows.append(row)
        print('VLM %d/%d %.2fs failed=%s category=%s'%(i+1,len(samples),elapsed,failed,item['category']),flush=True)
    flat=[dict(index=r['index'],map=r['map'],weather=r['weather'],category=r['category'],expected=r['expected'],confirmed=r['response']['confirmed'],
               failed=r['failed'],correct=r['correct'],wall_s=r['wall_s'],run=r['run'],frame=r['frame']) for r in rows]
    csv_write(out/'samples.csv',flat)
    success=[r for r in rows if not r['failed']]
    labelled=[r for r in success if r['expected'] is not None]
    summary=dict(samples=len(rows),success=len(success),failed=len(rows)-len(success),labelled_success=len(labelled),
                 correct=sum(r['correct'] for r in labelled),wall_p50_s=float(np.percentile([r['wall_s'] for r in rows],50)),
                 wall_p95_s=float(np.percentile([r['wall_s'] for r in rows],95)),
                 limitation='Exploratory stratified requests plus negative controls, not unbiased pipeline precision/recall. JPEG evidence crops. Production fail-open excluded from accuracy. No alerts or queue measurements.')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)

if __name__=='__main__':
    policy=json.loads((HERE/'execution_policy.json').read_text())
    if not policy.get('allow_real_vlm',False):
        raise SystemExit('Actual VLM execution is disabled by explicit user instruction.')
    p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');main(p.parse_args().execute)
