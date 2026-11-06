"""Validation-only replay. Branches never receive actor IDs or evaluation labels."""
from __future__ import annotations
import collections
import csv
import itertools
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'harness'))
from perception.temporal_confirm import TemporalConfirm
from perception.iou_tracker import IoUTracker
import perception.iou_tracker as tracker_module
from perception.deduplicator import Deduplicator, _centre, _diagonal
from perception.yolo_detector import Detection


class Confirm:
    def __init__(self, n=3, rule='current'):
        self.n, self.rule = n, rule
        self.original = TemporalConfirm(n)
        self.pending = {}

    def update(self, tid, color, timestamp):
        if self.rule == 'current':
            out = self.original.update(tid, color, timestamp)
            return out['color'] if out else None
        seq = self.pending.setdefault(tid, [])
        if seq and timestamp - seq[-1][0] > 1.0:
            seq.clear()
        seq.append((timestamp, color))
        if self.rule == 'sliding':
            del seq[:-self.n]
        if len(seq) < self.n:
            return None
        votes = collections.Counter(c for _, c in seq if c != 'unknown')
        best, count = votes.most_common(1)[0] if votes else (None, 0)
        threshold = self.n if self.rule == 'unanimous' else (self.n * .6)
        result = best if best and count >= threshold else None
        if self.rule != 'sliding':
            del self.pending[tid]
        return result


def configurations():
    base = dict(hsv=True, temporal=True, dedup=True, rule='current', architecture='current')
    out = []
    for n, dedup in itertools.product((1, 2, 3, 5, 7, 10), (True, False)):
        out.append(dict(base, name='n%d_%s' % (n, 'dedup' if dedup else 'raw'), family='window', n=n, dedup=dedup))
    for rule in ('full', 'unanimous', 'sliding'):
        out.append(dict(base, name='rule_' + rule, family='rules', n=3, rule=rule))
    for h, t, d in itertools.product((False, True), repeat=3):
        out.append(dict(base, name='factor_%d%d%d' % (h,t,d), family='factorial', n=3, hsv=h, temporal=t, dedup=d))
    for architecture in ('early_hsv', 'late_hsv'):
        out.append(dict(base, name=architecture, family='architecture', n=3, architecture=architecture))
    out.append(dict(base,name='dedup_active_guard',family='exploratory',n=3,dedup_active_guard=True))
    return out


class SimClock:
    now = 0.
    def time(self):
        return self.now


class ActiveGuardDedup(Deduplicator):
    """Exploratory: a currently matched track cannot be another track's fragment."""
    def __init__(self):
        super().__init__()
        self.active_tracks=set()

    def _find_continuation(self,camera_id,color,bbox,now):
        active_keys={self._track_target[(camera_id,tid)] for tid in self.active_tracks if (camera_id,tid) in self._track_target}
        best_key,best_distance=None,None
        cx,cy=_centre(bbox)
        for key,target in self._targets.items():
            if key in active_keys or key[0]!=camera_id or target.color!=color or now-target.last_seen>2.:
                continue
            tx,ty=_centre(target.bbox)
            distance=((cx-tx)**2+(cy-ty)**2)**.5
            if distance<=_diagonal(target.bbox) and (best_distance is None or distance<best_distance):
                best_key,best_distance=key,distance
        return best_key


class Branch:
    def __init__(self, config):
        self.config = config
        self.tracker, self.confirm, self.dedup = IoUTracker(), Confirm(config['n'], config['rule']), Deduplicator()
        if config.get('dedup_active_guard'):
            self.dedup=ActiveGuardDedup()
        self.clock = SimClock()

    def process(self, observations, timestamp):
        # This interface accepts only production-observable data; evaluation is external.
        c = self.config
        if c['architecture'] == 'early_hsv':
            observations = [d for d in observations if d['color'] == 'blue']
        if not observations:  # mirrors production's skip of empty detector frames
            return []
        self.clock.now = timestamp
        detections = [Detection(list(d['bbox']), int(d.get('class_id', 2)), 'car', float(d.get('confidence', 1)))
                      for d in observations]
        colors = ['unknown' if c['architecture']=='late_hsv' else d['color'] if c['hsv'] else 'vehicle' for d in observations]
        previous_clock = tracker_module.time
        try:
            tracker_module.time = self.clock
            tracks = self.tracker.update(detections, colors)
        finally:
            tracker_module.time = previous_clock
        if isinstance(self.dedup,ActiveGuardDedup):
            self.dedup.active_tracks={tid for tid,tr in tracks.items() if not tr.disappeared}
        events = []
        for tid, track in tracks.items():
            if track.disappeared:
                continue
            color = track.color_history[-1]
            evidence_color = 'vehicle' if c['architecture'] == 'late_hsv' else color
            confirmed = self.confirm.update(tid, evidence_color, timestamp) if c['temporal'] else evidence_color
            if confirmed is None:
                continue
            if c['architecture'] == 'late_hsv':
                confirmed = next(d['color'] for d in observations if d['bbox']==track.bbox)
            if c['hsv'] and confirmed != 'blue':
                continue
            common = dict(track=tid, color=confirmed, bbox=list(track.bbox))
            events.append(dict(common, kind='candidate'))
            allowed, reason = True, 'dedup_off'
            if c['dedup']:
                self.dedup.cleanup(timestamp)
                allowed, reason = self.dedup.should_verify_target('camera', tid, confirmed, track.bbox, timestamp)
            if c['dedup']:
                common['target_key']=list(self.dedup._track_target.get(('camera',tid),('camera',tid)))
            events.append(dict(common, kind='request' if allowed else 'suppressed', reason=reason))
        return events


