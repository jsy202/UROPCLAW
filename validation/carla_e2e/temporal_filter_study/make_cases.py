"""Create inspectable evidence from saved CARLA images and replay differences."""
import collections
import csv
import json
from pathlib import Path
import cv2
import numpy as np
from study import csv_write,association_details
HERE=Path(__file__).resolve().parent


def load_frames(path):
    frames=[json.loads(line) for line in path.open()]
    for f in frames:
        for d in f['detections']:
            d['actor']=association_details(d['bbox'],f['projected'])['actor']
    return frames


def main():
    out=HERE/'results/evidence';out.mkdir(parents=True,exist_ok=True)
    rows=list(csv.DictReader((HERE/'results/episodes.csv').open()))
    episodes={}
    for r in rows:
        if r['split']=='test' and r['basis']=='detected':
            episodes.setdefault((r['run'],r['episode']),{})[r['config']]=r
    wanted=collections.defaultdict(list)
    for key,by in episodes.items():
        a,b=by['n1_dedup'],by['n3_dedup']
        if a['target']=='1' and a['reached']=='1' and b['reached']=='0':wanted['N1_reached_N3_missed'].append((key,by))
        if a['target']=='1' and a['reached']=='0' and b['reached']=='1':wanted['N3_reached_N1_missed'].append((key,by))
        if b['target']=='1' and b['reached']=='0' and by['dedup_active_guard']['reached']=='1':wanted['guard_recovered'].append((key,by))
    cases=[]
    for kind,options in wanted.items():
        for key,by in options[:3]:
            run,ep=key;row=by['n3_dedup'];actor=int(row['actor'])
            p=HERE/'runs'/run
            frames=load_frames(p/'frames.jsonl')
            candidates=[f for f in frames if float(row['first_s'])<=f['t']<=float(row['last_s']) and any(d.get('actor')==actor for d in f['detections'])]
            if not candidates:continue
            frame=max(candidates,key=lambda f:max([(d['bbox'][2]-d['bbox'][0])*(d['bbox'][3]-d['bbox'][1]) for d in f['detections'] if d.get('actor')==actor] or [0]))
            image=cv2.imread(str(p/frame['image']))
            for d in frame['detections']:
                if d.get('actor')!=actor:continue
                b=d['bbox'];cv2.rectangle(image,(b[0],b[1]),(b[2],b[3]),(0,200,255),2)
                cv2.putText(image,'HSV='+d['color'],(b[0],max(15,b[1]-4)),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,200,255),1)
            title='%s | actor%d | t=%.1fs'%(kind,actor,frame['t'])
            cv2.putText(image,title,(8,22),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,0,0),3)
            cv2.putText(image,title,(8,22),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1)
            name='%s_%s_ep%s.jpg'%(kind,run,ep);cv2.imwrite(str(out/name),image)
            cases.append(dict(kind=kind,run=run,episode=ep,actor=actor,frame=frame['index'],time_s=frame['t'],image=name,
                              n1_reached=by['n1_dedup']['reached'],n3_reached=row['reached'],guard_reached=by['dedup_active_guard']['reached'],
                              n1_delay_s=by['n1_dedup']['request_delay_s'],n3_delay_s=row['request_delay_s']))
    # Typical valid target and wrong-color/unassociated requests.
    examples=collections.Counter()
    for p in sorted((HERE/'runs').iterdir()):
        m=json.loads((p/'manifest.json').read_text())
        if m['split']!='test':continue
        targets={a['actor_id'] for a in m['traffic'] if a['is_target_color']}
        frames=None
        for line in (p/'analysis/events.jsonl').open():
            e=json.loads(line)
            if e['config']!='n3_dedup' or e['kind']!='request':continue
            kind='correct_target_request' if e['actor'] in targets else 'ambiguous_request' if e['association']['status']=='ambiguous' else 'unassociated_request' if e['actor'] is None else 'wrong_color_request'
            if examples[kind]>=3:continue
            if frames is None:frames=load_frames(p/'frames.jsonl')
            f=frames[e['frame']];img=cv2.imread(str(p/f['image']));b=e['bbox']
            cv2.rectangle(img,(b[0],b[1]),(b[2],b[3]),(0,200,255),2)
            cv2.putText(img,kind+' t=%.1fs'%e['t'],(8,22),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),2)
            name=kind+'_'+p.name+'_f%d.jpg'%e['frame'];cv2.imwrite(str(out/name),img)
            x1,y1,x2,y2=b
            crop=img[max(0,y1):max(0,y2),max(0,x1):max(0,x2)]
            if crop.size:cv2.imwrite(str(out/('crop_'+name)),crop)
            examples[kind]+=1
            cases.append(dict(kind=kind,run=p.name,episode='',actor=e['actor'],frame=e['frame'],time_s=e['t'],image=name,n1_reached='',n3_reached='',guard_reached='',n1_delay_s='',n3_delay_s=''))
    csv_write(out/'cases.csv',cases)
    print('Saved',len(cases),'cases')

if __name__=='__main__':main()
