# Requirements — UROPCLAW AI Pipeline (Post-project Validation)

> 연구 종료 후(2026-10) 정리한 문서다. 출처 구분: Existing / Derived / Proposed. 증거 등급: A = 실행, B = 정적 분석, C = 제안.
> AI 모델의 정확도(YOLO, VLM)는 검증 범위가 아니다. 검증 대상은 **파이프라인의 데이터 전달, 장애 처리, 관측 가능성**이다.

| ID | 요구사항 | 출처 | 검증 |
|---|---|---|---|
| REQ-AP-001 | 목표 색상 차량이 연속 프레임에 보이면, 검증된 경보가 1건 생성되고 event와 crop이 기록된다. | Existing | A |
| REQ-AP-002 | 목표가 아닌 색상은 VLM 호출과 경보를 일으키지 않는다. | Existing | A |
| REQ-AP-003 | VLM 장애(timeout, 프로세스 오류, 응답 파싱 실패)가 나도 파이프라인은 멈추지 않는다. 경보는 fail-open으로 계속된다. | Existing ("Fail open: 시스템 중단 방지") | A |
| REQ-AP-004 | VLM timeout, 오류, 파싱 실패는 각각 지표(`openclaw_timeouts`, `openclaw_errors`, `openclaw_parse_failures`)로 관측된다. | Derived (`openclaw_timeouts` 필드가 이미 존재) | A |
| REQ-AP-005 | VLM이 거부(confirmed=false)하면 경보를 보내지 않는다. | Existing (AlertPolicy) | A |
| REQ-AP-006 | 경보 시도와 전달 결과(`alerts_sent` / `alerts_delivered` / `alerts_failed`)를 구분할 수 있다. | Derived | A |
| REQ-AP-007 | alert 전송이 실패하거나 예외가 나도 이후 처리는 계속된다. | Derived | A |
| REQ-AP-008 | 탐지 결과가 없으면 candidate, VLM 호출, 경보가 모두 0이다. | Derived | A |
| REQ-AP-009 | 잘못된 프레임(None, 잘못된 shape)이 들어와도 파이프라인은 멈추지 않는다. | Derived | A |
| REQ-AP-010 | 1 s를 넘는 tracking 공백이 있으면 시간적 확인이 초기화된다. | Existing (TemporalConfirm) | A |
| REQ-AP-011 | 2 s보다 오래된 프레임은 처리하지 않고 drop으로 집계한다. | Existing | A |
| REQ-AP-012 | frame_queue가 포화되면 프레임을 버리고 `frames_dropped`로 집계한다. | Existing | A |
| REQ-AP-013 | `frames_dropped`는 프레임 단위 drop만 센다. candidate 큐 포화는 `candidates_dropped`로 따로 센다. | Derived (README의 frame_drop_rate 정의) | A |
| REQ-AP-014 | 미션이 비활성이면 탐지를 수행하지 않는다. | Existing | A |
| REQ-AP-015 | baseline C는 VLM을 호출하지 않는다. A/B는 dedup 없이 VLM에 전달한다. | Existing (baseline.py, README §8) | A |
| REQ-AP-016 | CARLA, GPU, VLM, Discord 없이 동일 입력으로 파이프라인을 반복 실행할 수 있다(replay). | Proposed → 구현됨 | A |

## Proposed / 미구현

| ID | 내용 | 상태 |
|---|---|---|
| REQ-AP-P01 | VLM 장애 시 fail-open 대신 "검증 불가" 표시로 운영자에게 알리기 | C — 기존 설계(fail-open)는 유지. 지금은 집계만 함 |
| REQ-AP-P02 | `frame_id`를 프레임부터 event까지 전달 | C — `push_frame` 시그니처 변경이 필요해 보류 |
| REQ-AP-P03 | Discord 120 s 쿨다운(README) 구현 또는 README 수정 | C — 미수정 |
| REQ-AP-P04 | 단계별 지연(HSV, tracking)과 E2E 지연을 파이프라인 지표로 기록 | C — 지금은 detector 단계 지연만 기록. E2E는 benchmark 도구에서만 측정 |