def iou(a, b):
    area = max(0, min(a[2],b[2])-max(a[0],b[0])) * max(0,min(a[3],b[3])-max(a[1],b[1]))
    union = max(0,a[2]-a[0])*max(0,a[3]-a[1])+max(0,b[2]-b[0])*max(0,b[3]-b[1])-area
    return area / union if union else 0.


def association_details(bbox, boxes):
    ranked = sorted(((iou(bbox, box), int(a)) for a, box in boxes.items()), reverse=True)
    matches = [dict(actor=a, iou=v) for v,a in ranked if v >= .30]
    if not matches:
        return dict(actor=None, status='unassociated', matches=[])
    if len(matches)>1 and matches[0]['iou']-matches[1]['iou']<=.05:
        return dict(actor=None, status='ambiguous', matches=matches)
    return dict(actor=matches[0]['actor'], status='matched', matches=matches)


def associate(bbox, boxes):
    return association_details(bbox, boxes)['actor']


def episodes(frames, labels, basis='visible'):
    """Independent GT-visible / detected episodes; neither extends the other's gap."""
    result, latest, associations = [], {}, {}
    for index, frame in enumerate(frames):
        visible = {int(a) for a in frame['visible']}
        detected = {int(d['actor']) for d in frame['detections'] if d.get('actor') is not None}
        observed = visible if basis=='visible' else detected
        for actor in observed:
            if actor not in labels:
                continue
            key = latest.get(actor)
            if key is None or frame['t'] - result[key]['last_s'] > 1.0 + 1e-6:
                key = len(result)
                latest[actor] = key
                result.append(dict(episode=key, basis=basis, actor=actor, target=int(labels[actor]), first_s=frame['t'],
                                   last_s=frame['t'], first_detected_s=None, visible_frames=0, detected_frames=0))
            ep = result[key]
            ep['last_s'] = frame['t']
            ep['visible_frames'] += int(actor in visible)
            ep['detected_frames'] += int(actor in detected)
            if actor in detected and ep['first_detected_s'] is None:
                ep['first_detected_s'] = frame['t']
            associations[(index, actor)] = key
    return result, associations


def validate_frames(directory, manifest, frames):
    contracts={180:1800,600:6000}
    duration=manifest['duration_s']
    expected=contracts.get(duration)
    if expected is None or len(frames)!=expected or manifest['frames']!=expected:
        raise ValueError('Expected %s frames / %s seconds at10Hz: '%(expected or 'approved',duration)+str(directory))
    cleanup=manifest.get('cleanup',{})
    required={'attempted','destroyed','failed_actor_ids'}
    if not required.issubset(cleanup) or cleanup.get('failed_actor_ids') or cleanup.get('destroyed')!=cleanup.get('attempted') or cleanup.get('attempted')!=len(manifest.get('traffic',[]))+1:
        raise ValueError('actor cleanup failed: '+str(directory))
    for index,frame in enumerate(frames):
        if frame['index']!=index or abs(frame['t']-index*.1)>.002:
            raise ValueError('noncontiguous indices/times: '+str(directory))
        if index and frame['carla_frame']!=frames[index-1]['carla_frame']+1:
            raise ValueError('noncontiguous sensor frames: '+str(directory))
        if not (Path(directory)/frame['image']).is_file():
            raise ValueError('missing RGB image: '+str(directory))


