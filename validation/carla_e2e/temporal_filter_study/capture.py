#!/usr/bin/env python3
"""Offscreen CARLA capture: one YOLO/HSV pass, all JPEG evidence, replay JSONL."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import random
import sys
import time
import traceback
from contextlib import ExitStack
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/'harness'))
spec = importlib.util.spec_from_file_location('study_capture_v1', str(HERE.parent/'continuous_ablation/run_continuous_ablation.py'))
v1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v1)

WEATHER = {
    'clear':dict(cloudiness=5., precipitation=0., wetness=0., sun_altitude_angle=60., sun_azimuth_angle=120.),
    'low_sun':dict(cloudiness=70., precipitation=0., wetness=0., sun_altitude_angle=8., sun_azimuth_angle=120.),
    'rain':dict(cloudiness=90., precipitation=65., precipitation_deposits=70., wetness=90., sun_altitude_angle=35., sun_azimuth_angle=120.)}
BLUEPRINTS = ['vehicle.tesla.model3','vehicle.audi.a2','vehicle.audi.tt','vehicle.dodge.charger2020',
              'vehicle.ford.mustang','vehicle.mercedes.coupe','vehicle.bmw.grandtourer','vehicle.lincoln.mkz2017','vehicle.nissan.patrol']


def write_json(path, value):
    tmp = Path(str(path)+'.tmp')
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
    tmp.replace(path)


def spawn(carla, world, tm, args):
    lib = world.get_blueprint_library()
    available = {bp.id for bp in lib.filter('vehicle.*')}
    types = [bp for bp in BLUEPRINTS if bp in available]
    assignments = v1.deterministic_assignments(types, v1.PALETTE, args.vehicles,args.seed)
    points = v1._sorted_spawn_points(world.get_map())
    random.Random(args.seed).shuffle(points)
    actors, plan = [], []
    for i,(model,color) in enumerate(assignments):
        bp = lib.find(model)
        bp.set_attribute('color',color)
        bp.set_attribute('role_name','uropclaw_validation_study_%03d'%i)
        actor = world.try_spawn_actor(bp,points[i])
        if actor is None:
            continue
        actor.set_autopilot(True,args.tm_port)
        actors.append(actor)
        plan.append(dict(actor_id=actor.id,slot=i,blueprint=model,color=color,is_target_color=color=='0,0,255'))
    return actors,plan


def transform_dict(t):
    return dict(location=dict(x=t.location.x,y=t.location.y,z=t.location.z),rotation=dict(pitch=t.rotation.pitch,yaw=t.rotation.yaw,roll=t.rotation.roll))


def select_camera(carla,world,actors,np,map_name,out):
    camera_file = HERE/'cameras'/('%s.json'%map_name)
    if camera_file.exists():
        return v1.transform_from_dict(carla,json.loads(camera_file.read_text())['transform'])
    if map_name=='Town10HD_Opt':
        manifest=json.loads(v1.DEFAULT_CAMERA_MANIFEST.read_text())
        transform=v1.transform_from_dict(carla,manifest['planned_scene']['camera']['transform'])
        scores=[]
    else:
        candidates=sorted(world.get_map().get_spawn_points(),key=lambda t:t.location.x**2+t.location.y**2)[:40:2]
        snapshot=world.get_snapshot()
        scores=[]
        best=None
        for p in candidates:
            yaw=math.radians(p.rotation.yaw)
            for side in (-1,1):
                loc=carla.Location(x=p.location.x-side*18*math.sin(yaw),y=p.location.y+side*18*math.cos(yaw),z=p.location.z+9)
                rot=carla.Rotation(pitch=-25,yaw=p.rotation.yaw-side*90)
                tr=carla.Transform(loc,rot)
                gt=v1.GroundTruth(carla,world,tr,800,600,90.,np)
                _,vis=gt.frame(actors,snapshot)
                # Geometric camera calibration only; no detector/HSV/outcome tuning.
                score=sum(min(1.,(b[2]-b[0])*(b[3]-b[1])/1200.) for b in vis.values())
                scores.append(dict(score=score,visible=len(vis),transform=transform_dict(tr)))
                if best is None or score>best[0]:
                    best=(score,tr)
        transform=best[1]
    camera_file.parent.mkdir(exist_ok=True)
    write_json(camera_file,dict(map=map_name,transform=transform_dict(transform),calibration='pilot geometry only; frozen before evaluation',scores=scores))
    return transform


def run(args):
    import carla
    import cv2
    import numpy as np
    import torch
    import ultralytics
    from ultralytics import YOLO
    from perception.color_filter import classify_color
    out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)
    if (out/'manifest.json').exists():
        old=json.loads((out/'manifest.json').read_text())
        if old.get('status')=='COMPLETE':
            print('ALREADY COMPLETE',out,flush=True)
            return
        raise RuntimeError('Refusing to overwrite partial capture; use a new output path')
    (out/'images').mkdir(exist_ok=True)
    manifest=dict(status='RUNNING',map=args.map,weather=args.weather,weather_parameters=WEATHER[args.weather],
                  vehicles=args.vehicles,seed=args.seed,split=args.split,frames=0,duration_s=args.duration,
                  dt_s=.1,camera_width=800,camera_height=600,fov=90,offscreen=True,no_rendering_mode=False,
                  detector=dict(weight='yolov8s.pt',sha256=hashlib.sha256(v1.DEFAULT_WEIGHT.read_bytes()).hexdigest(),conf=.4,iou=.45),
                  image_format='JPEG quality85; detector/HSV cached from uncompressed original input',
                  environment=dict(python=sys.version,torch=torch.__version__,ultralytics=ultralytics.__version__,gpu=torch.cuda.get_device_name(0)),
                  traffic=[])
    write_json(out/'manifest.json',manifest)
    client=carla.Client('127.0.0.1',2000)
    client.set_timeout(90.)
    world=client.get_world()
    if world.get_map().name.split('/')[-1]!=args.map:
        world=client.load_world(args.map)
    if list(world.get_actors().filter('vehicle.*')):
        raise RuntimeError('World contains vehicles; no automatic deletion of unowned actors')
    settings=world.get_settings()
    settings.no_rendering_mode=False
    world.apply_settings(settings)
    world.set_weather(carla.WeatherParameters(**WEATHER[args.weather]))
    tm=client.get_trafficmanager(args.tm_port)
    model=YOLO(str(v1.DEFAULT_WEIGHT))
    model.to('cuda:0')
    torch.set_num_threads(2)
    owned=[]
    camera=stream=None
    start=time.perf_counter()
    try:
        with ExitStack() as stack:
            stack.enter_context(v1.synchronous_mode(world,tm,args.seed,.1))
            def cleanup():
                manifest['cleanup']=v1.shutdown_scene_resources(stream,camera,owned,world,args.tm_port,30.)
            stack.callback(cleanup)
            actors,plan=spawn(carla,world,tm,args)
            owned.extend(actors)
            manifest['traffic']=plan
            manifest['actual_vehicles']=len(actors)
            if len(actors)<args.vehicles*.9:
                raise RuntimeError('Too many spawn failures')
            for _ in range(100):
                world.tick(30.)
            transform=select_camera(carla,world,actors,np,args.map,out)
            manifest['camera_transform']=transform_dict(transform)
            bp=world.get_blueprint_library().find('sensor.camera.rgb')
            for k,v in [('image_size_x','800'),('image_size_y','600'),('fov','90'),('sensor_tick','0.0')]:
                bp.set_attribute(k,v)
            camera=world.spawn_actor(bp,transform)
            owned.append(camera)
            stream=v1.SynchronousSensorStream(camera)
            stream.start()
            stream.wait_until_ready(world,60.,10.,20)
            for _ in range(10):
                _,img=stream.tick_and_wait(world,30.,10.)
                frame=np.frombuffer(img.raw_data,dtype=np.uint8).reshape(600,800,4)[:,:,:3].copy()
                model(frame,conf=.4,iou=.45,device=0,verbose=False)
            gt=v1.GroundTruth(carla,world,transform,800,600,90.,np)
            write_json(out/'manifest.json',manifest)
            t0=None
            with (out/'frames.jsonl').open('w') as f:
                for index in range(int(round(args.duration*10))):
                    before=time.perf_counter()
                    fid,img=stream.tick_and_wait(world,30.,10.)
                    snapshot=world.get_snapshot()
                    if fid != snapshot.frame:
                        raise RuntimeError('Sensor/snapshot frame mismatch')
                    sim=snapshot.timestamp.elapsed_seconds
                    t0=sim if t0 is None else t0
                    frame=np.frombuffer(img.raw_data,dtype=np.uint8).reshape(600,800,4)[:,:,:3].copy()
                    torch.cuda.synchronize()
                    tic=time.perf_counter()
                    result=model(frame,conf=.4,iou=.45,device=0,verbose=False)
                    torch.cuda.synchronize()
                    yolo_ms=(time.perf_counter()-tic)*1000
                    dets=[]
                    for r in result:
                        if r.boxes is None:
                            continue
                        for b in r.boxes:
                            cls=int(b.cls[0])
                            if cls in v1.TARGET_CLASSES:
                                dets.append(dict(bbox=[int(x) for x in b.xyxy[0].tolist()],class_id=cls,confidence=float(b.conf[0])))
                    tic=time.perf_counter()
                    for d in dets:
                        d['color']=classify_color(frame,d['bbox'])
                    hsv_ms=(time.perf_counter()-tic)*1000
                    projected,visible=gt.frame(actors,snapshot)
                    for d in dets:
                        d['actor']=v1.best_actor(d['bbox'],projected)
                    file='images/%06d.jpg'%index
                    if not cv2.imwrite(str(out/file),frame,[cv2.IMWRITE_JPEG_QUALITY,85]):
                        raise IOError('image write failed')
                    row=dict(index=index,carla_frame=fid,t=round(sim-t0,6),detections=dets,projected=projected,visible=visible,
                             yolo_ms=yolo_ms,hsv_ms=hsv_ms,capture_wall_ms=(time.perf_counter()-before)*1000,image=file)
                    f.write(json.dumps(row)+'\n')
                    manifest['frames']=index+1
                    if index%100==0:
                        f.flush()
                        print('%s frame %d/%d det=%d visible=%d elapsed=%.1fs'%(out.name,index,int(args.duration*10),len(dets),len(visible),time.perf_counter()-start),flush=True)
            manifest['status']='COMPLETE'
    except BaseException:
        manifest['status']='FAILED'
        manifest['error']=traceback.format_exc()
        raise
    finally:
        manifest['wall_s']=time.perf_counter()-start
        write_json(out/'manifest.json',manifest)
    print('COMPLETE',out,'wall_s',manifest['wall_s'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--map',default='Town10HD_Opt')
    p.add_argument('--weather',choices=list(WEATHER),default='clear')
    p.add_argument('--vehicles',type=int,default=70)
    p.add_argument('--seed',type=int,default=101)
    p.add_argument('--split',default='pilot')
    p.add_argument('--duration',type=float,default=180.)
    p.add_argument('--tm-port',type=int,default=8000)
    p.add_argument('--output',required=True)
    run(p.parse_args())
