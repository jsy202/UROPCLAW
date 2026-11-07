"""Replay exactly one fixed6000-frame recording; never start CARLA/VLM."""
import csv
import hashlib
import json
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
REFERENCE=HERE.parent/'temporal_filter_study'
PREVIOUS=HERE.parent/'progressive_filter_study'
SOURCE=PREVIOUS/'runs/Town10HD_Opt_clear_v30_s101'
sys.path.insert(0,str(ROOT/'harness'))
sys.path.insert(0,str(REFERENCE))
sys.path.insert(0,str(PREVIOUS))
sys.path.insert(0,str(HERE))
import study
from analyze_progressive import configurations as prior_configurations
from policies import ReappearanceDeduplicator


class ComparisonBranch(study.Branch):
    def __init__(self,config):
        super().__init__(config)
        if config.get('policy'):
            self.dedup=ReappearanceDeduplicator(reset_on_gap=config['policy']=='reappearance')


def configurations():
    rows=prior_configurations()
    base=dict(n=1,rule='current',hsv=True,temporal=False,dedup=True,architecture='current',family='single_set_dedup')
    rows.extend([dict(base,name='track_only',policy='track_only'),
                 dict(base,name='reappearance',policy='reappearance'),
                 dict(base,name='reappearance_n3',policy='reappearance',temporal=True,n=3)])
    return rows


def keys(scores,name,basis):
    return {(r['actor'],r['episode']) for r in scores
            if r['config']==name and r['basis']==basis and r['target'] and r['reached']}


