# Pipeline Architecture — UROPCLAW (as implemented)

코드(`harness/core/pipeline.py`)를 기준으로 정리했다(B). README의 다이어그램과 다른 부분은 아래 표에 따로 적었다.

```text
[CARLA camera sensor]  sensors/camera.py _on_frame()            ← Production input
[Replay source]        harness/replay/source.py → Pipeline.push_frame()   ← Test / benchmark input
        │  {camera_id, agent_id, frame, timestamp, cam_location, cam_rotation}
        ▼
 frame_queue (maxsize 4) ── full → frames_dropped
        ▼
 Thread YoloWorker
   ├ stale (> 2 s) → frames_dropped
   ├ mission inactive → skip
   ├ detector(frame)            default: YOLOv8s (conf 0.40, iou 0.45; car/motorcycle/bus/truck)
   ├ classify_color (HSV, central region, ≥15 % pixels)
   ├ IoUTracker per camera (IoU 0.30, reconnect 2 s / 80 px)
   ├ TemporalConfirm (3 frames, gap ≤ 1 s, ≥ 60 % majority, unknown-only rejected)
   └ target-colour filter
        ▼
 candidate_queue (maxsize 20) ── full → candidates_dropped  [validation: was frames_dropped]
        ▼
 Thread OpenClawWorker
   ├ Deduplicator.should_verify(agent_id)  30 s per agent (proposed only)  [validation: A/B were also deduplicated]
   ├ crop → workspaces/<agent>/state/crops/vreq_*.jpg
   └ VLM: `claude --print --model claude-haiku-4-5…` (timeout 25 s) → JSON
        └ any failure → FAIL OPEN: confirmed=True, confidence "n/a"   [validation: now counted]
        ▼
 result_queue (maxsize 20, blocking put)
        ▼
 Thread AlertWorker
   ├ AlertPolicy (mission id, colour score ≥ 0.15, YOLO conf ≥ 0.25, VLM confirmed + medium/high/n/a)
   ├ alerts_sent += 1  (attempt)
   ├ detection_event.json + crop evt_*.jpg
   └ alert sender  default: Discord REST (bot token per agent)  [validation: delivered/failed counted]
 Thread MetricsWriter (every 5 s → workspaces/uropclaw1/state/metrics.json)
 Thread CarlaTickThread (world.tick) — only when a CARLA world is given
```

## 식별자 전달

| ID | 전달 범위 |
|---|---|
| `camera_id`, `agent_id` | 프레임 → candidate → event |
| `timestamp` | 프레임 push 시각. event까지 유지되며, benchmark는 이 값으로 E2E를 계산한다 |
| `track_id` | tracker → candidate → event. baseline A/B는 -1 |
| `mission_id` | OpenClawWorker에서 mission.json을 읽어 부착 → AlertPolicy가 stale 여부를 판정 |
| `event_id` | AlertWorker가 uuid4로 생성 |
| `frame_id` | **없음.** 파이프라인은 프레임 번호를 전달하지 않는다. Replay 소스에는 `frame_id`가 있지만 `push_frame`이 받지 않는다 |
| `vehicle_id` | **없음.** 탐지 대상 차량의 CARLA ID는 파이프라인에 없다(카메라 영상만 사용) |

## README와 코드의 차이 (정적 확인)

| README | 코드 |
|---|---|
| VLM 검증은 "body_type 지정 시" | 모든 confirmed candidate를 검증한다(`test_vlm_is_called_without_body_type_in_mission`으로 확인) |
| VLM 타임아웃 30초 | 25초 |
| "Discord 알림 120초 쿨다운" | `Deduplicator.should_alert`(120 s)를 호출하는 곳이 없다. 실제 제한은 agent당 30 s VLM 검증(should_verify)이다 |
| "동일 트랙 30초" | dedup key가 `agent_id`다(commit 7af6246) |
| 5스레드 | world가 없으면 4스레드(validation 변경) |
