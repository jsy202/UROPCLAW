# Limitations — UROPCLAW Validation

| 항목 | 상태 |
|---|---|
| YOLOv8 탐지 정확도와 추론 지연 | 미검증. `FakeDetector`로 대체했다. ultralytics/torch를 설치하지 않았다 |
| 실제 VLM(`claude` CLI)의 응답 품질과 지연 | 미검증. VLM 프로세스 경계에서 fake로 대체했다. benchmark의 0.2 s는 **인위적인 값**이다 |
| Discord 실제 전송 | 미검증. sender의 반환값은 `requests.post`를 monkeypatch해서만 확인했다 |
| CARLA 카메라 입력과 좌표 추정(`_estimate_vehicle_pos`) | 미검증 |
| OpenClaw 게이트웨이, agent, mission.json 작성 흐름 | 미검증 |
| 합성 장면의 대표성 | 단색 박스와 회색 배경이다. 실제 영상의 조명, 가림, 원근은 반영하지 않는다 |
| 단계별 지연(HSV, tracking) | 파이프라인에 계측점이 없어 측정하지 않았다 |
| `frame_id`, `vehicle_id` 전달 | 파이프라인에 없다(제안만 함) |
| GitHub Actions | 실행 기록 없음(push 안 함). 로컬에서 같은 명령으로 확인했다 |
| research-baseline(`f0d7651`)에서 직접 테스트 | 불가. 주입 경계가 없다. 경계만 추가한 `312b8a3`을 Before로 사용했다 |

## 설계를 유지한 항목 (변경하지 않음)

- **VLM 장애 시 fail-open.** 이제 지표로 관측할 수 있지만, 경보 동작은 같다.
- `alerts_sent`의 의미(시도 횟수). 전달 결과는 새 지표로 분리했다.
- `docker`/OpenClaw 관련 코드, start.py/harness.py의 실행 경로.

## README와 코드의 차이 (정적 확인, 수정하지 않음)

- VLM 검증 조건(README: 차종 지정 시 / 코드: 항상)
- 타임아웃(README 30 s / 코드 25 s)
- Discord 120 s 쿨다운(README에만 있음)

## 연구 결과와의 관계

이 저장소에는 연구 당시의 수치 결과가 없다. 이번 benchmark는 합성 입력과 fake 의존성으로 얻은 **시스템 동작 측정**이며, 연구 당시 결과를 대체하거나 재해석하지 않는다.

DEF-U06(baseline A/B dedup) 수정은 A/B 모드의 VLM 호출 수를 바꾼다. 연구 당시 A/B 비교 수치가 있었다면 그 수치는 수정 전 동작으로 얻은 것이다.
