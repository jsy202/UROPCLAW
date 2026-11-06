# 필터를 단계적으로 추가하는 비교

고정한 30개 조건을 각각 **10Hz · 시뮬레이션 10분 · 6,000장**으로 새로 수집한다. 총 180,000장이다. 개발 12개와 평가 18개를 분리하고, 모든 비교 구성에 같은 검출·색상 캐시를 입력한다. 실제 VLM과 알림은 호출하지 않는다.

처음에는 40개를 계획했으나 사용자 요청으로 30번째에서 수집을 마쳤다. 이번 비교는 Town10HD_Opt의 3환경 × 2밀도 × 5seed이며 두 번째 지도는 포함하지 않는다. 선택 기준은 그대로 유지했다.

구성은 공통 추적 기반에서 **YOLO 후보 → HSV 추가 → 대상별 중복 억제 추가 → 연속 확인 추가·검토**로 설명한다. 추가한 필터의 요청 절감과 함께 목표 손실·지연을 보고한다. 연속 확인은 새 평가에서도 실익이 부족하면 도입 후 제외한 시행착오로 기록한다. 이전 3분 실험의 결론을 이번 결과로 가정하지 않는다.

‘연속 확인’은 기존 모듈의 이름이다. 기존 N3는 같은 track의 관측 3개를 모아 unknown을 제외하고 색상 투표를 하며, 판정 뒤 모음을 비운다. 3프레임 모두 목표 색이어야 한다는 뜻은 아니다. N=1/2/3/5/7/10과 투표 규칙 대안을 나누어 비교한다.

- [고정 실험 명세](PROTOCOL.ko.md)
- [제안·시행착오·문제 해결 기록](RESEARCH_LOG.ko.md)
- [최종 결론과 권장 구조](SUMMARY.ko.md)
- [전체 결과와 해석](REPORT.ko.md)
- [검증 기록](VERIFICATION.md)
- [개발 선택](results/dev_selection.json) — 개발 자료에서만 선택해 고정
- [최종 판정](results/decision.json) — 평가 결과로 선택을 바꾸지 않음
- [전체 결과](results/aggregate.csv) · [조건별 결과](results/stratified.csv)
- [원자료 무결성 목록](results/archive_inventory.csv)
- [소스 해시](source_manifest.json) · [과거 로컬 체크포인트와 공개 소스의 구분](SOURCE_PROVENANCE.md)
- [이전 3분 탐색 실험](../temporal_filter_study/README.md)

저장소 루트에서 실행한다. 수집기는 진행 중인 다른 CARLA 서버를 종료하지 않는다. 완료한 동일 조건은 건너뛰며, 부분 녹화는 자동 덮어쓰지 않는다.

```bash
.venv-carla-e2e/bin/python -u validation/carla_e2e/progressive_filter_study/run_batch.py
.venv-carla-e2e/bin/python -u validation/carla_e2e/progressive_filter_study/postprocess.py
```

두 번째 명령은 전체 수집이 끝날 때까지 기다린 뒤 28개 구성의 재생, 누락 진단, 개발 색상 점검, 합성 반례, 이미지 무결성 검증, 보고서 생성을 수행한다. 이미 수집한 자료만으로 후처리할 때도 같은 명령을 쓴다. 모델이나 VLM을 추가로 호출하지 않는다.

로컬 원자료는 `runs/<조건>/`에 보존한다.

- `images/000000.jpg` … `005999.jpg`: 모든 프레임, JPEG quality 85.
- `frames.jsonl`: 원본 센서 입력에서 계산한 YOLO/HSV, GT 투영, 시각.
- `manifest.json`: 지도·기상·차량·seed·모델 해시·환경·actor 정리 결과.
- `images.sha256`: 검증 단계에서 작성하는 이미지별 해시.
- `analysis/`: 구성별 사건과 출현별 점수.

JPEG는 확인용 저장 이미지다. 비교에는 JPEG를 재추론하지 않고 원본 센서 입력의 동일 캐시를 사용한다. 큰 원자료는 Git에서 제외하고 결과표·대표 이미지·코드는 포함한다.
