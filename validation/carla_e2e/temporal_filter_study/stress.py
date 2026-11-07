"""Deterministic synthetic stress probes. These are NOT CARLA performance data."""
from pathlib import Path
import json
from study import Branch, Confirm, configurations, csv_write
HERE=Path(__file__).resolve().parent


def run(root=HERE):
    HERE=root
    rows=[]
    for n in (1,2,3,5,7,10):
        for length in (1,2,3,5,7,10):
            for gap in (.1,.9,1.1):
                c=Confirm(n,'current')
                emitted=[i*gap for i in range(length) if c.update(0,'blue',i*gap)=='blue']
                rows.append(dict(kind='short_exposure',n=n,rule='current',observations=length,gap_s=gap,
                                 reached=int(bool(emitted)),first_confirm_s=emitted[0] if emitted else None))
    csv_write(HERE/'stress_exposure.csv',rows)
    votes=[]
    seqs=[('target_with_unknown',['blue','unknown','unknown']),
          ('nontarget_single_error',['blue','red','red']),
          ('nontarget_error_plus_unknown',['blue','unknown','unknown']),
          ('unstable_then_target',['red','red','blue','blue','blue']),
          ('target_one_error',['blue','red','blue'])]
    for name,colors in seqs:
        for rule in ('current','full','unanimous','sliding'):
            c=Confirm(3,rule)
            outputs=[c.update(0,color,i/10.) for i,color in enumerate(colors)]
            votes.append(dict(sequence=name,rule=rule,colors=','.join(colors),outputs=json.dumps(outputs),
                              blue_confirmations=outputs.count('blue')))
    csv_write(HERE/'stress_votes.csv',votes)
    outcomes=[]
    config=next(c for c in configurations() if c['name']=='n3_dedup')
    for distance,guard in ((65,False),(150,False),(65,True),(150,True)):
        b=Branch(dict(config,dedup_active_guard=guard))
        events=[]
        for i in range(10):
            dets=[dict(bbox=[100,100,160,140],class_id=2,confidence=.9,color='blue'),
                  dict(bbox=[100+distance,100,160+distance,140],class_id=2,confidence=.9,color='blue')]
            events.extend(dict(e,t=i/10.) for e in b.process(dets,i/10.))
        outcomes.append(dict(probe='two_distinct_simultaneous_targets',distance_px=distance,active_guard=guard,
                             candidates=sum(e['kind']=='candidate' for e in events),requests=sum(e['kind']=='request' for e in events),
                             requesting_tracks=json.dumps(sorted({e['track'] for e in events if e['kind']=='request'})),
                             reasons=json.dumps([e.get('reason') for e in events if e['kind']=='suppressed'])))
    csv_write(HERE/'stress_dedup.csv',outcomes)
    print(json.dumps(outcomes,indent=2))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=HERE)
    run(p.parse_args().root)
