#!/usr/bin/env python3
"""Reproduce CSVs/charts. Select on dev before accessing held-out replay results."""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from study import configurations, csv_write, replay

HERE=Path(__file__).resolve().parent


def numeric(row):
    text_keys={'run','split','map','weather','config','family','basis'}
    return {k:(v if k in text_keys else float(v) if v not in ('',None) else None) for k,v in row.items()}


def percentile(values,q):
    return float(np.percentile(values,q)) if values else None


def aggregate(summaries,scores):
    groups=collections.defaultdict(list)
    episodes=collections.defaultdict(list)
    for r in summaries: groups[(r['split'],r['config'])].append(r)
    for r in scores: episodes[(r['split'],r['config'])].append(r)
    rows=[]
    for (split,config),rs in groups.items():
        es=episodes[(split,config)]
        targets=[e for e in es if e['target'] and e['basis']=='detected']
        visible=[e for e in es if e['target'] and e['basis']=='visible']
        nontargets=[e for e in es if not e['target'] and e['basis']=='detected']
        actors={(e['run'],e['actor']) for e in targets}
        reached_actors={(e['run'],e['actor']) for e in targets if e['reached']}
        requests=sum(r['requests'] for r in rs)
        tp=sum(r['target_requests'] for r in rs)
        fp=sum(r['nontarget_requests'] for r in rs)
        unknown=sum(r['unassociated_requests'] for r in rs)
        rows.append(dict(split=split,config=config,runs=len(rs),detected_targets=len(targets),
                         reached_targets=sum(e['reached'] for e in targets),
                         unique_target_actors=len(actors),reached_unique_target_actors=len(reached_actors),
                         unique_actor_recall=len(reached_actors)/len(actors) if actors else None,
                         detected_recall=sum(e['reached'] for e in targets)/len(targets) if targets else None,
                         visible_targets=len(visible),visible_reached=sum(e['reached'] for e in visible),
                         visible_recall=sum(e['reached'] for e in visible)/len(visible) if visible else None,
                         detected_nontargets=len(nontargets),reached_nontargets=sum(e['reached'] for e in nontargets),
                         ambiguous_requests=sum(r['ambiguous_requests'] for r in rs),different_actor_suppressions=sum(r['different_actor_suppressions'] for r in rs),
                         requests=requests,target_requests=tp,nontarget_requests=fp,unassociated_requests=unknown,
                         conservative_request_precision=tp/requests if requests else None,
                         mapped_request_precision=tp/(tp+fp) if tp+fp else None,
                         candidates=sum(r['candidates'] for r in rs),repeated_requests=sum(r['repeated_requests'] for r in rs),
                         requests_per_min=requests/(sum(r['frames'] for r in rs)/600),
                         confirm_p50_s=percentile([e['confirm_delay_s'] for e in targets if e['confirm_delay_s'] is not None],50),
                         confirm_p95_s=percentile([e['confirm_delay_s'] for e in targets if e['confirm_delay_s'] is not None],95),
                         request_p50_s=percentile([e['request_delay_s'] for e in targets if e['request_delay_s'] is not None],50),
                         request_p95_s=percentile([e['request_delay_s'] for e in targets if e['request_delay_s'] is not None],95),
                         cpu_ms_p50_recording_median=percentile([r['cpu_ms_p50'] for r in rs],50),
                         cpu_ms_p95_recording_median=percentile([r['cpu_ms_p95'] for r in rs],50)))
    return rows


def choose(dev):
    rows={r['config']:r for r in dev}
    base=rows['n1_dedup']
    eligible=[r for r in dev if r['config'] in ['n%d_dedup'%n for n in (1,2,3,5,7,10)]
              and r['detected_recall'] is not None and r['detected_recall']>=base['detected_recall']-.02-1e-9
              and r['confirm_p95_s'] is not None and r['confirm_p95_s']<=.5+1e-9]
    if not eligible: return None
    return min(eligible,key=lambda r:(r['nontarget_requests']+r['unassociated_requests'],r['requests'],int(r['config'].split('_')[0][1:])))['config']


def paired_ci(summaries,split,base='n1_dedup'):
    rows=[r for r in summaries if r['split']==split]
    by=collections.defaultdict(dict)
    for r in rows: by[r['config']][r['run']]=r
    names=sorted(by[base]); rng=np.random.RandomState(20261106)
    indices=rng.randint(0,len(names),size=(2000,len(names)))
    def sample(config):
        rs=[by[config][name] for name in names]
        t=np.array([r['detected_targets'] for r in rs])[indices].sum(axis=1)
        reached=np.array([r['reached_targets'] for r in rs])[indices].sum(axis=1)
        req=np.array([r['requests'] for r in rs])[indices].sum(axis=1)
        minutes=np.array([r['frames']/600 for r in rs])[indices].sum(axis=1)
        return reached/np.maximum(t,1),req/minutes
    base_recall,base_requests=sample(base)
    result=[]
    for config in by:
        rec,req=sample(config)
        lo,hi=np.percentile(rec-base_recall,[2.5,97.5])
        qlo,qhi=np.percentile(req-base_requests,[2.5,97.5])
        result.append(dict(split=split,config=config,baseline=base,recall_diff_ci_low=lo,recall_diff_ci_high=hi,
                           requests_per_min_diff_ci_low=qlo,requests_per_min_diff_ci_high=qhi,
                           exploratory_noninferiority_2pp=bool(lo>=-.02),bootstrap_recordings=len(names),resamples=2000))
    return result


