"""Independent semantic checks for the validation-only study."""
import importlib.util
import sys
from pathlib import Path
import pytest

PATH = Path(__file__).resolve().parents[2] / 'validation/carla_e2e/temporal_filter_study/study.py'

def load():
    assert PATH.exists(), 'study implementation is missing'
    spec = importlib.util.spec_from_file_location('temporal_filter_study', str(PATH))
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def test_unknown_votes_do_not_count_as_two_target_votes():
    m = load()
    current = m.Confirm(3, 'current')
    strict = m.Confirm(3, 'full')
    for i, c in enumerate(['blue', 'unknown', 'unknown']):
        a, b = current.update(0, c, i / 10), strict.update(0, c, i / 10)
    assert a == 'blue'
    assert b is None


def test_gap_resets_and_batch_restarts():
    m = load()
    c = m.Confirm(3, 'current')
    assert c.update(0, 'blue', 0) is None
    assert c.update(0, 'blue', 1.1) is None
    assert c.update(0, 'blue', 1.2) is None
    assert c.update(0, 'blue', 1.3) == 'blue'
    assert c.update(0, 'blue', 1.4) is None


def test_sliding_can_recover_without_waiting_for_next_batch():
    m = load()
    c = m.Confirm(3, 'sliding')
    out = [c.update(0, x, i / 10) for i, x in enumerate(['red', 'red', 'blue', 'blue'])]
    assert out == [None, None, 'red', 'blue']


def test_current_rules_equal_production_for_all_window_sizes():
    m = load()
    from perception.temporal_confirm import TemporalConfirm
    import random
    rng = random.Random(9)
    for n in (1, 2, 3, 5, 7, 10):
        original, study = TemporalConfirm(n), m.Confirm(n, 'current')
        t = 0
        for _ in range(500):
            t += rng.choice([.1, .1, .1, 1.2])
            tid, color = rng.randrange(3), rng.choice(['blue', 'red', 'unknown', 'green'])
            a = original.update(tid, color, t)
            assert study.update(tid, color, t) == (a['color'] if a else None)


def test_config_matrix_is_unique_and_complete():
    m = load()
    configs = m.configurations()
    assert len({c['name'] for c in configs}) == len(configs)
    assert {c['n'] for c in configs if c['family'] == 'window'} == {1, 2, 3, 5, 7, 10}
    assert sum(c['family'] == 'factorial' for c in configs) == 8


def test_episodes_separate_revisits_and_include_unconfirmed_misses():
    m = load()
    frames = [dict(t=t, visible={'1':[0,0,20,20]}, detections=[dict(bbox=[0,0,20,20], actor=1)])
              for t in [0., .1, 2., 2.1]]
    episodes, associations = m.episodes(frames, {1: True})
    assert len(episodes) == 2
    rows = m.score_episodes(episodes, associations, [{'frame':0,'kind':'request','actor':1}], 'x')
    assert rows[0]['reached'] == 1
    assert rows[0]['request_delay_s'] == 0
    assert rows[1]['reached'] == 0
    assert rows[1]['request_delay_s'] is None


def test_empty_frame_does_not_add_temporal_evidence(monkeypatch):
    m = load()
    b = m.Branch(dict(name='test',family='window',n=3,hsv=True,temporal=True,dedup=True,rule='current',architecture='current'))
    det = dict(bbox=[0,0,40,40], class_id=2, confidence=.9, color='blue')
    assert b.process([det], 0) == []
    for t in [.1,.2,.3]:
        assert b.process([], t) == []
    assert b.process([det], .4) == []
    assert any(e['kind'] == 'request' for e in b.process([det], .5))


def test_current_branch_matches_existing_shadow(monkeypatch):
    m = load()
    shadow_path = PATH.parent.parent / 'continuous_ablation_v2/branches.py'
    spec = importlib.util.spec_from_file_location('existing_v2_shadow', str(shadow_path))
    shadow = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shadow)
    from perception.yolo_detector import Detection
    from perception.iou_tracker import IoUTracker
    from perception.temporal_confirm import TemporalConfirm
    from perception.deduplicator import Deduplicator
    c = next(c for c in m.configurations() if c['name']=='n3_dedup')
    ours = m.Branch(c)
    old = shadow.ShadowBranch('full',IoUTracker,TemporalConfirm,Deduplicator)
    import random
    rng = random.Random(18)
    for i in range(100):
        observations=[]
        for x in (20,400):
            if rng.random()>.2:
                observations.append(dict(bbox=[x+i,20,x+i+50,70],class_id=2,confidence=.9,color=rng.choice(['blue','blue','red','unknown'])))
        a=ours.process(observations,i/10)
        b=old.process([Detection(d['bbox'],2,'car',.9) for d in observations],[d['color'] for d in observations],i/10)
        assert sum(e['kind']=='candidate' for e in a)==old.counters['candidates_raised']-getattr(old,'previous_candidates',0)
        old.previous_candidates=old.counters['candidates_raised']
        assert [(e['track'],e['kind']=='request') for e in a if e['kind']!='candidate']==[(e['track_id'],e['kind']=='vlm_trigger') for e in b]


