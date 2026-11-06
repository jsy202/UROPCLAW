"""Build the Korean report exclusively from saved measured tables."""
from __future__ import annotations
import collections
import csv
import json
from pathlib import Path
import numpy as np
from study import configurations,csv_write
from queue_model import simulate
HERE=Path(__file__).resolve().parent


def read_csv(path):return list(csv.DictReader(path.open()))
def number(v):return float(v) if v not in ('',None) else None
def fmt(v,d=3):return '—' if v in ('',None) else ('%.*f'%(d,float(v)))
def pct(v):return '—' if v in ('',None) else ('%.1f%%'%(100*float(v)))


def queue_profiles():
    profile=json.loads((HERE/'results/real_vlm/summary.json').read_text())
    service=[float(r['wall_s']) for r in read_csv(HERE/'results/real_vlm/samples.csv')]
    configs={c['name']:c for c in configurations()}
    names=['n%d_dedup'%n for n in (1,2,3,5,7,10)]+['n3_raw','factor_000']
    rows=[]
    for p in sorted((HERE/'runs').iterdir()):
        m=json.loads((p/'manifest.json').read_text())
        if m['split']!='test':continue
        by=collections.defaultdict(list)
        for line in (p/'analysis/events.jsonl').open():
            e=json.loads(line)
            if e['config'] in names and e['kind']=='candidate':by[e['config']].append(e)
        for name in names:
            result=simulate(by[name],service,capacity=20,dedup=configs[name]['dedup'])
            calls=result['calls'];wait=[c['wait_s'] for c in calls];delay=[c['end_to_end_proxy_s'] for c in calls]
            rows.append(dict(run=p.name,config=name,candidates=len(by[name]),calls=len(calls),dropped=result['dropped'],suppressed=result['suppressed'],
                             wait_p50_s=float(np.percentile(wait,50)) if wait else None,wait_p95_s=float(np.percentile(wait,95)) if wait else None,
                             finish_delay_p95_s=float(np.percentile(delay,95)) if delay else None,
                             last_finish_s=calls[-1]['finished_s'] if calls else None))
    csv_write(HERE/'results/queue_model.csv',rows)
    return rows


