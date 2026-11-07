"""Six no-temporal comparisons. Reuse existing archives; never render or call VLM."""
import json
import os
from pathlib import Path
import study
HERE=Path(__file__).resolve().parent


def configurations():
    base=dict(n=1,rule='current',temporal=False,architecture='current')
    out=[]
    for hsv,dedup,name in [(False,False,'neither'),(False,True,'dedup_only'),(True,False,'hsv_only'),(True,True,'hsv_dedup')]:
        out.append(dict(base,name=name,family='presence',hsv=hsv,dedup=dedup))
    for arch in ('early_hsv','late_hsv'):
        out.append(dict(base,name=arch,family='order',hsv=True,dedup=True,architecture=arch))
    return out


def plots(output,rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    for group,names in [('presence',['neither','dedup_only','hsv_only','hsv_dedup']),('order',['hsv_dedup','early_hsv','late_hsv'])]:
        fig,axes=plt.subplots(1,3,figsize=(13,4))
        for ax,field,title in zip(axes,['detected_recall','requests','request_p95_s'],['Detected target episode recall','Request triggers (no VLM calls)','First request delay p95 (sim s)']):
            ax.bar(names,[rows[name][field] for name in names]);ax.set_ylabel(title)
            ax.tick_params(axis='x',rotation=30);ax.grid(axis='y',alpha=.2)
            if field=='detected_recall':ax.set_ylim(0,1.05)
            if field=='requests' and group=='presence':ax.set_yscale('log')
        fig.suptitle('No temporal stage: same40 recordings, held-out24')
        fig.tight_layout();fig.savefig(output/(group+'.png'),dpi=170);plt.close(fig)


def main():
    from analyze import aggregate,paired_ci
    policy=json.loads((HERE/'execution_policy.json').read_text())
    assert policy['allow_real_vlm'] is False
    output=HERE/'no_temporal_structure';output.mkdir(exist_ok=True)
    summaries=[];scores=[]
    sources=sorted((HERE/'runs').iterdir())
    assert len(sources)==40
    for index,source in enumerate(sources):
        work=output/'replays'/source.name;work.mkdir(parents=True,exist_ok=True)
        for name in ('manifest.json','frames.jsonl','images'):
            target=work/name
            if not target.exists():target.symlink_to(os.path.relpath(source/name,work),target_is_directory=name=='images')
        summary,episodes,_=study.replay(work,configurations())
        summaries.extend(summary);scores.extend(episodes)
        print('STRUCTURE',index+1,'/40',source.name,flush=True)
    rows=aggregate(summaries,scores)
    study.csv_write(output/'aggregate.csv',rows)
    study.csv_write(output/'per_recording.csv',summaries)
    study.csv_write(output/'episodes.csv',scores)
    study.csv_write(output/'paired_vs_current.csv',paired_ci(summaries,'test',base='hsv_dedup'))
    test={r['config']:r for r in rows if r['split']=='test'}
    lines=['# 시간적 확인 제거 후 필터 유무·배치 비교','',
           '기존40개 녹화와 동일한 YOLO/HSV 캐시를 재사용했다. 추가녹화와 실제VLM호출은없다. 평가24개/개발16개를 유지하며, 모든구성에서temporal=False다. 이전26구성의원자료·결과파일은덮어쓰지않았다.','',
           '| 구성 | HSV | dedup | 추적과 색상 선별의 관계 |', '|---|---|---|---|',
           '| neither | 끔 | 끔 | 모든 차량 추적·후보 |',
           '| dedup_only | 끔 | 켬 | 모든 차량 추적 후 중복 억제 |',
           '| hsv_only | 켬 | 끔 | 색상 라벨 부여 → 전체 차량 추적 → 목표 색 gate |',
           '| hsv_dedup (현재) | 켬 | 켬 | 색상 라벨 부여 → 전체 차량 추적 → 목표 색 gate → dedup |',
           '| early_hsv | 켬 | 켬 | 목표 색 검출만 남김 → 추적 → dedup |',
           '| late_hsv | 켬 | 켬 | 색상을 사용하지 않고 추적 → 현재 색 gate → dedup |','',
           'HSV를끄면색상정보를추적재연결과중복연속성에도사용하지않는다. 따라서HSV제거효과에는단순목표색선별뿐아니라ID연결의변화도포함된다.', '', 'dedup은track식별자를필요로하므로추적앞으로단순교환하지않는다. 후보가통과하기전에쿨다운을소비하는설계도같은정책의순서변경이라고취급하지않았다. 배치대안은추적에색상정보를사용하는방식도바꾸므로순서만의인과효과가아니다.','',
           '## 평가 결과','',
           '| 구성 | 도달 출현/121 | 도달률 | 도달 고유 차량/92 | 요청 트리거 | 비목표 요청 | 미확정 요청 | 요청 지연 p95(s) |',
           '|---|---:|---:|---:|---:|---:|---:|---:|']
    for config in configurations():
        r=test[config['name']]
        delay='—' if r['request_p95_s'] is None else '%.3f'%r['request_p95_s']
        lines.append('| %s | %d | %.1f%% | %d | %d | %d | %d | %s |'%(r['config'],r['reached_targets'],100*r['detected_recall'],r['reached_unique_target_actors'],r['requests'],r['nontarget_requests'],r['unassociated_requests'],delay))
    lines+=['','도달률은검출된출현구간기준이며실제VLM정확도가아니다. 요청은검증을요구했을트리거다. 미확정요청을입증된오검출로부르지않는다. 지연은첫검출→요청트리거까지의시뮬레이션시간이고VLM응답·최종경보지연은미측정이다.','',
            'YOLO/HSV를한번계산한캐시로판단흐름을비교했으므로구조전체의실제계산시간절감을입증하지않는다. GT연결근사·지도별날씨조건차이등한계는[기존실험요약](../SUMMARY.ko.md)과같다.','',
            '[녹화별 결과](per_recording.csv) · [현재 구조 대비 paired 구간](paired_vs_current.csv)']
    plots(output,test)
    lines+=['','![필터 유무](presence.png)','','![HSV 배치](order.png)','','현재구조와두배치대안은도달률이같고요청130~133건으로차이가작았다. 특정순서가유일한정답이라고단정하지않고현재배치를유지하며시간적확인만제외한다.']
    lines+=['','## 최종 권장 구조','','**YOLO → HSV 색상 라벨 → 전체 차량 추적 → 현재 목표 색 선별 → 대상별 중복 억제 → 검증 요청**. 기존 구조에서 시간적 확인만 제외했다. HSV+dedup은110/121출현·131요청이고 HSV만 쓰면111/121·2036요청이므로 도달과 요청량의 절충이다. 배치 대안은 도달률이 같고 요청130~133건으로 차이가 작아 기존 순서를 유지한다. 이는 이번 실험 범위의 권장안이며 절대 최적이나 실제VLM 이후 성능을 입증한 것이 아니다.']
    (output/'REPORT.ko.md').write_text('\n'.join(lines)+'\n')
    print('STRUCTURE COMPLETE',output,flush=True)

if __name__=='__main__':main()