def main():
    import cv2
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    manifest=json.loads((SOURCE/'manifest.json').read_text())
    assert (manifest['map'],manifest['weather'],manifest['vehicles'],manifest['seed'])==('Town10HD_Opt','clear',30,101)
    assert manifest['status']=='COMPLETE' and manifest['frames']==6000 and manifest['duration_s']==600
    local=HERE/'replay'/SOURCE.name;local.mkdir(parents=True,exist_ok=True)
    for name in ('manifest.json','frames.jsonl','images'):
        p=local/name
        if not p.exists():p.symlink_to(SOURCE/name,target_is_directory=name=='images')
    output=HERE/'results';output.mkdir(exist_ok=True)
    original=study.Branch
    try:
        study.Branch=ComparisonBranch
        summaries,scores,events=study.replay(local,configurations())
    finally:
        study.Branch=original
    assert study.Branch is original
    reference_detected=keys(scores,'factor_000','detected')
    reference_visible=keys(scores,'factor_000','visible')
    reference_actors={a for a,_ in reference_detected}
    all_visible={(r['actor'],r['episode']) for r in scores if r['config']=='factor_000' and r['basis']=='visible' and r['target']}
    for r in summaries:
        name=r['config'];det=keys(scores,name,'detected');vis=keys(scores,name,'visible')
        r['missed_detected_episodes']=len(reference_detected-det)
        r['missed_visible_episodes']=len(reference_visible-vis)
        r['missed_actors']=len(reference_actors-{a for a,_ in det})
        r['zero_added_loss']=not (reference_detected-det or reference_visible-vis or reference_actors-{a for a,_ in det})
        target=[e for e in scores if e['config']==name and e['basis']=='detected' and e['target']]
        for metric in ('confirm_delay_s','request_delay_s'):
            values=[e[metric] for e in target if e[metric] is not None]
            r[metric.replace('_delay_s','_p95_s')]=float(np.percentile(values,95)) if values else None
            r[metric.replace('_delay_s','_max_s')]=max(values) if values else None
        r['request_reduction_pct']=100*(1-r['requests']/next(s['requests'] for s in summaries if s['config']=='factor_000'))
    by={r['config']:r for r in summaries}
    eligible=[r for r in summaries if r['zero_added_loss']]
    selected=min(eligible,key=lambda r:(r['requests'],r['request_p95_s'] or 0,r['config']))['config']
    study.csv_write(output/'comparison.csv',summaries)
    study.csv_write(output/'episodes.csv',scores)
    temporal=[by['n%d_raw'%n] for n in (1,2,3,5,7,10)]
    study.csv_write(output/'temporal_without_dedup.csv',temporal)
    changes=[]
    for name in by:
        for basis,reference in [('detected',reference_detected),('visible',reference_visible)]:
            for actor,episode in sorted(reference-keys(scores,name,basis)):
                changes.append(dict(config=name,basis=basis,actor=actor,episode=episode))
    study.csv_write(output/'missed_reference_episodes.csv',changes,fields=['config','basis','actor','episode'])
    frames=[json.loads(line) for line in (SOURCE/'frames.jsonl').open()]
    assert len(frames)==6000
    cases=[]
    for actor,episode in sorted(keys(scores,'n1_raw','detected')-keys(scores,'n3_raw','detected')):
        score=next(r for r in scores if r['config']=='n1_raw' and r['basis']=='detected' and r['actor']==actor and r['episode']==episode)
        event=next(e for e in events if e['config']=='n1_raw' and e['kind']=='request' and e['actor']==actor and score['first_s']<=e['t']<=score['last_s'])
        frame=frames[event['frame']];im=cv2.imread(str(SOURCE/frame['image']))
        box=[int(v) for v in event['bbox']];cv2.rectangle(im,tuple(box[:2]),tuple(box[2:]),(0,255,255),2)
        label='N1 reached / N3 missed | actor%d episode%d frame%d'%(actor,episode,event['frame'])
        cv2.putText(im,label,(8,22),cv2.FONT_HERSHEY_SIMPLEX,.52,(0,0,0),3)
        cv2.putText(im,label,(8,22),cv2.FONT_HERSHEY_SIMPLEX,.52,(255,255,255),1)
        name='temporal_miss_actor%d_episode%d.jpg'%(actor,episode)
        cv2.imwrite(str(output/name),im)
        observations=[d for f in frames if score['first_s']<=f['t']<=score['last_s'] for d in f['detections']
                      if study.associate(d['bbox'],f['projected'])==actor]
        cases.append(dict(actor=actor,episode=episode,first_s=score['first_s'],last_s=score['last_s'],frame=event['frame'],image=name,
                          observations=len(observations),blue_observations=sum(d['color']=='blue' for d in observations)))
    study.csv_write(output/'temporal_miss_cases.csv',cases)
    recoveries=[]
    for actor,episode in sorted(reference_detected-keys(scores,'factor_101','detected')):
        row=next(r for r in scores if r['config']=='factor_000' and r['basis']=='detected' and r['actor']==actor and r['episode']==episode)
        suppressed=[e for e in events if e['config']=='factor_101' and e['kind']=='suppressed' and e['actor']==actor and row['first_s']<=e['t']<=row['last_s']]
        recovered=[e for e in events if e['config']==selected and e['kind']=='request' and e['actor']==actor and row['first_s']<=e['t']<=row['last_s']]
        first=min(r['first_s'] for r in scores if r['config']=='factor_000' and r['basis']=='detected' and r['actor']==actor)
        recoveries.append(dict(actor=actor,episode=episode,appearance='first' if row['first_s']==first else 'reappearance',
                               first_s=row['first_s'],last_s=row['last_s'],legacy_first_reason=suppressed[0]['reason'] if suppressed else '',
                               legacy_reasons=','.join(sorted({e['reason'] for e in suppressed})),
                               selected=selected,recovered=bool(recovered),request_s=recovered[0]['t'] if recovered else None,
                               request_delay_s=recovered[0]['t']-row['first_s'] if recovered else None))
    study.csv_write(output/'dedup_recovery.csv',recoveries)
    image_hash=hashlib.sha256();image_bytes=0
    with (output/'images.sha256').open('w') as target:
        for index,frame in enumerate(frames):
            p=SOURCE/frame['image'];data=p.read_bytes();assert data[:2]==b'\xff\xd8' and data[-2:]==b'\xff\xd9'
            digest=hashlib.sha256(data).hexdigest();target.write(digest+'  '+frame['image']+'\n')
            image_hash.update((p.name+digest).encode());image_bytes+=len(data)
            if index%100==0 or index==5999:assert cv2.imread(str(p)).shape==(600,800,3)
    inventory=list(csv.DictReader((PREVIOUS/'results/archive_inventory.csv').open()))
    prior=next(r for r in inventory if r['run']==SOURCE.name)
    assert image_hash.hexdigest()==prior['image_set_sha256']
    decision=dict(source=SOURCE.name,recordings=1,frames=6000,configurations=len(summaries),selected=selected,
                  selection_basis='same-set exploratory:zero added actor/detected-episode/baseline-visible-episode loss then minrequests',
                  independent_holdout=False,actual_vlm_called=False,production_policy_changed=False,
                  spawned_target_actors=sum(a['is_target_color'] for a in manifest['traffic']),
                  reference_detected_episodes=len(reference_detected),reference_actors=len(reference_actors),
                  gt_visible_episodes=len(all_visible),reference_visible_reached=len(reference_visible),
                  baseline_visible_misses=len(all_visible-reference_visible),
                  selected_missed_actors=by[selected]['missed_actors'],selected_missed_detected_episodes=by[selected]['missed_detected_episodes'],
                  selected_missed_visible_episodes=by[selected]['missed_visible_episodes'],image_bytes=image_bytes,
                  image_set_sha256=image_hash.hexdigest(),frames_sha256=hashlib.sha256((SOURCE/'frames.jsonl').read_bytes()).hexdigest(),
                  manifest_sha256=hashlib.sha256((SOURCE/'manifest.json').read_bytes()).hexdigest())
    (output/'decision.json').write_text(json.dumps(decision,ensure_ascii=False,indent=2)+'\n')
    names=['factor_000','factor_100','factor_101','track_only','reappearance','reappearance_n3']
    fig,axes=plt.subplots(1,3,figsize=(15,4.8))
    for ax,field,title in zip(axes,['requests','reached_targets','request_p95_s'],['Request triggers (no real VLM)','Target episodes reached /16','Request delay p95 (sim s)']):
        ax.bar(names,[by[n][field] for n in names]);ax.set_ylabel(title);ax.tick_params(axis='x',rotation=35);ax.grid(axis='y',alpha=.2)
        if field=='requests':ax.set_yscale('log')
    fig.suptitle('One fixed 6,000-frame set; no independent hold-out')
    fig.tight_layout();fig.savefig(output/'single_set_comparison.png',dpi=170);plt.close(fig)
    write_report(by,decision,cases)
    print('SINGLE SET COMPLETE',json.dumps(decision,ensure_ascii=False),flush=True)