def test_late_hsv_tracking_does_not_use_color_before_confirmation():
    m=load()
    b=m.Branch(next(c for c in m.configurations() if c['name']=='late_hsv'))
    d=dict(bbox=[0,0,40,40],class_id=2,confidence=.9,color='blue')
    b.process([d],0)
    assert b.tracker._tracks[0].color_history==['unknown']
    b.process([d],.1)
    assert any(e['kind']=='request' for e in b.process([d],.2))


def test_branch_does_not_change_production_tracker_clock():
    m=load()
    import perception.iou_tracker as tracker
    original=tracker.time
    b=m.Branch(next(c for c in m.configurations() if c['name']=='n3_dedup'))
    b.process([dict(bbox=[0,0,40,40],class_id=2,confidence=.9,color='blue')],0)
    assert tracker.time is original


def test_equal_overlapping_ground_truth_is_ambiguous():
    m=load()
    assert m.associate([0,0,40,40],{'1':[0,0,40,40],'2':[0,0,40,40]}) is None
    detail=m.association_details([0,0,40,40],{'1':[0,0,40,40],'2':[0,0,40,40]})
    assert detail['status']=='ambiguous' and len(detail['matches'])==2


def test_detection_cannot_bridge_two_gt_visible_episodes():
    m=load()
    frames=[dict(t=i/10.,visible={'1':[0,0,20,20]} if i in (0,13) else {},
                 detections=[dict(bbox=[0,0,20,20],actor=1)]) for i in range(14)]
    visible,_=m.episodes(frames,{1:True},basis='visible')
    detected,_=m.episodes(frames,{1:True},basis='detected')
    assert len(visible)==2
    assert len(detected)==1


def test_capture_validation_rejects_short_and_noncontiguous(tmp_path):
    m=load()
    frames=[dict(index=0,carla_frame=1,t=0,image='0.jpg')]
    (tmp_path/'0.jpg').write_bytes(b'test')
    with pytest.raises(ValueError,match='1800'):
        m.validate_frames(tmp_path,{'frames':1,'duration_s':180},frames)


def test_guard_keeps_simultaneous_distinct_target_tracks_separate():
    m=load()
    base=next(c for c in m.configurations() if c['name']=='n3_dedup')
    base=dict(base,dedup_active_guard=True)
    b=m.Branch(base)
    events=[]
    for i in range(3):
        ds=[dict(bbox=[x,100,x+60,140],class_id=2,confidence=.9,color='blue') for x in (100,165)]
        events.extend(b.process(ds,i/10))
    assert sum(e['kind']=='request' for e in events)==2


def load_queue_model():
    p=PATH.parent/'queue_model.py'
    assert p.exists(),'queue model implementation missing'
    spec=importlib.util.spec_from_file_location('study_queue_model',str(p));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_serial_vlm_queue_wait_and_duplicate_processing():
    m=load_queue_model()
    a=dict(t=0.,track=0,color='blue',bbox=[0,0,40,40])
    duplicate=dict(a,t=.1)
    b=dict(t=.2,track=1,color='blue',bbox=[400,0,440,40])
    result=m.simulate([a,duplicate,b],[10.],dedup=True)
    assert len(result['calls'])==2 and result['suppressed']==1
    assert result['calls'][1]['wait_s']==pytest.approx(9.8)
    assert result['calls'][1]['finished_s']==20.


def test_bounded_vlm_queue_drops_waiting_candidate():
    m=load_queue_model()
    events=[dict(t=t,track=i,color='blue',bbox=[i*200,0,i*200+40,40]) for i,t in enumerate([0,.1,.2])]
    result=m.simulate(events,[10.],capacity=1,dedup=False)
    assert len(result['calls'])==2 and result['dropped']==1


def test_vlm_negative_controls_skip_ambiguous_raw_capture_labels(tmp_path,monkeypatch):
    import json
    p=PATH.parent/'real_vlm.py'
    monkeypatch.syspath_prepend(str(PATH.parent))
    spec=importlib.util.spec_from_file_location('study_real_vlm',str(p));v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
    monkeypatch.setattr(v,'HERE',tmp_path)
    (tmp_path/'results').mkdir();(tmp_path/'results/dev_selection.json').write_text('{"selected":"n3_dedup"}')
    run=tmp_path/'runs/test';(run/'analysis').mkdir(parents=True)
    m=dict(split='test',map='map',weather='clear',traffic=[dict(actor_id=1,is_target_color=True),dict(actor_id=2,is_target_color=False)])
    (run/'manifest.json').write_text(json.dumps(m));(run/'analysis/events.jsonl').write_text('')
    frame=dict(index=0,detections=[dict(actor=2,bbox=[0,0,40,40])],projected={'1':[0,0,40,40],'2':[0,0,40,40]})
    (run/'frames.jsonl').write_text(json.dumps(frame)+'\n')
    assert v.select()==[]


def test_missing_cleanup_cannot_pass_capture_validation(tmp_path):
    m=load()
    frames=[dict(index=i,carla_frame=i+1,t=i/10.,image='one.jpg') for i in range(1800)]
    (tmp_path/'one.jpg').write_bytes(b'image')
    with pytest.raises(ValueError,match='cleanup'):
        m.validate_frames(tmp_path,{'frames':1800,'duration_s':180},frames)


