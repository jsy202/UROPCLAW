# Experiment B: 10-minute continuous monitoring / pipeline efficiency ablation

Run label: `dry_run_45s`. All numbers come from one continuous host CARLA run
(`evidence/result.json`, `evidence/frame_metrics.csv`). Experiment A
(`../multivehicle/validation_report.md`, system integration / stability) is unchanged.

Question: on the same 45.0 s of dynamic CARLA traffic, how much does the
VLM workload grow when HSV, Temporal Confirmation or Deduplication is removed?

## Setup

- CARLA 0.9.13 `Carla/Maps/Town10HD_Opt`, synchronous 0.1 s ticks, seed 42; 70 TM-autopilot vehicles
  (4-wheel blueprints with paintable colour, deterministic 8-colour palette incl. blue);
  fixed CCTV 800x600 FOV 90 at 10 Hz (pose reused from Experiment A); 5.0 s pre-roll.
- Real YOLOv8s (yolov8s.pt, conf 0.40) runs once per frame on the NVIDIA GeForce RTX 3060. The identical frame,
  detections and HSV colours are fanned out to four shadow branches with independent
  production IoUTracker / TemporalConfirm / Deduplicator instances.
- Branch logic replicates production YoloWorker + OpenClawWorker dedup; equivalence
  with the production Pipeline is unit-tested (`tests/validation/test_continuous_ablation_branches.py`).
- A VLM trigger is the point where production would call the VLM (after dedup). No VLM
  is called; these are trigger counts, not Real VLM inferences.