def main():
    out=HERE/'results'
    data=read_csv(out/'aggregate.csv');test={r['config']:r for r in data if r['split']=='test'}
    choice=json.loads((out/'dev_selection.json').read_text())['selected']
    cis={r['config']:r for r in read_csv(out/'paired_confidence_intervals.csv') if r['split']=='test'}
    paired={(r['config'],r['metric']):r for r in read_csv(out/'paired_delays.csv') if r['split']=='test'}
    q=[]
    vlm=None
    times=read_csv(out/'timings.csv')
    current=test['n3_dedup'];baseline=test['n1_dedup'];guard=test['dedup_active_guard']
    lines=['# 시간적 확인과 필터 구조 비교 실험 결과', '', '이 문서는 시간적 확인 제거 전 구현을 비교한 기록이다. 이후 사용자 결정으로 현재 실행 경로에서 시간적 확인을 제외했다. 도입 후 실제 검증에서 이점이 부족해 제외한 시행착오와 후속 구조 비교는 SUMMARY.ko.md를 참고한다.',
           '', '**실험 성격:** 초기 경험적 설계를 사후 비교 검증했다. 당시 3프레임 선정 이유를 소급해 만들어내지 않았다. production 코드는 변경하지 않고 검증 도구에서 대안을 비교했다.',
           '', '## 1. 실제 실행 범위', '',
           '- CARLA0.9.13, RTX3060, 화면 창 없이 `RenderOffScreen`, Low quality. RGB 렌더링 활성화. 모든 원본 카메라 프레임을 JPEG(q85)로 저장했다.',
           '- Town10HD_Opt는 3환경 × 차량30/70 × seed5개(30녹화). Town03_Opt는 맑은 낮 × 차량30/70 × seed5개(10녹화). 사용자 요청으로 총40개에서 수집을 종료했다. 두 번째 지도의 낮은 태양/비 조건은 측정하지 않았다.',
           '- 40개 녹화 × 180초 × 10Hz = **72,000프레임, 시뮬레이션120분**. 개발16개(48분), 최종평가24개(72분).',
           '- 모든 녹화에서 원본 비압축 RGB로 YOLOv8s와 HSV를 한 번 실행하고 결과를 저장했다. 동일 검출·색상 결과를26개 독립 상태 구성에 재생했다. JPEG 재추론 결과와 섞지 않았다.',
           '- 최종평가를 분석하기 전에 개발 데이터에서 N을 선택하고 `dev_selection.json`에 고정했다. 평가 데이터로 다시 고르지 않았다.',
           '- 모든1800연속센서frame/index/시각/이미지실재와 생성 차량+카메라의 정리성공을 검사했다.',
           '', '## 2. 현재 3프레임 규칙의 정확한 의미', '',
           '현재 규칙은 연속3장의 완전한 일치를 요구하지 않는다. 같은 트랙의 실제 매칭 관측3개를 모으고 unknown을 제외한 색상 투표에서60% 이상인 색을 고른다. 관측 간격이1초를 넘으면 초기화하고, 판정 후 묶음을 삭제한다. 따라서 blue/unknown/unknown도 blue로 확인된다. 10Hz에서 검출이 빠짐없다면 첫 관측부터 세 번째까지는0.2초다.',
           '', '실제 처리 순서: `모든 차량 검출 → HSV 라벨 부여 → 전체 차량 tracking → temporal 색상 확인 → 목표 색 gate → target별 dedup → VLM 요청`.',
           '', '## 3. 지표와 판단 기준', '',
           '- **검출 출현 도달률:** 모호하지 않게 정답 차량에 연결된 검출의 출현 구간 중 VLM요청이 발생한 비율. 검출 간격이1초를 넘으면 새 출현이다. 주지표이며 YOLO가 전혀 잡지 못한 차량은 분모에 없으므로 end-to-end recall로 부르지 않는다.',
           '- **GT가시 출현 도달률:** 별도로 GT가시 관측 간격1초로 나눈 출현을 평가한다. GT가시 관측 시점에서 요청이 있었는지 확인한다. 검출로 이 구간을 이어 붙이지 않는다. GT투영/raycast가 근사라는 한계가 있다.',
           '- **확인/요청 지연:** 해당 검출 출현의 첫YOLO검출부터 첫목표확인/요청까지의 simulation time. 확인 못 한 출현은 누락으로 따로 남긴다. 지연p95는 성공 출현에 조건부이므로 공통 성공 출현의paired지연차도 제공한다.',
           '- IoU≥.30으로 연결하되 상위2후보IoU차≤.05면 ambiguous. 이런 요청은 전체요청/미확정요청에 남기고 mapped precision에 넣지 않는다. 미확정요청이 모두 오검출이라는 뜻은 아니다.',
           '- 개발 선택 기준: N1대비 주도달률 손실≤2%p, 확인지연p95≤.5초. 충족값 중 비목표+미확정요청, 총요청, 낮은N순으로 선택. 이운영기준은 보편적 최적성 기준이 아니다.',
           '', '## 4. N 비교 — 최종평가24개 녹화', '',
           '| N | 도달/검출출현 | 도달률 | 요청/분 | 비목표요청 | 미확정요청(모호포함) | 확인p95(s) | 요청p95(s) | 공통성공 확인추가지연p95 vsN1(s) |',
           '|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for n in (1,2,3,5,7,10):
        r=test['n%d_dedup'%n];p=paired[(r['config'],'confirm_delay_s')]
        lines.append('| %d | %s/%s | %s | %s | %s | %s | %s | %s | %s |'%(n,r['reached_targets'],r['detected_targets'],pct(r['detected_recall']),fmt(r['requests_per_min']),r['nontarget_requests'],r['unassociated_requests'],fmt(r['confirm_p95_s']),fmt(r['request_p95_s']),fmt(p['paired_difference_p95_s'])))
    lines+=['','차량 단위와 재등장 출현은 다르다. 같은 차량의30초이내재등장은의도적으로억제될수있다. 아래는한녹화안에서한번이라도요청된고유목표actor의도달률이다(서로다른녹화의같은모델은독립actor로집계). 주지표나개발N선택기준을사후변경하지않고보조지표로제공한다.','',
            '| N | 고유목표차량 도달/검출 | 차량도달률 | dedup없는출현도달률 |','|---:|---:|---:|---:|']
    for n in (1,2,3,5,7,10):
        r=test['n%d_dedup'%n];raw=test['n%d_raw'%n]
        lines.append('| %d | %s/%s | %s | %s |'%(n,r['reached_unique_target_actors'],r['unique_target_actors'],pct(r['unique_actor_recall']),pct(raw['detected_recall'])))
    lines+=['','![프레임수별 균형](results/window_tradeoff.png)','','### 개발 선택과 최종평가 해석','']
    if choice is None:
        lines+=['**개발 데이터에서 사전 운영조건을 동시에 만족한 N은 없었다.** 따라서 단일 N을 정답으로 추천하지 않는다. 확인지연에 HSV 안정화 대기와 검출공백이 포함된다는 점을 고려해야 한다. 조건을 결과에 맞춰 바꾸지 않았다.']
    else:
        r=test[choice];ci=cis[choice]
        lines+=['**개발에서 선택된 설정: `%s`.** 평가 도달률%s, 확인p95 %s초, 요청/분%s였다.'%(choice,pct(r['detected_recall']),fmt(r['confirm_p95_s']),fmt(r['requests_per_min'])),
                'N1대비 도달률차이의paired녹화bootstrap95%%구간은 **[%s, %s]%%p**다. 2%%p 비열등성의 탐색적 조건 충족 여부: **%s**. 이값 하나로 모든환경에서 최적이라고 주장하지 않는다.'%(fmt(100*float(ci['recall_diff_ci_low']),2),fmt(100*float(ci['recall_diff_ci_high']),2),'충족' if ci['exploratory_noninferiority_2pp']=='True' else '미충족')]
    ci=cis['n3_dedup']
    lines+=['','현재N3의 N1대비 도달률차이95%%구간: [%s, %s]%%p. 현재N3의GT가시출현 도달률은 %s/%s(%s)다. 표본단위와분모가 다른 두 도달률을 합치지 않았다.'%(fmt(100*float(ci['recall_diff_ci_low']),2),fmt(100*float(ci['recall_diff_ci_high']),2),current['visible_reached'],current['visible_targets'],pct(current['visible_recall'])),
            '', '전체 요청수만 적은 설정을 우수하다고 판단하면 목표누락을 보상하게 된다. p95만 비교하면 느린 차량을 놓치는 설정이 유리해질 수 있어 누락 수와 공통성공 지연차를 함께 봤다.',
            '', '## 5. N3 투표 규칙 비교','',
            '| 규칙 | 도달률 | 요청 | 비목표 | 미확정 | 확인p95(s) |', '|---|---:|---:|---:|---:|---:|']
    for name in ('n3_dedup','rule_full','rule_unanimous','rule_sliding'):
        r=test[name];lines.append('| %s | %s | %s | %s | %s | %s |'%(name,pct(r['detected_recall']),r['requests'],r['nontarget_requests'],r['unassociated_requests'],fmt(r['confirm_p95_s'])))
    lines+=['','`full`: unknown을 분모에 포함한2/3. `unanimous`:3/3. `sliding`:매 관측에서 최근3개 중2/3. 현재규칙은unknown제외/묶음초기화다. 합성색상열 결과는[stress_votes.csv](stress_votes.csv), 실제영상결과는 위표다. 둘을 동일한 성능 근거로 취급하지 않는다.',
            '', '![투표규칙](results/rules.png)','', '## 6. 필터8조합 비교','',
            '| HSV/Temporal/Dedup | 도달률 | 후보 | 요청 | 요청/분 | 비목표 | 미확정 |','|---|---:|---:|---:|---:|---:|---:|']
    for h in (0,1):
        for t in (0,1):
            for d in (0,1):
                r=test['factor_%d%d%d'%(h,t,d)];lines.append('| %d/%d/%d | %s | %s | %s | %s | %s | %s |'%(h,t,d,pct(r['detected_recall']),r['candidates'],r['requests'],fmt(r['requests_per_min']),r['nontarget_requests'],r['unassociated_requests']))
    lines+=['','HSV없음의temporal은 색상일관성이 아니라 차량존재의반복관측을 확인한다. dedup이temporal효과를 가릴 수 있으므로 앞의N비교는dedup on/off도 모두 제공했다. 모든프레임과최종요청의차이를 하나의필터효과로 부르지 않았다.',
            '', '![조합비교](results/factorial.png)','', '## 7. 구조 대안과 중복 억제','',
            '| 구조 | 도달률 | 요청 | 확인p95(s) | 비목표 | 미확정 | 다른GT차량 억제사건* |','|---|---:|---:|---:|---:|---:|---:|']
    for name in ('n3_dedup','early_hsv','late_hsv','dedup_active_guard'):
        r=test[name];lines.append('| %s | %s | %s | %s | %s | %s | %s |'%(name,pct(r['detected_recall']),r['requests'],fmt(r['confirm_p95_s']),r['nontarget_requests'],r['unassociated_requests'],r['different_actor_suppressions']))
    lines+=['','`early_hsv`:매프레임 목표색만남긴 뒤 추적. `late_hsv`:색상없이 추적해 N회존재를 확인한 뒤 현재crop색만판별. 순서와증거사용방식이 함께 바뀌므로 순서만의 인과효과로 해석하지 않는다.',
            '', '*다른GT차량 억제사건은 해당dedup target키의마지막요청 actor와 현재억제 actor가 다른 경우의 관측사건 수다. 요청자체의GT연결오류·IDswitch가능성이 있어 독립적인 차량누락 수로 단정하지 않는다. 실제도달률차이와 사례이미지로 함께 확인한다.',
            '', '합성 통제: 동시에 보이는 같은색 두차량이65px떨어져 있고 box대각선이약72px이면 현재dedup은2트랙중1개만요청한다. 현재매칭된다른트랙을fragment부모로사용하지 않는 탐색적guard는2개를요청했다.150px에서는둘다2개다. [합성결과](stress_dedup.csv). 실제N3대비guard의검출출현도달률은 %s → %s였다. baseline production은 그대로 유지했다.'%(pct(current['detected_recall']),pct(guard['detected_recall'])),
            '', '![구조비교](results/architecture.png)','', '## 8. 필터 처리시간과 확인 지연','',
            '녹화별YOLO p50의중앙값 **%sms**, 녹화별YOLO p95의중앙값 **%sms**. 녹화별HSV p95의중앙값 **%sms**. 이측정은동기CARLA호스트에서GPU동기화로잰wall-time이며 실제도로서비스의종단간지연은 아니다.'%(fmt(np.median([float(t['yolo_p50_ms']) for t in times])),fmt(np.median([float(t['yolo_p95_ms']) for t in times])),fmt(np.median([float(t['hsv_p95_ms']) for t in times]))),
            '', 'replay CPU측정에는실제HSV연산이없다. 따라서late-HSV의실제계산량절감을CPU표만으로입증할수없다. 모든원본프레임에서HSV를계산한캐시를사용해판단결과의차이만비교했다.',
            '', '사용자 요청으로 본 실험에서는 실제 VLM을 호출하지 않았다. 요청 수는 필터가 VLM 검증을 요구했을 트리거 수다. 측정 지연은 첫 검출부터 필터 확인/요청 트리거까지이며, 실제 VLM 응답·큐 대기·최종 경보 지연으로 해석하지 않는다. 실제 VLM 및 실제 worker 큐 실험은 자동 실행에서 제거했다.',
            '', '지시 이전 연결 확인용 이미지1장 호출 기록은 vlm_probe에 별도 보존했다. 이는 본 비교 실험의 표본이나 서비스 지연 통계에 포함하지 않는다.']
    lines+=[
            '', '## 9. 발생한 어려움과 해결 기록','',
            '1. **지도전환시CARLA SIGSEGV:** Town03 live load에서서버가종료됐다. 세부native원인은확인하지못했다. Town03_Opt를새서버에명시적RPC로로드하고실제mapname을검증했다. 실행인자만으로지도선택이된다는초기추정은RPC관측으로틀렸음을확인해바로잡았다. [D01](defects/D01-map-transition.md).',
            '별도서버재시작에서도wrapper만종료되고Unrealchild가포트를점유해다음시작이실패했다. 소유프로세스그룹종료와포트해제검사를추가하고30개완료녹화를보존한채재개했다. [D04](defects/D04-server-process-group.md).',
            '2. **비교대안의정보누출과시계오염:** late-HSV가추적때이미색상을사용하고replay시계가공유module에남던문제를테스트로발견했다.unknown입력/판정후색상조회/finally복구로수정했다. [D02](defects/D02-validation-isolation.md).',
            '3. **정답모호성·출현분모·완료검사:** 별도리뷰에서강제GT연결,GT출현을검출로이어붙이는문제,완료개수만확인하는문제를발견했다. 원본입력과GT가남아있어재수집없이수정하고회귀검증했다. 준비했던VLM음성대조군도리뷰했지만실제호출계획은사용자요청으로취소했다. 이미지consumer에는같은규칙을적용했다. [D03](defects/D03-evaluation-denominators.md).',
            '4. **가까운서로다른차량의dedup오합침:** 합성재현과실제빈도를구분해기록하고active-track guard를검증도구에서비교했다. 이guard가순차적으로등장하는다른차량이나모든IDswitch까지해결한다는증거는없다.',
            '', '## 10. 해석의 한계','',
            '- 첫 지도는3환경·2교통량,두번째지도는맑은낮·2교통량으로조건이비대칭이다. 카메라는지도각1개다. 실제도로/야간/다른센서로일반화하지않는다. 색상이적용되는9개sedan/SUV모델로제한했고microlino는수집전제외했다.',
            '- GT는페인트설정+투영bbox+중심raycast다. 실제픽셀단위가시성정답이아니다. 겹침모호성을분리했어도연결오류는남을수있다. 개발용crop색상감사표와이미지를제공했다.',
            '- 출현구분gap1초와영상경계는평가정의다. 마지막에짧게나타난차량도분모에서빼지않았다. 영상중간에검출이끊긴같은차량은새출현이될수있다.',
            '- 동일입력내비교는공정하지만시뮬레이션실행은bit단위재현을보장하지않는다. seed별녹화는동일지도서버를순서대로사용하며traffic-light위상등world상태가이어질수있다.',
            '- bootstrap은녹화단위2000회paired재표집이다. 프레임을독립표본으로취급하지않았다. 여러설정의구간은탐색적이며다중비교보정을하지않았다. 2%p차이를확정할충분한검정력이있다고가정하지않는다.',
            '- 사용자 요청에 따라 본 비교에서 실제 VLM은 실행하지 않았다. 최종 VLM 정확도·실제 VLM 응답·큐 대기·경보 지연·청구 비용은 측정하지 않았다. Discord나 외부 경보는 발송하지 않았다.',
            '', '## 11. 원자료·그림·재현','',
            '- [프레임수비교그림](results/window_tradeoff.png) / [4개환경장면](results/scene_comparison.jpg) / [사례목록](results/evidence/cases.csv).',
            '- [전체집계](results/aggregate.csv), [녹화별집계](results/per_recording.csv), [출현별결과](results/episodes.csv), [조건별결과](results/stratified.csv), [paired지연](results/paired_delays.csv), [신뢰구간](results/paired_confidence_intervals.csv).',
            '- `runs/<조건>/images/000000.jpg`부터모든RGB이미지, `frames.jsonl`에원본YOLO/HSV/GT/시각, `manifest.json`에환경/가중치SHA256/차량/cleanup. `analysis/events.jsonl`에후보·억제·요청·모호한정답후보목록.',
            '- `label_audit/`에개발전용색상crop감사자료. 본 비교의 실제VLM 결과는 생성하지 않는다. raw runs는용량때문에git에서제외했지만호스트디스크에는보존했다.',
            '', '```bash',
            '# 저장소 루트에서 기존 CARLA 환경 사용',
            '.venv-carla-e2e/bin/python validation/carla_e2e/temporal_filter_study/run_batch.py',
            '.venv-carla-e2e/bin/python validation/carla_e2e/temporal_filter_study/analyze.py',
            '.venv-carla-e2e/bin/python validation/carla_e2e/temporal_filter_study/stress.py',
            '.venv-carla-e2e/bin/python validation/carla_e2e/temporal_filter_study/make_cases.py',
            '.venv-carla-e2e/bin/python validation/carla_e2e/temporal_filter_study/audit_labels.py',
            '.venv-carla-e2e/bin/python validation/carla_e2e/temporal_filter_study/report.py',
            '.venv-carla-e2e/bin/python -m pytest -q',
            '```','',
            '기존 완료 녹화는 재사용한다. 실제 VLM 호출은 실행 정책에서 차단되어 있다. 실패한부분녹화는덮어쓰지않으므로원인을확인하고별도로보존한뒤재실행해야한다. analysis재실행은측정CPU시간만달라질수있고고정된개발N선택이바뀌면거부한다.']
    (HERE/'REPORT.ko.md').write_text('\n'.join(lines)+'\n')
    print('WROTE',HERE/'REPORT.ko.md')

if __name__=='__main__':main()
