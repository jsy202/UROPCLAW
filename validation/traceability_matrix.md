# Traceability Matrix — UROPCLAW

Requirement → Production code (`harness/core/pipeline.py` 라인, validation 브랜치) → Test → 결과.

- Before = 현재 테스트를 `312b8a3`(경계 추가, 결함 수정 전)에 실행한 결과(`evidence/baseline_crosscheck.txt`)
- Current = 최종 결과

| REQ | Production code | Test | Before | Current | Commit |
|---|---|---|---|---|---|
| AP-001 | 전 단계. `push_frame` L808, YoloWorker, OpenClawWorker, AlertWorker | TC-01 | PASS | PASS | – |
| AP-002 | target colour filter (YoloWorker) | TC-02 | PASS | PASS | – |
| AP-003 | fail-open L518–, AlertPolicy "n/a" (`policy/alert_policy.py` L36) | TC-03, 05, 06 | PASS, FAIL\*, FAIL\* | PASS | – (기존 설계) |
| AP-004 | L509 parse, L512 timeout, L515 errors | TC-04, 05, 06, 07 | FAIL ×4 | PASS | `f20d51f` |
| AP-005 | AlertPolicy | TC-08 | PASS | PASS | – |
| AP-006 | L564 `alerts_sent`(시도), L621 delivered/failed, `_enqueue_discord_alert` L628 → bool | TC-10–14 | TC-10 PASS, 나머지 FAIL | PASS | `6878cb4` |
| AP-007 | `_write_event` sender 예외 처리 L621– | TC-15 | PASS | PASS | (`6878cb4`에서 예외를 직접 처리하도록 변경) |
| AP-008 | YoloWorker `if not detections` | TC-16 | PASS | PASS | – |
| AP-009 | YoloWorker `except Exception` | TC-17 | PASS | PASS | – |
| AP-010 | `perception/temporal_confirm.py` | TC-18, unit | PASS | PASS | – |
| AP-011 | L158 | TC-19 | PASS | PASS | – |
| AP-012 | `push_frame` L808– | TC-20 | PASS | PASS | – |
| AP-013 | L187, L225, L288 `candidates_dropped` | TC-22 | FAIL | PASS | `2bfced2` |
| AP-014 | L162 | TC-21 | PASS | PASS | – |
| AP-015 | L182, L220 `dedup_enabled(mode)`, L404 | TC-23, 24, 25 | PASS, FAIL, FAIL | PASS | `0d79f2d` |
| AP-016 | `Pipeline(detector, vlm_runner, alert_sender)` L124/389/543, `world=None` L772, `harness/replay/source.py` | 전체 스위트, benchmark | – | PASS | `a70e54d` (경계), `312b8a3` (replay) |

\* TC-05와 06은 fail-open과 집계를 함께 확인한다. Before에서는 집계 부분이 실패했다.

## Defect → cause → fix

| DEF | 원인 | 기록 | 수정 |
|---|---|---|---|
| U01 | `openclaw_timeouts`를 초기화만 하고 증가시키지 않음 | `312b8a3` | `f20d51f` |
| U02 | VLM 프로세스 예외를 로그로만 남김 | `312b8a3` | `f20d51f` |
| U03 | 파싱 실패를 로그로만 남기고, 깨진 JSON은 일반 예외로 처리 | `312b8a3` | `f20d51f` |
| U04 | `alerts_sent`를 전달 전에 증가시키고, sender는 결과를 반환하지 않음 | `312b8a3` | `6878cb4` |
| U05 | candidate 큐 포화를 `frames_dropped`로 집계 | `312b8a3` | `2bfced2` |
| U06 | A/B candidate에 `dedup_enabled` 키가 없고, 기본값이 True | `33c794d` | `0d79f2d` |
