"""Validate all accepted frames and fingerprint every saved evidence image."""
import hashlib
import json
from pathlib import Path
import cv2
from study import csv_write,validate_frames
HERE=Path(__file__).resolve().parent

def main(root=HERE,expected_recordings=40):
    HERE=root
    rows=[]
    for directory in sorted((HERE/'runs').iterdir()):
        manifest=json.loads((directory/'manifest.json').read_text())
        assert manifest['status']=='COMPLETE'
        frames=[json.loads(line) for line in (directory/'frames.jsonl').open()]
        validate_frames(directory,manifest,frames)
        images=sorted((directory/'images').glob('*.jpg'))
        assert len(images)==manifest['frames'] and len({f['image'] for f in frames})==manifest['frames']
        image_set=hashlib.sha256();total_bytes=0
        with (directory/'images.sha256').open('w') as output:
            for index,path in enumerate(images):
                content=path.read_bytes();total_bytes+=len(content)
                assert content[:2]==b'\xff\xd8' and content[-2:]==b'\xff\xd9'
                digest=hashlib.sha256(content).hexdigest()
                output.write(digest+'  images/'+path.name+'\n')
                image_set.update((path.name+digest).encode())
                if index%100==0 or index==len(images)-1:
                    image=cv2.imread(str(path));assert image is not None and image.shape==(600,800,3)
        rows.append(dict(run=directory.name,split=manifest['split'],map=manifest['map'],weather=manifest['weather'],
                         vehicles_requested=manifest['vehicles'],vehicles_spawned=manifest['actual_vehicles'],frames=len(frames),images=len(images),
                         image_bytes=total_bytes,image_set_sha256=image_set.hexdigest(),
                         frames_sha256=hashlib.sha256((directory/'frames.jsonl').read_bytes()).hexdigest(),
                         manifest_sha256=hashlib.sha256((directory/'manifest.json').read_bytes()).hexdigest(),
                         actor_cleanup=manifest['cleanup']['destroyed'],weight_sha256=manifest['detector']['sha256']))
        print('VERIFIED',len(rows),directory.name,flush=True)
    assert len(rows)==expected_recordings and len({r['frames'] for r in rows})==1
    assert sum(r['frames'] for r in rows)==expected_recordings*rows[0]['frames']
    csv_write(HERE/'results/archive_inventory.csv',rows)
    summary=dict(recordings=len(rows),frames=sum(r['frames'] for r in rows),images=sum(r['images'] for r in rows),
                 image_bytes=sum(r['image_bytes'] for r in rows),actual_vlm_execution_allowed=False,
                 earlier_connectivity_probe_excluded=1)
    (HERE/'results/archive_verification.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('ARCHIVE VERIFIED',json.dumps(summary),flush=True)

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,default=HERE)
    p.add_argument("--expected-recordings",type=int,default=40)
    args=p.parse_args()
    main(args.root,args.expected_recordings)