def paired_delays(scores):
    by=collections.defaultdict(dict)
    for row in scores:
        if row['basis']=='detected' and row['target']:
            by[(row['split'],row['config'])][(row['run'],row['episode'])]=row
    result=[]
    for (split,config),rows in by.items():
        base=by[(split,'n1_dedup')]
        for field in ('confirm_delay_s','request_delay_s'):
            differences=[row[field]-base[key][field] for key,row in rows.items()
                         if row[field] is not None and base[key][field] is not None]
            result.append(dict(split=split,config=config,baseline='n1_dedup',metric=field,joint_episodes=len(differences),
                               paired_difference_p50_s=percentile(differences,50),paired_difference_p95_s=percentile(differences,95),
                               baseline_only=sum(base[key][field] is not None and row[field] is None for key,row in rows.items()),
                               configuration_only=sum(base[key][field] is None and row[field] is not None for key,row in rows.items())))
    return result


def plots(aggregates,out):
    rows={r['config']:r for r in aggregates if r['split']=='test'}
    if not rows:return
    ns=[1,2,3,5,7,10]
    fig,axes=plt.subplots(1,3,figsize=(14,4))
    for suffix,label in [('dedup','Dedup on'),('raw','Dedup off')]:
        rs=[rows['n%d_%s'%(n,suffix)] for n in ns]
        axes[0].plot(ns,[100*r['detected_recall'] for r in rs],marker='o',label=label)
        axes[1].plot(ns,[r['requests_per_min'] for r in rs],marker='o',label=label)
        axes[2].plot(ns,[r['confirm_p95_s'] for r in rs],marker='o',label=label)
    axes[0].set_ylabel('Detected target episode recall (%)')
    axes[1].set_ylabel('VLM request triggers / minute')
    axes[2].set_ylabel('First confirmation delay p95 (sim s)')
    axes[2].axhline(.5,color='gray',linestyle='--',label='Proposed 0.5 s budget')
    for ax in axes:
        ax.set_xlabel('Observations N');ax.set_xticks(ns);ax.grid(alpha=.25);ax.legend(fontsize=8)
    fig.suptitle('Held-out CARLA replay: same input for every configuration')
    fig.tight_layout();fig.savefig(out/'window_tradeoff.png',dpi=180);plt.close(fig)
    for group,names in [('rules',['n3_dedup','rule_full','rule_unanimous','rule_sliding']),
                        ('architecture',['n3_dedup','early_hsv','late_hsv']),
                        ('factorial',['factor_%d%d%d'%(h,t,d) for h in (0,1) for t in (0,1) for d in (0,1)])]:
        rs=[rows[n] for n in names]
        fig,axes=plt.subplots(1,3,figsize=(14,4.7))
        for ax,field,label in zip(axes,['detected_recall','requests_per_min','request_p95_s'],['Target episode recall','Triggers / minute','First request delay p95 (sim s)']):
            ax.bar(names,[r[field] or 0 for r in rs]);ax.set_ylabel(label);ax.tick_params(axis='x',rotation=45);ax.grid(axis='y',alpha=.2)
        fig.suptitle('Held-out '+group+' comparison');fig.tight_layout();fig.savefig(out/(group+'.png'),dpi=180);plt.close(fig)


def evidence(run_dirs,out):
    import cv2
    selected=[]
    for directory in run_dirs:
        m=json.loads((directory/'manifest.json').read_text())
        if m['seed']!=201 or m['vehicles']!=70:continue
        frames=[json.loads(l) for l in (directory/'frames.jsonl').open()]
        f=max(frames,key=lambda f:len(f['detections']))
        image=cv2.imread(str(directory/f['image']))
        targets={p['actor_id'] for p in m['traffic'] if p['is_target_color']}
        for d in f['detections']:
            b=d['bbox'];color=(255,150,0) if d.get('actor') in targets else (0,230,0)
            cv2.rectangle(image,(b[0],b[1]),(b[2],b[3]),color,2)
            cv2.putText(image,d['color'],(b[0],max(15,b[1]-4)),cv2.FONT_HERSHEY_SIMPLEX,.45,color,1)
        title='%s %s | frame%d | detections%d'%(m['map'],m['weather'],f['index'],len(f['detections']))
        cv2.putText(image,title,(8,20),cv2.FONT_HERSHEY_SIMPLEX,.48,(0,0,0),3)
        cv2.putText(image,title,(8,20),cv2.FONT_HERSHEY_SIMPLEX,.48,(255,255,255),1)
        path=out/'evidence'/(directory.name+'.jpg');path.parent.mkdir(exist_ok=True)
        cv2.imwrite(str(path),image)
        selected.append((m['map'],m['weather'],image))
    if len(selected) in (3,4,6):
        order={'clear':0,'low_sun':1,'rain':2}
        selected.sort(key=lambda v:(v[0],order[v[1]]))
        cols=2 if len(selected)==4 else 3
        collage=np.concatenate([np.concatenate([cv2.resize(v[2],(480,360)) for v in selected[i:i+cols]],axis=1) for i in range(0,len(selected),cols)],axis=0)
        cv2.imwrite(str(out/'scene_comparison.jpg'),collage)