def write_report(by,decision,cases):
    selected=by[decision['selected']]
    lines=['# 단일 6,000프레임: 목표 보존을 우선한 필터 비교','',
           '**한 녹화·6,000프레임만 입력했다.** Town10HD_Opt 맑은 낮·차량30대·seed101·10Hz·10분. 기존 개발 자료의 첫 조건으로 고정했고 다른 영상은 읽거나 수집하지 않았다. 실제 VLM은 호출하지 않았다. 이전 전체 결과는 별도로 보존했다.','',
           '## 목표 누락을 직접 확인한 결과','',
           'CARLA 정답상 생성된 파란 차량은 %d대이며 이 세트에서는 모두 YOLO에 검출됐다. 기준에서 도달한 검출 출현 %d건, GT 가시 출현 %d/%d건을 actor/episode ID 집합으로 대조했다. 개수만 같다고 무손실로 판정하지 않았다.'%(decision['spawned_target_actors'],decision['reference_detected_episodes'],decision['reference_visible_reached'],decision['gt_visible_episodes']),
           '', '| 구성 | 요청 | 목표 차량 도달 | 목표 출현 도달 | 추가 출현 누락 | 확인p95(s) | 요청p95(s) |','|---|---:|---:|---:|---:|---:|---:|']
    labels=[('factor_000','기본 YOLO 후보'),('factor_100','HSV 추가'),('factor_101','기존 중복 억제 추가'),('track_only','새 track의 첫 요청 보장'),('reappearance','관측 공백 후 재요청 추가'),('reappearance_n3','동일 수정 dedup에 N3 추가')]
    for name,label in labels:
        r=by[name];lines.append('| %s | %d | %d/%d | %d/%d | %d | %.3f | %.3f |'%(label,r['requests'],r['reached_unique_target_actors'],r['unique_target_actors'],r['reached_targets'],r['detected_targets'],r['missed_detected_episodes'],r['confirm_p95_s'],r['request_p95_s']))
    lines+=['','![동일 입력 비교](results/single_set_comparison.png)','',
            '선택: **%s**. 기준 대비 추가 차량 누락 %d건·추가 검출 출현 누락 %d건·추가 GT 가시 출현 누락 %d건이며, 요청은8167→%d회(%.2f%% 감소)다.'%(decision['selected'],decision['selected_missed_actors'],decision['selected_missed_detected_episodes'],decision['selected_missed_visible_episodes'],selected['requests'],selected['request_reduction_pct']),
            '', '기존 구조는 차량4대는 모두 찾았지만 목표의 첫 출현1건과 재등장1건이30초 cooldown/fragment alias로 차단됐다. 선택한 track-only 수정안은 HSV·추적·현재 색 선별을 그대로 두고 새track의 첫 요청을 인접track에 묶지 않는다. 같은track의30초 cooldown은 유지한다. 관측 공백 후 재요청 대안도 비교했으나 목표 보존은 같고 요청이30회로 늘어 선택하지 않았다. 연속 확인은 추가하지 않는다. 이 구현은 실험용이며 운영 기본 경로를 자동 변경하지 않았다.','',
            '선택안의 요청 지연 p95는 %.3f초, 최대 %.3f초다. HSV만 쓴 경우 p95 %.3f초, 최대 %.3f초보다 지연이 늘었다. 목표 출현마다 적어도 한 번 도달했다는 뜻이며, 지연 없는 즉시 전달을 보장한 것은 아니다.'%(selected['request_p95_s'],selected['request_max_s'],by['factor_100']['request_p95_s'],by['factor_100']['request_max_s']),'',
            '## 연속 확인을 제외한 수치적 근거','',
            '아래는 **모든 N에서 dedup을 끈 동일 조건**이다. 따라서 목표 출현 손실을 중복 억제와 분리해 확인한다. 기존 N 규칙은 unknown을 제외한 모음 투표이며 연속N회 모두 목표라는 규칙이 아니다.','',
            '| N | 요청 | 차량 도달 | 출현 도달 | 추가 출현 누락 | 확인p95(s) |','|---:|---:|---:|---:|---:|---:|']
    for n in (1,2,3,5,7,10):
        r=by['n%d_raw'%n];lines.append('| %d | %d | %d/%d | %d/%d | %d | %.3f |'%(n,r['requests'],r['reached_unique_target_actors'],r['unique_target_actors'],r['reached_targets'],r['detected_targets'],r['missed_detected_episodes'],r['confirm_p95_s']))
    lines+=['','중복 억제를 꺼도 N3에서 출현2건이 이미 누락됐다. 따라서 새 중복 억제 정책 때문이라고 설명할 수 없다. N3의 요청 절감 효과도 관측됐다. 그러나 이번 요구는 목표 차량뿐 아니라 목표의 각 출현을 모두 보존하는 것이므로, 추가 출현 누락이 생기는 연속 확인은 제외한다. N3에서도 차량4대는 모두 도달했으며 모든 차량을 놓쳤다는 뜻은 아니다.','',
            '[기존 중복 억제의 누락·복구 시각](results/dedup_recovery.csv) · [N별 원자료](results/temporal_without_dedup.csv) · [누락 ID 목록](results/missed_reference_episodes.csv) · [사례 관측 수](results/temporal_miss_cases.csv)']
    for case in cases:lines+=['','![N3 누락 사례](results/%s)'%case['image']]
    lines+=['','## 범위와 재현','',
            '관측한 한 세트에서 추가 손실0을 확인한 결과다. 선택·비교가 같은 한 세트에서 이루어졌고 독립 평가가 없다. 기존 전체 자료나 모든 환경의 무손실로 일반화하지 않는다. GT 투영·연결도 근사다. 반복 프레임을 모두 VLM에 보내는 뜻이 아니라 각 목표 차량/출현이 최소한 번 요청 단계에 도달했는지 평가했다. 실제 VLM·큐·최종 경보의 누락은 측정하지 않았다.','',
            '모든6,000JPEG의 해시·마커를 검증하고 해상도를 표본 검사했다. 기존 원자료 image-set 해시와 일치한다. 입력 캐시는 원본 센서에서 얻은 검출·색상이며 JPEG를 재추론하지 않았다.','',
            '[고정 명세](PROTOCOL.ko.md) · [전체31구성](results/comparison.csv) · [선택과 무결성](results/decision.json) · [이미지별 해시](results/images.sha256)']
    (HERE/'REPORT.ko.md').write_text('\n'.join(lines)+'\n')

if __name__=='__main__':main()