def test_measured_queue_replay_uses_real_worker_and_records_wait(tmp_path,monkeypatch):
    p=PATH.parent/'measured_queue.py'
    assert p.exists(),'measured queue implementation missing'
    monkeypatch.syspath_prepend(str(PATH.parent))
    spec=importlib.util.spec_from_file_location('study_measured_queue',str(p));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    from queue import Queue
    import threading,time
    trace={0:dict(arrived=time.monotonic(),status='queued'),1:dict(arrived=time.monotonic(),status='queued')}
    source=m.ObservedQueue(trace,maxsize=20)
    stop=threading.Event();results=Queue();metrics={}
    def fake_verify(self,candidate,mission,crop_path):
        time.sleep(.04)
        return dict(confirmed=True,confidence='high')
    monkeypatch.setattr(m.pipeline.OpenClawWorker,'_llm_verify',fake_verify)
    monkeypatch.setattr(m.pipeline.OpenClawWorker,'_save_crop',lambda *args:None)
    monkeypatch.setattr(m.pipeline,'read_mission',lambda:dict(target_color='blue'))
    worker=m.MeasuredWorker(stop,source,results,metrics,trace)
    for i in range(2):
        source.put_nowait(dict(profile_id=i,camera_id='c',agent_id='a',track_id=i,color='blue',bbox=[i*200,0,i*200+40,40]))
    worker.start()
    assert results.get(timeout=2)['profile_id']==0
    assert results.get(timeout=2)['profile_id']==1
    stop.set();worker.join(timeout=2)
    assert trace[0]['ended']-trace[0]['started']>=.035
    assert trace[1]['dequeued']-trace[1]['arrived']>=.035
    assert not worker.is_alive()


def test_measured_queue_refuses_cached_result_from_another_clip(tmp_path,monkeypatch):
    p=PATH.parent/'measured_queue.py';monkeypatch.syspath_prepend(str(PATH.parent))
    spec=importlib.util.spec_from_file_location('study_measured_queue_cache',str(p));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    monkeypatch.setattr(m,'HERE',tmp_path)
    out=tmp_path/'results/measured_queue/n3_dedup';out.mkdir(parents=True)
    (out/'summary.json').write_text('{"clip":"old_clip"}')
    with pytest.raises(ValueError,match='clip'):
        m.run('n3_dedup','different_clip')


def test_server_cleanup_signals_group_even_if_wrapper_already_exited(monkeypatch):
    from types import SimpleNamespace
    p=PATH.parent/'server_lifecycle.py'
    assert p.exists(),'server lifecycle implementation missing'
    spec=importlib.util.spec_from_file_location('study_server_lifecycle',str(p));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    signals=[]
    monkeypatch.setattr(m.os,'killpg',lambda pid,sig:signals.append((pid,sig)))
    monkeypatch.setattr(m,'ports_free',lambda:True)
    proc=SimpleNamespace(pid=123,poll=lambda:0,wait=lambda timeout:0)
    m.stop_process_group(proc)
    assert signals==[(123,m.signal.SIGTERM)]


def test_server_readiness_loads_and_checks_actual_map():
    from types import SimpleNamespace
    p=PATH.parent/'server_lifecycle.py'
    spec=importlib.util.spec_from_file_location('study_server_map',str(p));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    loaded=[]
    world=lambda name:SimpleNamespace(get_map=lambda:SimpleNamespace(name='Carla/Maps/'+name))
    client=SimpleNamespace(get_world=lambda:world('Town10HD_Opt'),load_world=lambda town:(loaded.append(town) or world(town)))
    assert m.ensure_map(client,'Town03_Opt').get_map().name.endswith('Town03_Opt')
    assert loaded==['Town03_Opt']


def test_automatic_pipeline_excludes_real_vlm_by_user_instruction():
    import ast,json
    policy=json.loads((PATH.parent/'execution_policy.json').read_text())
    assert policy['allow_real_vlm'] is False
    tree=ast.parse((PATH.parent/'postprocess.py').read_text())
    tasks=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.For) and isinstance(node.target,ast.Tuple):
            if [x.id for x in node.target.elts if isinstance(x,ast.Name)]==['script','args']:
                tasks=ast.literal_eval(node.iter)
    assert tasks
    assert not {'real_vlm.py','measured_queue.py'}.intersection(name for name,_ in tasks)


def test_ten_minute_archive_accepts_exactly6000_at10hz(tmp_path):
    m=load()
    (tmp_path/'frame.jpg').write_bytes(b'image')
    frames=[dict(index=i,carla_frame=20+i,t=i/10.,image='frame.jpg') for i in range(6000)]
    manifest=dict(frames=6000,duration_s=600,traffic=[],cleanup=dict(attempted=1,destroyed=1,failed_actor_ids=[]))
    m.validate_frames(tmp_path,manifest,frames)
    frames[200]['t']+=.1
    with pytest.raises(ValueError,match='noncontiguous'):
        m.validate_frames(tmp_path,manifest,frames)