def analyze(root):
    runs=sorted(p for p in (root/'runs').iterdir() if (p/'manifest.json').exists())
    import itertools
    expected_cells=set(itertools.product(('Town10HD_Opt',),('clear','low_sun','rain'),(30,70),(101,102,201,202,203))) | set(itertools.product(('Town03_Opt',),('clear',),(30,70),(101,102,201,202,203)))
    actual_cells=[]
    for p in runs:
        m=json.loads((p/'manifest.json').read_text())
        cell=(m['map'],m['weather'],m['vehicles'],m['seed'])
        if cell not in expected_cells or m['split']!=('dev' if m['seed']<200 else 'test'):
            raise ValueError('unexpected condition/split: '+str(p))
        if m['status']=='COMPLETE':actual_cells.append(cell)
    if set(actual_cells)!=expected_cells or len(actual_cells)!=len(expected_cells):
        raise ValueError('missing/duplicate scheduled conditions')
    expected=40
    complete=[p for p in runs if json.loads((p/'manifest.json').read_text())['status']=='COMPLETE']
    if len(complete)!=expected:raise RuntimeError('Expected40 completed recordings, got%d'%len(complete))
    summaries,scores=[],[]
    out=root/'results';out.mkdir(exist_ok=True)
    for split in ('dev','test'):
        if split=='test' and not (out/'dev_selection.json').exists():raise RuntimeError('dev selection must be frozen first')
        for directory in complete:
            manifest=json.loads((directory/'manifest.json').read_text())
            if manifest['split']!=split:continue
            print('REPLAY',split,directory.name,flush=True)
            s,e,_=replay(directory);summaries.extend(s);scores.extend(e)
        aggregates=aggregate(summaries,scores)
        csv_write(out/'aggregate.csv',aggregates)
        if split=='dev':
            selection=dict(selected=choose(aggregates),rule='recall loss<=2pp vsN1; confirm p95<=.5s; min erroneous/unassociated triggers then total triggers then N',
                           based_on='16 development recordings only; no test results read',
                           data_sha256=hashlib.sha256(json.dumps(aggregates,sort_keys=True).encode()).hexdigest())
            selection_path=out/'dev_selection.json'
            if selection_path.exists():
                if json.loads(selection_path.read_text())['selected']!=selection['selected']:
                    raise ValueError('Frozen dev selection changed; preserve original and investigate')
            else:
                selection_path.write_text(json.dumps(selection,indent=2)+'\n')
            print('FROZEN SELECTION',selection['selected'],flush=True)
    csv_write(out/'per_recording.csv',summaries)
    csv_write(out/'episodes.csv',scores)
    csv_write(out/'paired_delays.csv',paired_delays(scores))
    cis=paired_ci(summaries,'dev')+paired_ci(summaries,'test')
    csv_write(out/'paired_confidence_intervals.csv',cis)
    # Stratified outcomes, retaining the shared recording unit for each condition.
    strata=[]
    for town in sorted({s['map'] for s in summaries}):
        for weather in ('clear','low_sun','rain'):
            for vehicles in (30,70):
                ss=[s for s in summaries if s['map']==town and s['weather']==weather and s['vehicles']==vehicles]
                ee=[e for e in scores if e['map']==town and e['weather']==weather and e['vehicles']==vehicles]
                for r in aggregate(ss,ee):r.update(map=town,weather=weather,vehicles=vehicles);strata.append(r)
    csv_write(out/'stratified.csv',strata)
    plots(aggregates,out);evidence(complete,out)
    timings=[]
    for p in complete:
        fs=[json.loads(l) for l in (p/'frames.jsonl').open()]
        m=json.loads((p/'manifest.json').read_text())
        timings.append(dict(run=p.name,split=m['split'],frames=len(fs),wall_s=m['wall_s'],
                            yolo_p50_ms=percentile([f['yolo_ms'] for f in fs],50),yolo_p95_ms=percentile([f['yolo_ms'] for f in fs],95),
                            hsv_p50_ms=percentile([f['hsv_ms'] for f in fs],50),hsv_p95_ms=percentile([f['hsv_ms'] for f in fs],95),
                            capture_p95_ms=percentile([f['capture_wall_ms'] for f in fs],95)))
    csv_write(out/'timings.csv',timings)
    print('ANALYSIS COMPLETE',out,flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=HERE)
    analyze(parser.parse_args().root)
