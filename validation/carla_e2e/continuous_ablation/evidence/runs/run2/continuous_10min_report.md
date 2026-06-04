# Experiment B: 10-minute continuous monitoring / pipeline efficiency ablation

Run label: `full_10min`. All numbers come from one continuous host CARLA run
(`evidence/result.json`, `evidence/frame_metrics.csv`). Experiment A
(`../multivehicle/validation_report.md`, system integration / stability) is unchanged.

Question: on the same 600.0 s of dynamic CARLA traffic, how much does the
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
| Full | 11 | - | 1.00x |
| No HSV | 19 | +8 | 1.73x |
| No Temporal | 11 | +0 | 1.00x |
| No Dedup | 222 | +211 | 20.18x |

Stage contributions (ablation comparison on identical input, not a causal claim):

- HSV: removing it changes VLM triggers 11 -> 19 (+8; 1.73x).
- Temporal Confirmation: removing it changes VLM triggers 11 -> 11 (+0; 1.00x).
- Deduplication: removing it changes VLM triggers 11 -> 222 (+211; 20.18x).

Because dedup is a 30 s per-camera cooldown, any branch that keeps dedup is bounded by
roughly duration/30 s triggers; the dedup-free branch shows the candidate volume that
dedup absorbs. Candidate counts below show what HSV and Temporal remove before dedup.

## Per-branch metrics

| Metric | Unit | Full | No HSV | No Temporal | No Dedup |
|---|---|---:|---:|---:|---:|
| hsv_candidate_detections | detections | 400 | 4305 | 400 | 400 |
| frames_with_hsv_candidate | frames | 375 | 2800 | 375 | 375 |
| active_target_track_observations | track-frames | 400 | 4305 | 400 | 400 |
| frames_with_active_target_track | frames | 375 | 2800 | 375 | 375 |
| temporal_confirmations_passing_gate | events | 222 | 2434 | 400 | 222 |
| frames_triggering_confirmation | frames | 197 | 1625 | 375 | 197 |
| candidates_raised | candidates | 222 | 2434 | 400 | 222 |
| duplicate_suppressed | candidates | 211 | 2415 | 389 | 0 |
| vlm_triggers | requests | 11 | 19 | 11 | 222 |
| frames_with_vlm_trigger | frames | 11 | 19 | 11 | 197 |
| unique_tracks_triggering | tracks | 11 | 19 | 11 | 40 |
| unique_actors_triggering | actors | 7 | 7 | 8 | 11 |
| target_actors_with_candidate | actors | 9 | 9 | 9 | 9 |
| target_actors_with_vlm_trigger | actors | 5 | 0 | 6 | 9 |
| candidates_target_actor | candidates | 132 | 146 | 345 | 132 |
| candidates_non_target_actor | candidates | 17 | 1347 | 53 | 17 |
| candidates_unassociated | candidates | 73 | 941 | 2 | 73 |
| triggers_target_actor | requests | 7 | 0 | 8 | 132 |
| triggers_non_target_actor | requests | 3 | 7 | 3 | 17 |
| triggers_unassociated | requests | 1 | 12 | 0 | 73 |
| max_candidates_in_one_frame | candidates | 2 | 6 | 2 | 2 |
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
| input_frames | 6000 | n/a | 1 |
| frames_with_yolo_vehicle_detection | 2800 | 0.4667 | 0.4667 |
| frames_with_target_hsv_candidate | 375 | 0.1339 | 0.0625 |
| frames_with_active_target_track | 375 | 1 | 0.0625 |
| frames_triggering_temporal_confirmation | 197 | 0.5253 | 0.0328 |
| frames_triggering_vlm | 11 | 0.0558 | 0.0018 |

## Traffic

| Item | Value |
|---|---:|
| simulation_duration_s | 600 |
| input_frames | 6000 |
| dropped_camera_frames | 0 |
| spawned_vehicles | 70 |
| spawned_target_color_vehicles | 9 |
| unique_vehicles_entering_fov | 67 |
| unique_vehicles_entering_fov_3plus_frames | 67 |
| target_color_vehicles_entering_fov | 9 |
| non_target_vehicles_entering_fov | 58 |
| unique_vehicles_matched_by_yolo | 67 |
| target_color_vehicles_matched_by_yolo | 9 |
| total_yolo_vehicle_detections | 4305 |
| frames_with_vehicle_detection | 2800 |
| frames_with_no_yolo_detection | 3200 |
| frames_with_no_visible_vehicle | 2357 |
| mean_detections_per_frame | 0.7175 |
| p95_detections_per_frame | 3 |
| max_detections_per_frame | 6 |
| longest_no_visible_vehicle_frames | 215 |
| longest_no_yolo_detection_frames | 219 |
| ten_second_windows_with_visible_vehicle | 57 |
| ten_second_windows_total | 60 |
| yolo_latency_ms_mean | 14.676 |
| yolo_latency_ms_p95 | 16.183 |

