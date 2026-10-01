# Failure Model — UROPCLAW

각 장애를 테스트에서 주입하고, 관찰된 시스템 동작을 기록했다. "Before"는 수정 전 코드(`312b8a3`), "After"는 validation 최종 코드다. 모두 실행 결과다.

| 장애 | 주입 방법 | 기대 동작 | Before | After | 테스트 |
|---|---|---|---|---|---|
| VLM timeout | `TimeoutVLM` → `subprocess.TimeoutExpired` | 파이프라인 지속, fail-open 경보, 집계 | fail-open 동작, **집계 0** | `openclaw_timeouts`=1 | `test_vlm_timeout_*` |
| VLM 프로세스 오류 | `ErrorVLM` → `FileNotFoundError` | 위와 같음 | **집계 없음** | `openclaw_errors`=1 | `test_vlm_process_error_*` |
| VLM 응답 형식 오류 | `MalformedResponseVLM`(JSON 없음), BrokenJSON | 위와 같음 | **집계 없음** (BrokenJSON은 일반 예외 경로로 처리됨 — 정적 확인, B) | `openclaw_parse_failures`=1 | `test_vlm_malformed_*`, `test_vlm_broken_json_*` |
| VLM 거부 | `RejectVLM` | 경보 없음 | 같음 | 같음 | `test_vlm_rejection_blocks_alert` |
| alert 전송 실패 | `FakeAlert(fail="false")`, Discord 500, 토큰 없음 | 지속, 실패 집계 | `alerts_sent`=1 (실패 구분 불가) | `alerts_failed`=1 | `test_alert_delivery_failure_is_counted`, `test_discord_sender_*` |
| alert 전송 예외 | `FakeAlert(fail="raise")` | 다른 agent 처리는 계속 | 계속됨 | 계속됨, `alerts_failed` 증가 | `test_alert_exception_does_not_stop_pipeline` |
| 탐지 결과 없음 | `EmptyDetector` | candidate 0 | 같음 | 같음 | `test_empty_detection_*` |
| 잘못된 프레임 | `None`, 1차원 배열 | 예외는 worker 안에서 처리되고, 이후 프레임은 정상 처리 | 같음 | 같음 | `test_invalid_frame_*` |
| tracking 공백 | 1.3 s 공백 | 확인 초기화, VLM 0회 | 같음 | 같음 | `test_tracking_loss_*` |
| 오래된 프레임 | timestamp − 5 s | drop | 같음 | 같음 | `test_stale_frames_are_dropped` |
| frame_queue 포화 | worker 정지 상태에서 10 push | 4개 보관, 6 drop | 같음 | 같음 | `test_frame_queue_saturation_*` |
| candidate_queue 포화 | 큐가 가득 찬 상태에서 3 candidate | candidate drop 별도 집계 | **frames_dropped=3** | `candidates_dropped`=3, `frames_dropped`=0 | `test_candidate_queue_overflow_*` |
| 미션 비활성 | `active: false` | 탐지 안 함 | 같음 | 같음 | `test_inactive_mission_skips_processing` |
| baseline A/B dedup | B 모드, 5개 탐지 | VLM 5회 | **VLM 1회, 억제 4회** | VLM 5회 | `test_baseline_*` |

## 설계상 위험 (수정하지 않음)

- **Fail-open:** VLM이 완전히 장애 상태여도 목표 색상 candidate는 경보로 이어진다(agent당 30 s에 1건). 이번 수정으로 이 상황이 지표로 보이게 되었을 뿐, 동작은 그대로다.
- **`result_queue.put()`이 blocking:** AlertWorker가 느리면(Discord timeout 최대 8 s) OpenClawWorker가 막히고, 이어서 candidate 큐가 포화된다. benchmark 범위 안에서는 관찰되지 않았다(결과 큐 최대 깊이는 `benchmark.md` 참조).
