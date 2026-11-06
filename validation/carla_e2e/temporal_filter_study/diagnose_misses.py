"""Explain N1-confirmed/N3-unconfirmed target episodes using saved observations."""
import collections
import csv
import json
from pathlib import Path
from study import Branch,association_details,configurations,csv_write,episodes
HERE=Path(__file__).resolve().parent

def main(root=HERE):
    HERE=root
    durations={p.parent.name:json.loads(p.read_text())["duration_s"] for p in (HERE/"runs").glob("*/manifest.json")}
    rows=list(csv.DictReader((HERE/'results/episodes.csv').open()))
    by=collections.defaultdict(dict)
    for row in rows:
        if row['split']=='test' and row['basis']=='detected' and row['target']=='1':
            by[(row['run'],int(row['episode']))][row['config']]=row
    miss=[(key,rs) for key,rs in by.items() if rs['n1_dedup']['confirm_delay_s']!='' and rs['n3_dedup']['confirm_delay_s']=='']
    records=[]
    for run in sorted({key[0] for key,_ in miss}):
        directory=HERE/'runs'/run
        manifest=json.loads((directory/'manifest.json').read_text())
        labels={a['actor_id']:a['is_target_color'] for a in manifest['traffic']}
        frames=[json.loads(line) for line in (directory/'frames.jsonl').open()]
        for frame in frames:
            for det in frame['detections']:det['actor']=association_details(det['bbox'],frame['projected'])['actor']
        eps,assoc=episodes(frames,labels,'detected')
        branch=Branch(next(c for c in configurations() if c['name']=='n3_dedup'))
        evidence=collections.defaultdict(list)
        for index,frame in enumerate(frames):
            branch.process([{k:d[k] for k in ('bbox','class_id','confidence','color')} for d in frame['detections']],frame['t'])
            if not frame['detections']:continue
            for tid,track in branch.tracker._tracks.items():
                if track.disappeared:continue
                actor=association_details(track.bbox,frame['projected'])['actor']
                ep=assoc.get((index,actor))
                if ep is not None:evidence[ep].append((frame['t'],tid,track.color_history[-1]))
        for key,_ in miss:
            if key[0]!=run:continue
            ep=key[1];observations=evidence[ep];counts=collections.Counter(row[1] for row in observations)
            records.append(dict(run=run,episode=ep,actor=eps[ep]['actor'],observations=len(observations),
                                blue_observations=sum(row[2]=='blue' for row in observations),
                                max_observations_same_track=max(counts.values()) if counts else 0,
                                track_ids=json.dumps(dict(counts)),colors=json.dumps([row[2] for row in observations]),
                                times=json.dumps([row[0] for row in observations])))
    csv_write(HERE/'results/temporal_miss_diagnosis.csv',records)
    counts=dict(n1_confirmed_n3_unconfirmed=len(records),fewer_than3_total=sum(r['observations']<3 for r in records),
                enough_total_but_fewer_than3_per_track=sum(r['observations']>=3 and r['max_observations_same_track']<3 for r in records))
    boundary=[]
    for name in ('n1_dedup','n2_dedup','n3_dedup'):
        rs=[r for r in rows if r['split']=='test' and r['basis']=='detected' and r['target']=='1' and r['config']==name
            and float(r['first_s'])>1. and float(r['last_s'])<durations[r['run']]-1.1]
        boundary.append(dict(config=name,target_episodes=len(rs),reached=sum(int(r['reached']) for r in rs),
                             recall=sum(int(r['reached']) for r in rs)/len(rs) if rs else None))
    csv_write(HERE/'results/boundary_sensitivity.csv',boundary)
    (HERE/'results/temporal_miss_summary.json').write_text(json.dumps(counts,indent=2)+'\n')
    print(json.dumps(counts))

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,default=HERE)
    main(parser.parse_args().root)