def score_episodes(eps, associations, events, config):
    result = [dict(ep, config=config, reached=0, requests=0, candidates=0, request_delay_s=None, confirm_delay_s=None) for ep in eps]
    for event in events:
        key = associations.get((event['frame'], event.get('actor')))
        if key is None:
            continue
        row = result[key]
        t = event.get('t', row['first_detected_s'])
        if event['kind'] == 'candidate':
            row['candidates'] += 1
            if row['confirm_delay_s'] is None and row['first_detected_s'] is not None:
                row['confirm_delay_s'] = max(0., t - row['first_detected_s'])
        if event['kind'] == 'request':
            row['requests'] += 1
            row['reached'] = 1
            if row['request_delay_s'] is None and row['first_detected_s'] is not None:
                row['request_delay_s'] = max(0., t - row['first_detected_s'])
    return result


def csv_write(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields or list(rows[0]) if rows else (fields or []), extrasaction='ignore',lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def replay(directory, configs=None):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest['status'] != 'COMPLETE':
        raise ValueError('incomplete capture: ' + str(directory))
    frames = [json.loads(line) for line in (directory / 'frames.jsonl').open()]
    validate_frames(directory, manifest, frames)
    for frame in frames:
        for d in frame['detections']:
            detail=association_details(d['bbox'],frame['projected'])
            d['capture_actor']=d.get('actor')
            d['actor']=detail['actor']
            d['association']=detail
    labels = {int(p['actor_id']): p['is_target_color'] for p in manifest['traffic']}
    visible_eps, visible_assoc = episodes(frames, labels, 'visible')
    detected_eps, detected_assoc = episodes(frames, labels, 'detected')
    all_events, all_scores, summaries = [], [], []
    for config in configs or configurations():
        branch, events, timings = Branch(config), [], []
        for index, frame in enumerate(frames):
            observable = [{k:d[k] for k in ('bbox','class_id','confidence','color')} for d in frame['detections']]
            started = time.perf_counter()
            emitted = branch.process(observable, frame['t'])
            timings.append((time.perf_counter()-started)*1000)
            for event in emitted:
                event.update(frame=index, t=frame['t'], config=config['name'], run=directory.name,
                             actor=associate(event['bbox'], frame['projected']),
                             association=association_details(event['bbox'],frame['projected']))
                events.append(event)
        scores = score_episodes(visible_eps, visible_assoc, events, config['name']) + score_episodes(detected_eps, detected_assoc, events, config['name'])
        target_owners={}
        for event in events:
            key=tuple(event.get('target_key',[]))
            if event['kind']=='request' and key:
                target_owners[key]=event['actor']
            event['different_actor_suppressed']=int(event['kind']=='suppressed' and key in target_owners and event['actor'] is not None and target_owners[key] is not None and event['actor']!=target_owners[key])
        for row in scores:
            row.update(run=directory.name, split=manifest['split'], map=manifest['map'], weather=manifest['weather'], vehicles=manifest['vehicles'])
        requests = [e for e in events if e['kind']=='request']
        tp = [s for s in scores if s['target'] and s['basis']=='detected']
        nt = [s for s in scores if not s['target'] and s['basis']=='detected']
        import numpy as np
        summaries.append(dict(run=directory.name, split=manifest['split'], map=manifest['map'], weather=manifest['weather'],
                              vehicles=manifest['vehicles'], config=config['name'], family=config['family'], n=config['n'],
                              target_episodes=sum(s['target'] for s in scores if s['basis']=='visible'), detected_targets=len(tp),
                              reached_targets=sum(s['reached'] for s in tp), detected_nontargets=len(nt),
                              unique_target_actors=len({s['actor'] for s in tp}),
                              reached_unique_target_actors=len({s['actor'] for s in tp if s['reached']}),
                              reached_nontargets=sum(s['reached'] for s in nt), requests=len(requests),
                              target_requests=sum(e['actor'] is not None and labels.get(e['actor'],False) for e in requests),
                              nontarget_requests=sum(e['actor'] is not None and not labels.get(e['actor'],True) for e in requests),
                              unassociated_requests=sum(e['actor'] is None for e in requests),
                              ambiguous_requests=sum(e['association']['status']=='ambiguous' for e in requests),
                              different_actor_suppressions=sum(e['different_actor_suppressed'] for e in events),
                              candidates=sum(e['kind']=='candidate' for e in events),
                              repeated_requests=sum(max(0,s['requests']-1) for s in scores if s['basis']=='detected'),
                              cpu_ms_p50=float(np.percentile(timings,50)), cpu_ms_p95=float(np.percentile(timings,95)),
                              frames=len(frames)))
        all_scores.extend(scores)
        all_events.extend(events)
    out = directory / 'analysis'
    out.mkdir(exist_ok=True)
    csv_write(out/'episodes.csv', all_scores)
    csv_write(out/'summary.csv', summaries)
    with (out/'events.jsonl').open('w') as f:
        for e in all_events:
            f.write(json.dumps(e)+'\n')
    return summaries, all_scores, all_events
