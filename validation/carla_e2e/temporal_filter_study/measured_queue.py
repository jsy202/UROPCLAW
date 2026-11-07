"""Measured real-time candidate replay into the actual production VLM worker.

Perception is cached, so this is a back-end queue/VLM measurement, not a live
sensor-to-alert benchmark. Never instantiates AlertWorker or sends notifications.
"""
from __future__ import annotations
import argparse
import json
import queue
import subprocess
import threading
import time
from pathlib import Path
import cv2
import numpy as np
from study import csv_write
import core.pipeline as pipeline
import core.mission as mission
HERE=Path(__file__).resolve().parent


class ObservedQueue(queue.Queue):
    def __init__(self,trace,**kwargs):
        super().__init__(**kwargs)
        self.trace=trace

    def get(self,*args,**kwargs):
        item=super().get(*args,**kwargs)
        self.trace[item['profile_id']].update(dequeued=time.monotonic(),status='dequeued')
        return item


class MeasuredWorker(pipeline.OpenClawWorker):
    def __init__(self,stop,source,results,metrics,trace):
        self.trace=trace
        self.busy=threading.Event()
        self.current_profile=None
        super().__init__(stop,source,results,metrics,vlm_runner=self.runner)

    def runner(self,command,**kwargs):
        proc=subprocess.run(command+['--allowedTools','Read'],**kwargs)
        self.trace[self.current_profile]['raw']=dict(returncode=proc.returncode,stdout=proc.stdout.decode(errors='replace'),stderr=proc.stderr.decode(errors='replace'))
        return proc

    def _llm_verify(self,candidate,mission_data,crop_path):
        self.current_profile=candidate['profile_id']
        row=self.trace[self.current_profile]
        row.update(started=time.monotonic(),crop_path=crop_path,status='in_vlm')
        before=dict(self._metrics)
        self.busy.set()
        try:
            response=super()._llm_verify(candidate,mission_data,crop_path)
            row['response']=response
            row['failed']=any(self._metrics.get(k,0)>before.get(k,0) for k in ('openclaw_timeouts','openclaw_errors','openclaw_parse_failures'))
            return response
        finally:
            row.update(ended=time.monotonic(),status='completed')
            self.busy.clear()


