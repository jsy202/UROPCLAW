# Test Cases — UROPCLAW

모든 테스트는 CARLA, GPU, `claude` CLI, Discord 없이 실행된다. 실제 파이프라인 단계(HSV, IoU tracker, TemporalConfirm, Deduplicator, VLM 프롬프트 생성과 파싱, AlertPolicy, event 기록)를 사용한다. 외부 의존성 3개만 fake로 바꾼다.

"Before" 열은 현재 테스트를 수정 전 코드(`312b8a3`)에 실행한 결과다(`evidence/baseline_crosscheck.txt`).

## Integration — 정상 흐름 (`test_pipeline_happy_path.py`)

| TC | 테스트 | 기대 | REQ |
|---|---|---|---|
| TC-01 | `test_blue_vehicle_replay_produces_one_verified_alert` | 6 프레임 → VLM 1회 → 경보 1건, event/crop/mission_id 일치, frames 6/6 | AP-001 |
| TC-02 | `test_non_target_colour_produces_no_vlm_call_and_no_alert` | 빨간 차량 → VLM 0, 경보 0 | AP-002 |

## Integration — 장애 (`test_pipeline_failures.py`)

| TC | DEF | 테스트 | REQ |
|---|---|---|---|
| TC-03 | – | `test_vlm_timeout_fails_open_and_still_alerts` | AP-003 |
| TC-04 | U01 | `test_vlm_timeout_is_counted` | AP-004 |
| TC-05 | U02 | `test_vlm_process_error_fails_open_and_is_counted` | AP-003, 004 |
| TC-06 | U03 | `test_vlm_malformed_response_fails_open_and_is_counted` | AP-003, 004 |
| TC-07 | – | `test_vlm_broken_json_is_counted_as_parse_failure` | AP-004 |
| TC-08 | – | `test_vlm_rejection_blocks_alert` | AP-005 |
| TC-09 | – | `test_vlm_is_called_without_body_type_in_mission` (README와 다른 동작을 기록) | – |
| TC-10 | – | `test_alerts_sent_counts_attempts_not_deliveries` (기존 의미를 기록) | AP-006 |
| TC-11 | U04 | `test_alert_delivery_failure_is_counted` | AP-006 |
| TC-12 | – | `test_successful_alert_is_counted_as_delivered` | AP-006 |
| TC-13 | – | `test_discord_sender_without_token_reports_not_delivered` | AP-006 |
| TC-14 | – | `test_discord_sender_http_error_reports_not_delivered` (requests.post를 monkeypatch, 네트워크 없음) | AP-006 |
| TC-15 | – | `test_alert_exception_does_not_stop_pipeline` | AP-007 |
| TC-16 | – | `test_empty_detection_produces_no_candidates` | AP-008 |
| TC-17 | – | `test_invalid_frame_does_not_stop_pipeline` | AP-009 |
| TC-18 | – | `test_tracking_loss_resets_temporal_confirmation` | AP-010 |
| TC-19 | – | `test_stale_frames_are_dropped` | AP-011 |
| TC-20 | – | `test_frame_queue_saturation_drops_and_counts` | AP-012 |
| TC-21 | – | `test_inactive_mission_skips_processing` | AP-014 |
| TC-22 | U05 | `test_candidate_queue_overflow_is_not_counted_as_frame_drop` | AP-013 |

## Integration — baseline 모드 (`test_baseline_modes.py`)

| TC | DEF | 테스트 | REQ |
|---|---|---|---|
| TC-23 | – | `test_baseline_c_never_calls_vlm` | AP-015 |
| TC-24 | U06 | `test_baseline_b_sends_every_detection_to_vlm_without_dedup` | AP-015 |
| TC-25 | U06 | `test_baseline_a_sends_every_nth_frame_to_vlm_without_dedup` | AP-015 |

## Unit (`tests/unit/test_perception_units.py`)

TC-26 ~ TC-36(11건): HSV 분류(blue/red, 퇴화 bbox), IoU, tracker ID 유지, TemporalConfirm(3 프레임 확인, 공백 초기화, unknown 거부), Deduplicator 30 s, AlertPolicy(허용, stale, 낮은 YOLO 신뢰도, fail-open "n/a" 통과).

## Benchmark (`tools/replay_benchmark.py`)

테스트가 아니라 측정용이다. 결과는 `benchmark.md`에 있다.

## 미실행

| ID | 내용 |
|---|---|
| ST-01 | 실제 CARLA 카메라 + YOLOv8(GPU) 탐지 정확도와 지연 |
| ST-02 | 실제 `claude` CLI(VLM)의 응답 품질과 지연 |
| ST-03 | Discord 실제 전송 |
| ST-04 | OpenClaw 게이트웨이와 4개 agent의 mission 처리 |
