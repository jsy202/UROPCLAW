"""Development-only painted-label image audit; never reads held-out recordings."""
import collections
import json
from pathlib import Path
import cv2
import numpy as np
from study import association_details, csv_write
HERE=Path(__file__).resolve().parent

def main(root=HERE):
    HERE=root
    out=HERE/'label_audit';out.mkdir(exist_ok=True)
    selected={}
    for directory in sorted((HERE/'runs').iterdir()):
        p=directory/'manifest.json'
        if not p.exists():continue
        manifest=json.loads(p.read_text())
        if manifest['split']!='dev' or manifest['status']!='COMPLETE':continue
        actors={a['actor_id']:a for a in manifest['traffic']}
        for line in (directory/'frames.jsonl').open():
            f=json.loads(line)
            for d in f['detections']:
                actor=association_details(d['bbox'],f['projected'])['actor']
                if actor is None or actor not in actors:continue
                a=actors[actor];b=d['bbox'];area=(b[2]-b[0])*(b[3]-b[1])
                key=(manifest['map'],manifest['weather'],a['blueprint'],a['color'])
                if key not in selected or area>selected[key]['area']:
                    selected[key]=dict(area=area,run=directory.name,frame=f['index'],image=str(directory/f['image']),bbox=b,
                                       model=a['blueprint'],paint=a['color'],hsv=d['color'],target=a['is_target_color'],map=manifest['map'],weather=manifest['weather'])
    rows=[]
    for row in selected.values():
        rows.append({k:v for k,v in row.items() if k!='bbox'})
    csv_write(out/'samples.csv',rows)
    for group in ('target','nontarget_blue_hsv'):
        samples=sorted([r for r in selected.values() if r['target']] if group=='target' else [r for r in selected.values() if not r['target'] and r['hsv']=='blue'],key=lambda r:(r['map'],r['weather'],r['model']))
        for page in range((len(samples)+15)//16):
            canvas=np.full((4*180,4*280,3),28,dtype=np.uint8)
            for index,r in enumerate(samples[page*16:page*16+16]):
                image=cv2.imread(r['image']);x1,y1,x2,y2=r['bbox'];crop=image[max(0,y1):y2,max(0,x1):x2]
                if not crop.size:continue
                scale=min(270/crop.shape[1],120/crop.shape[0]);resize=cv2.resize(crop,(max(1,int(crop.shape[1]*scale)),max(1,int(crop.shape[0]*scale))))
                x=(index%4)*280;y=(index//4)*180
                canvas[y:y+resize.shape[0],x:x+resize.shape[1]]=resize
                cv2.putText(canvas,r['model'].split('.')[-1]+' HSV:'+r['hsv'],(x+3,y+135),cv2.FONT_HERSHEY_SIMPLEX,.4,(255,255,255),1)
                cv2.putText(canvas,r['map']+' '+r['weather'],(x+3,y+152),cv2.FONT_HERSHEY_SIMPLEX,.36,(255,255,255),1)
                cv2.putText(canvas,'paint '+r['paint'],(x+3,y+169),cv2.FONT_HERSHEY_SIMPLEX,.38,(255,255,255),1)
            cv2.imwrite(str(out/('%s_page%d.jpg'%(group,page))),canvas)
    print('AUDIT',len(rows),'model/color/condition samples from dev only')

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,default=HERE)
    main(parser.parse_args().root)