def _run(config,clip):
    directory=HERE/'runs'/clip
    output=HERE/'results/measured_queue'/config
    output.mkdir(parents=True,exist_ok=True)
    if (output/'summary.json').exists():
        cached=json.loads((output/'summary.json').read_text())
        if cached['clip']!=clip:raise ValueError('cached clip differs; preserve results and use a separate root')
        print('REUSE measured queue',config,flush=True);return
    manifest=json.loads((directory/'manifest.json').read_text())
    if manifest['status']!='COMPLETE':raise ValueError('complete capture required')
    events=[json.loads(line) for line in (directory/'analysis/events.jsonl').open()]
    candidates=[e for e in events if e['config']==config and e['kind']=='candidate']
    if not candidates:raise ValueError('selected fixed clip contains no candidates')
    pipeline.WORKSPACE_BASE=(output/'workspaces').resolve()
    mission._MISSION_PATH=pipeline.WORKSPACE_BASE/'uropclaw1/state/mission.json'
    mission.write_mission(dict(active=True,target_color='blue',mission_id='measured-queue'))
    trace={};source=ObservedQueue(trace,maxsize=20);results=queue.Queue(maxsize=20);stop=threading.Event();metrics={}
    worker=MeasuredWorker(stop,source,results,metrics,trace)
    worker.start();start=time.monotonic()
    last_frame=None;image=None
    def drain_results():
        while True:
            try:results.get_nowait()
            except queue.Empty:return
    try:
        for i,event in enumerate(candidates):
            deadline=start+event['t']
            while time.monotonic()<deadline:
                drain_results();time.sleep(min(.02,max(0,deadline-time.monotonic())))
            if event['frame']!=last_frame:
                image=cv2.imread(str(directory/'images'/('%06d.jpg'%event['frame'])))
                if image is None:raise ValueError('missing image')
                last_frame=event['frame']
            trace[i]=dict(profile_id=i,source_frame=event['frame'],source_t=event['t'],source_actor=event['actor'],
                          track=event['track'],bbox=event['bbox'],arrived=time.monotonic(),status='queued')
            item=dict(profile_id=i,camera_id='measured-camera',agent_id='uropclaw1',track_id=event['track'],color=event['color'],
                      bbox=event['bbox'],frame=image,timestamp=time.time(),dedup_enabled=True)
            try:source.put_nowait(item)
            except queue.Full:
                trace[i]['status']='queue_full';metrics['candidates_dropped']=metrics.get('candidates_dropped',0)+1
            drain_results()
            if i%100==0:print('MEASURE',config,i,'source_t',event['t'],'queue',source.qsize(),flush=True)
        while time.monotonic()<start+180:
            drain_results();time.sleep(.02)
        idle_since=None;drain_deadline=time.monotonic()+600
        while time.monotonic()<drain_deadline:
            drain_results()
            if source.empty() and not worker.busy.is_set():
                idle_since=time.monotonic() if idle_since is None else idle_since
                if time.monotonic()-idle_since>1:break
            else:idle_since=None
            if not worker.is_alive():raise RuntimeError('VLM worker stopped unexpectedly')
            time.sleep(.02)
        else:raise RuntimeError('VLM queue did not drain within600s')
    finally:
        stop.set();worker.join(timeout=30);drain_results()
        (output/'trace.json').write_text(json.dumps(list(trace.values()),ensure_ascii=False,indent=2)+'\n')
    if worker.is_alive():raise RuntimeError('VLM worker did not stop')
    rows=[]
    for r in trace.values():
        if r['status']=='dequeued':r['status']='dedup_suppressed'
        row=dict(profile_id=r['profile_id'],source_frame=r['source_frame'],source_t=r['source_t'],status=r['status'],
                 source_actor=r['source_actor'],track=r['track'],enqueue_lateness_s=r['arrived']-start-r['source_t'],
                 wait_s=r['dequeued']-r['arrived'] if 'dequeued' in r else None,
                 service_s=r['ended']-r['started'] if 'ended' in r else None,
                 candidate_to_response_s=r['ended']-r['arrived'] if 'ended' in r else None,
                 failed=r.get('failed'),confirmed=r.get('response',{}).get('confirmed'))
        rows.append(row)
    csv_write(output/'trace.csv',rows)
    calls=[r for r in rows if r['status']=='completed']
    if len(calls)!=metrics.get('openclaw_calls',0):raise ValueError('missing worker call trace')
    summary=dict(config=config,clip=clip,input_duration_s=180,wall_s=time.monotonic()-start,candidates=len(candidates),
                 calls=len(calls),queue_dropped=sum(r['status']=='queue_full' for r in rows),
                 dedup_suppressed=sum(r['status']=='dedup_suppressed' for r in rows),vlm_failed=sum(bool(r['failed']) for r in calls),metrics=metrics,
                 wait_p50_s=float(np.percentile([r['wait_s'] for r in calls],50)) if calls else None,
                 wait_p95_s=float(np.percentile([r['wait_s'] for r in calls],95)) if calls else None,
                 service_p95_s=float(np.percentile([r['service_s'] for r in calls],95)) if calls else None,
                 candidate_to_response_p95_s=float(np.percentile([r['candidate_to_response_s'] for r in calls],95)) if calls else None,
                 enqueue_lateness_p95_s=float(np.percentile([r['enqueue_lateness_s'] for r in rows],95)),
                 limitation='Single held-out clip, cached perception, real10Hz timing and production VLM worker/20queue. No live detector/camera/alerts; no population inference.')
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('MEASURE COMPLETE',json.dumps(summary),flush=True)

def run(config,clip):
    previous_workspace=pipeline.WORKSPACE_BASE
    previous_mission=mission._MISSION_PATH
    try:
        return _run(config,clip)
    finally:
        pipeline.WORKSPACE_BASE=previous_workspace
        mission._MISSION_PATH=previous_mission


if __name__=='__main__':
    policy=json.loads((HERE/'execution_policy.json').read_text())
    if not policy.get('allow_real_vlm',False):
        raise SystemExit('Actual VLM execution is disabled by explicit user instruction.')
    p=argparse.ArgumentParser();p.add_argument('--config');p.add_argument('--clip',default='Town10HD_Opt_clear_v70_s201');args=p.parse_args()
    selected=json.loads((HERE/'results/dev_selection.json').read_text())['selected']
    names=[args.config] if args.config else ['n3_dedup',selected if selected and selected!='n3_dedup' else 'n1_dedup']
    for name in names:run(name,args.clip)