FOV entry = projected box height >= 12 px, distance <= 80 m and clear centre
line of sight (`world.cast_ray`).

Colour distribution (spawned / entered FOV):

| Colour (RGB) | Spawned | Entered FOV |
|---|---:|---:|
| 0,0,255 (target blue) | 9 | 9 |
| 255,0,0 | 8 | 8 |
| 255,255,255 | 9 | 9 |
| 10,10,10 | 9 | 8 |
| 150,150,150 | 9 | 9 |
| 0,200,0 | 9 | 8 |
| 255,255,0 | 8 | 8 |
| 255,140,0 | 9 | 8 |

Blueprints that entered the FOV: 31 distinct (vehicle.audi.a2 x2, vehicle.audi.etron x2, vehicle.audi.tt x2, vehicle.bmw.grandtourer x1, vehicle.carlamotors.carlacola x2, vehicle.carlamotors.firetruck x3, vehicle.chevrolet.impala x3, vehicle.citroen.c3 x2, vehicle.dodge.charger_2020 x2, vehicle.dodge.charger_police x2, vehicle.dodge.charger_police_2020 x3, vehicle.ford.ambulance x2, vehicle.ford.crown x3, vehicle.ford.mustang x1, vehicle.jeep.wrangler_rubicon x3, vehicle.lincoln.mkz_2017 x2, vehicle.lincoln.mkz_2020 x2, vehicle.mercedes.coupe x2, vehicle.mercedes.coupe_2020 x1, vehicle.mercedes.sprinter x3, vehicle.micro.microlino x2, vehicle.mini.cooper_s x2, vehicle.mini.cooper_s_2021 x2, vehicle.nissan.micra x2, vehicle.nissan.patrol x3, vehicle.nissan.patrol_2021 x2, vehicle.seat.leon x2, vehicle.tesla.model3 x3, vehicle.toyota.prius x2, vehicle.volkswagen.t2 x2, vehicle.volkswagen.t2_2021 x2).

## Per-minute summary

| Minute | Unique vehicles | Target vehicles | YOLO detections | Mean visible | Moving vehicles | Full | No HSV | No Temporal | No Dedup |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 22 | 1 | 561 | 1.332 | 70/70 | 1 | 2 | 1 | 20 |
| 1 | 14 | 4 | 275 | 0.773 | 70/70 | 2 | 2 | 2 | 32 |
| 2 | 22 | 2 | 568 | 1.367 | 70/70 | 1 | 2 | 1 | 17 |
| 3 | 20 | 3 | 623 | 1.397 | 70/70 | 1 | 2 | 1 | 39 |
| 4 | 12 | 2 | 305 | 0.808 | 67/70 | 1 | 2 | 1 | 17 |
| 5 | 12 | 0 | 388 | 0.835 | 66/70 | 1 | 2 | 1 | 13 |
| 6 | 18 | 3 | 583 | 1.213 | 70/70 | 2 | 2 | 2 | 46 |
| 7 | 16 | 0 | 339 | 0.912 | 70/70 | 0 | 1 | 0 | 0 |
| 8 | 11 | 1 | 294 | 0.787 | 70/70 | 1 | 2 | 1 | 37 |
| 9 | 13 | 1 | 369 | 0.865 | 70/70 | 1 | 2 | 1 | 1 |

Moving vehicles: displaced > 5 m between the start of the minute and the next.

## Stability

- Memory (RSS MB / CUDA allocated MB) samples: 0.0s: 3357.9/42.6, 60.0s: 3363.0/42.6, 120.0s: 3363.6/42.6, 180.0s: 3364.5/42.6, 240.0s: 3365.8/42.6, 300.0s: 3366.2/42.6, 360.0s: 3366.6/42.6, 420.0s: 3367.5/42.6, 480.0s: 3368.8/42.6, 540.0s: 3369.2/42.6, 599.9s: 3370.1/42.6
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
