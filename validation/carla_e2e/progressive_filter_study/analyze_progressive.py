"""Progressive filter additions, all6000frame inputs held constant; no VLM calls."""
import argparse
import collections
import itertools
import json
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
REFERENCE=HERE.parent/'temporal_filter_study'
sys.path.insert(0,str(REFERENCE))


def configurations():
    import study
    out=study.configurations()
    for architecture in ('early_hsv','late_hsv'):
        out.append(dict(name='no_temporal_'+architecture,family='order_without_temporal',n=1,rule='current',
                        hsv=True,temporal=False,dedup=True,architecture=architecture))
    return out


def expected_cells():
    return set(itertools.product(('Town10HD_Opt',),('clear','low_sun','rain'),(30,70),(101,102,201,202,203)))


def validate_schedule(root):
    import study
    paths=sorted((root/'runs').glob('*/manifest.json'))
    actual=[]
    for p in paths:
        m=json.loads(p.read_text())
        cell=(m['map'],m['weather'],m['vehicles'],m['seed'])
        if m['status']!='COMPLETE' or m['frames']!=6000 or m['duration_s']!=600 or m['dt_s']!=.1:
            raise ValueError('Expected6000frames/600s/10Hz COMPLETE: '+str(p))
        if m['split']!=('dev' if m['seed']<200 else 'test'):raise ValueError('split mismatch')
        actual.append(cell)
    if len(actual)!=30 or set(actual)!=expected_cells():raise ValueError('missing or duplicate condition')
    return [p.parent for p in paths]


def temporal_validated(rows,cis,selected):
    if not selected or selected=='n1_dedup':return False
    chosen=rows[selected];base=rows['factor_101'];interval=cis[selected]
    return (float(interval['recall_diff_ci_low'])>=-.02 and chosen['confirm_p95_s'] not in ('',None)
            and float(chosen['confirm_p95_s'])<=.5 and int(chosen['requests'])<int(base['requests']))


def main(root=HERE):
    import numpy as np
    import study
    import analyze as old
    import make_cases
    runs=validate_schedule(root)
    output=root/'results';output.mkdir(exist_ok=True)
    summaries=[];scores=[]
    for split in ('dev','test'):
        for directory in runs:
            manifest=json.loads((directory/'manifest.json').read_text())
            if manifest['split']!=split:continue
            print('REPLAY',split,directory.name,flush=True)
            s,e,_=study.replay(directory,configurations());summaries.extend(s);scores.extend(e)
        aggregate=old.aggregate(summaries,scores)
        study.csv_write(output/'aggregate.csv',aggregate)
        if split=='dev':
            selected=old.choose(aggregate)
            selection=dict(selected=selected,based_on='12development6000frame recordings only',
                           criteria='loss<=2pp vsN1;confirmationp95<=.5s;min non-target+unassociated thenrequests thenN')
            p=output/'dev_selection.json'
            if p.exists():
                if json.loads(p.read_text())['selected']!=selected:raise ValueError('Frozen dev choice changed')
            else:p.write_text(json.dumps(selection,indent=2)+'\n')
            print('FROZEN DEV SELECTION',selected,flush=True)
    study.csv_write(output/'per_recording.csv',summaries)
    study.csv_write(output/'episodes.csv',scores)
    study.csv_write(output/'paired_delays.csv',old.paired_delays(scores))
    study.csv_write(output/'paired_confidence_intervals.csv',old.paired_ci(summaries,'dev')+old.paired_ci(summaries,'test'))
    study.csv_write(output/'stage_paired_confidence_intervals.csv',old.paired_ci(summaries,'test',base='factor_101'))
    strata=[]
    for town,weather,vehicles in sorted({(r['map'],r['weather'],r['vehicles']) for r in summaries}):
        ss=[r for r in summaries if (r['map'],r['weather'],r['vehicles'])==(town,weather,vehicles)]
        ee=[r for r in scores if (r['map'],r['weather'],r['vehicles'])==(town,weather,vehicles)]
        for r in old.aggregate(ss,ee):r.update(map=town,weather=weather,vehicles=vehicles);strata.append(r)
    study.csv_write(output/'stratified.csv',strata)
    old.plots(aggregate,output);old.evidence(runs,output)
    make_cases.HERE=root;make_cases.main()
    timings=[]
    for directory in runs:
        frames=[json.loads(line) for line in (directory/'frames.jsonl').open()]
        m=json.loads((directory/'manifest.json').read_text())
        timings.append(dict(run=directory.name,split=m['split'],frames=len(frames),wall_s=m['wall_s'],
                            yolo_p50_ms=old.percentile([f['yolo_ms'] for f in frames],50),
                            yolo_p95_ms=old.percentile([f['yolo_ms'] for f in frames],95),
                            hsv_p95_ms=old.percentile([f['hsv_ms'] for f in frames],95)))
    study.csv_write(output/'timings.csv',timings)
    print('ALL28 COMPARISONS COMPLETE',flush=True)

if __name__=='__main__':main()