- Temporal, dedup and tracker-reconnect windows use simulation time (a real-time 10 Hz
  camera's timestamps). Production dedup is per camera agent with a 30 s cooldown.

## Ablation comparison (same traffic, same detections)

| Configuration | VLM Triggers | vs Full increase | vs Full ratio |
|---|---:|---:|---:|
| Full | 1 | - | 1.00x |
| No HSV | 2 | +1 | 2.00x |
| No Temporal | 1 | +0 | 1.00x |
| No Dedup | 20 | +19 | 20.00x |

Stage contributions (ablation comparison on identical input, not a causal claim):

- HSV: removing it changes VLM triggers 1 -> 2 (+1; 2.00x).
- Temporal Confirmation: removing it changes VLM triggers 1 -> 1 (+0; 1.00x).
- Deduplication: removing it changes VLM triggers 1 -> 20 (+19; 20.00x).

Because dedup is a 30 s per-camera cooldown, any branch that keeps dedup is bounded by
roughly duration/30 s triggers; the dedup-free branch shows the candidate volume that
dedup absorbs. Candidate counts below show what HSV and Temporal remove before dedup.

## Per-branch metrics

| Metric | Unit | Full | No HSV | No Temporal | No Dedup |
|---|---|---:|---:|---:|---:|
| hsv_candidate_detections | detections | 43 | 440 | 43 | 43 |
| frames_with_hsv_candidate | frames | 43 | 259 | 43 | 43 |
| active_target_track_observations | track-frames | 43 | 440 | 43 | 43 |
| frames_with_active_target_track | frames | 43 | 259 | 43 | 43 |
| temporal_confirmations_passing_gate | events | 20 | 244 | 43 | 20 |
| frames_triggering_confirmation | frames | 20 | 144 | 43 | 20 |
| candidates_raised | candidates | 20 | 244 | 43 | 20 |
| duplicate_suppressed | candidates | 19 | 242 | 42 | 0 |
| vlm_triggers | requests | 1 | 2 | 1 | 20 |
| frames_with_vlm_trigger | frames | 1 | 2 | 1 | 20 |
| unique_tracks_triggering | tracks | 1 | 2 | 1 | 3 |
| unique_actors_triggering | actors | 1 | 2 | 1 | 1 |
| candidates_target_actor | candidates | 17 | 17 | 43 | 17 |
| candidates_non_target_actor | candidates | 0 | 135 | 0 | 0 |
| candidates_unassociated | candidates | 3 | 92 | 0 | 3 |
| triggers_target_actor | requests | 1 | 0 | 1 | 17 |
| triggers_non_target_actor | requests | 0 | 2 | 0 | 0 |
| triggers_unassociated | requests | 0 | 0 | 0 | 3 |
| max_candidates_in_one_frame | candidates | 1 | 6 | 1 | 1 |
| dropped_frames | frames | 0 | 0 | 0 | 0 |
| branch_exceptions | exceptions | 0 | 0 | 0 | 0 |

For No HSV, every detection/track is a candidate by construction (no colour gate).
Actor association (IoU >= 0.30 with a projected CARLA box) is evidence only;
`non_target_actor` candidates are false-target candidates, `unassociated` could not
be matched to any projected vehicle (e.g. YOLO false positives, occlusion).
The shadow branches are synchronous: no queue exists, so queue depth is reported as
the maximum number of candidates produced in one frame; drops are camera frames lost.

## Full pipeline frame funnel (frame units only)

| Stage | Count | Previous-stage retention | Input ratio |
|---|---:|---:|---:|
| input_frames | 450 | n/a | 1 |
| frames_with_yolo_vehicle_detection | 259 | 0.5756 | 0.5756 |
| frames_with_target_hsv_candidate | 43 | 0.166 | 0.0956 |
| frames_with_active_target_track | 43 | 1 | 0.0956 |
| frames_triggering_temporal_confirmation | 20 | 0.4651 | 0.0444 |
| frames_triggering_vlm | 1 | 0.05 | 0.0022 |

## Traffic

| Item | Value |
|---|---:|
| simulation_duration_s | 45 |
| input_frames | 450 |
| dropped_camera_frames | 0 |
| spawned_vehicles | 70 |
| spawned_target_color_vehicles | 9 |
| unique_vehicles_entering_fov | 19 |
| unique_vehicles_entering_fov_3plus_frames | 17 |
| target_color_vehicles_entering_fov | 1 |
| non_target_vehicles_entering_fov | 18 |
| unique_vehicles_matched_by_yolo | 15 |
| target_color_vehicles_matched_by_yolo | 1 |
| total_yolo_vehicle_detections | 440 |
| frames_with_vehicle_detection | 259 |
| frames_with_no_yolo_detection | 191 |
| frames_with_no_visible_vehicle | 111 |
| mean_detections_per_frame | 0.9778 |
| p95_detections_per_frame | 3 |
| max_detections_per_frame | 4 |
| yolo_latency_ms_mean | 14.608 |
| yolo_latency_ms_p95 | 15.926 |

FOV entry = projected box height >= 12 px, distance <= 80 m and clear centre
line of sight (`world.cast_ray`).

Colour distribution (spawned / entered FOV):

| Colour (RGB) | Spawned | Entered FOV |
|---|---:|---:|
| 0,0,255 (target blue) | 9 | 1 |
| 255,0,0 | 8 | 1 |
| 255,255,255 | 9 | 4 |
| 10,10,10 | 9 | 3 |
| 150,150,150 | 9 | 3 |
| 0,200,0 | 9 | 2 |
| 255,255,0 | 8 | 3 |
| 255,140,0 | 9 | 2 |

Blueprints that entered the FOV: 17 distinct (vehicle.audi.etron x1, vehicle.audi.tt x1, vehicle.carlamotors.carlacola x1, vehicle.citroen.c3 x1, vehicle.dodge.charger_2020 x1, vehicle.dodge.charger_police x1, vehicle.dodge.charger_police_2020 x1, vehicle.ford.crown x1, vehicle.jeep.wrangler_rubicon x1, vehicle.lincoln.mkz_2020 x1, vehicle.mercedes.coupe x1, vehicle.mini.cooper_s_2021 x2, vehicle.nissan.micra x2, vehicle.nissan.patrol x1, vehicle.seat.leon x1, vehicle.tesla.model3 x1, vehicle.toyota.prius x1).

## Per-minute summary

| Minute | Unique vehicles | Target vehicles | YOLO detections | Mean visible | Moving vehicles | Full | No HSV | No Temporal | No Dedup |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 19 | 1 | 440 | 1.387 | 70/70 | 1 | 2 | 1 | 20 |

Moving vehicles: displaced > 5 m between the start of the minute and the next.

## Stability

- Memory (RSS MB / CUDA allocated MB) samples: 0.0s: 3335.2/42.6, 44.9s: 3338.0/42.6
- Branch exceptions: 0; dropped camera frames: 0.
- Cleanup: {"attempted": 71, "destroyed": 71, "failed_actor_ids": []}

## Interpretation limits

- One continuous run on one camera pose and one map; trigger counts are not
  repeated-measure statistics and do not generalise to other traffic or scenes.
- VLM triggers are counted, not executed; no Real VLM accuracy or latency is measured.
- Input frames -> VLM triggers is not a single 'filtering effect': the stages are
  separated above and dedup is a time-based cooldown.
- Ground truth projection/line of sight is evidence only and approximate (centre ray).
- Wall-clock processing in synchronous CARLA is not real-time road latency.
- Historical 46,372 / 28,736 / 3,298 / 53 values are not compared (units not established).
