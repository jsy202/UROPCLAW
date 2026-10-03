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
| No Dedup | 186 | +175 | 16.91x |

Stage contributions (ablation comparison on identical input, not a causal claim):

- HSV: removing it changes VLM triggers 11 -> 19 (+8; 1.73x).
- Temporal Confirmation: removing it changes VLM triggers 11 -> 11 (+0; 1.00x).
- Deduplication: removing it changes VLM triggers 11 -> 186 (+175; 16.91x).

Because dedup is a 30 s per-camera cooldown, any branch that keeps dedup is bounded by
roughly duration/30 s triggers; the dedup-free branch shows the candidate volume that
dedup absorbs. Candidate counts below show what HSV and Temporal remove before dedup.

## Per-branch metrics

| Metric | Unit | Full | No HSV | No Temporal | No Dedup |
|---|---|---:|---:|---:|---:|
| hsv_candidate_detections | detections | 357 | 4365 | 357 | 357 |
| frames_with_hsv_candidate | frames | 348 | 2822 | 348 | 348 |
| active_target_track_observations | track-frames | 357 | 4365 | 357 | 357 |
| frames_with_active_target_track | frames | 348 | 2822 | 348 | 348 |
| temporal_confirmations_passing_gate | events | 186 | 2448 | 357 | 186 |
| frames_triggering_confirmation | frames | 177 | 1542 | 348 | 177 |
| candidates_raised | candidates | 186 | 2448 | 357 | 186 |
| duplicate_suppressed | candidates | 175 | 2429 | 346 | 0 |
| vlm_triggers | requests | 11 | 19 | 11 | 186 |
| frames_with_vlm_trigger | frames | 11 | 19 | 11 | 177 |
| unique_tracks_triggering | tracks | 11 | 19 | 11 | 33 |
| unique_actors_triggering | actors | 6 | 5 | 8 | 10 |
| candidates_target_actor | candidates | 117 | 129 | 337 | 117 |
| candidates_non_target_actor | candidates | 5 | 1367 | 19 | 5 |
| candidates_unassociated | candidates | 64 | 952 | 1 | 64 |
| triggers_target_actor | requests | 9 | 0 | 10 | 117 |
| triggers_non_target_actor | requests | 0 | 6 | 1 | 5 |
| triggers_unassociated | requests | 2 | 13 | 0 | 64 |
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
| frames_with_yolo_vehicle_detection | 2822 | 0.4703 | 0.4703 |
| frames_with_target_hsv_candidate | 348 | 0.1233 | 0.058 |
| frames_with_active_target_track | 348 | 1 | 0.058 |
| frames_triggering_temporal_confirmation | 177 | 0.5086 | 0.0295 |
| frames_triggering_vlm | 11 | 0.0621 | 0.0018 |

## Traffic

| Item | Value |
|---|---:|
| simulation_duration_s | 600 |
| input_frames | 6000 |
| dropped_camera_frames | 0 |
| spawned_vehicles | 70 |
| spawned_target_color_vehicles | 9 |
| unique_vehicles_entering_fov | 68 |
| unique_vehicles_entering_fov_3plus_frames | 68 |
| target_color_vehicles_entering_fov | 9 |
| non_target_vehicles_entering_fov | 59 |
| unique_vehicles_matched_by_yolo | 68 |
| target_color_vehicles_matched_by_yolo | 9 |
| total_yolo_vehicle_detections | 4365 |
| frames_with_vehicle_detection | 2822 |
| frames_with_no_yolo_detection | 3178 |
| frames_with_no_visible_vehicle | 2304 |
| mean_detections_per_frame | 0.7275 |
| p95_detections_per_frame | 3 |
| max_detections_per_frame | 5 |
| yolo_latency_ms_mean | 14.476 |
| yolo_latency_ms_p95 | 15.604 |

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
| 0,200,0 | 9 | 9 |
| 255,255,0 | 8 | 8 |
| 255,140,0 | 9 | 8 |

Blueprints that entered the FOV: 31 distinct (vehicle.audi.a2 x2, vehicle.audi.etron x2, vehicle.audi.tt x2, vehicle.bmw.grandtourer x2, vehicle.carlamotors.carlacola x2, vehicle.carlamotors.firetruck x3, vehicle.chevrolet.impala x3, vehicle.citroen.c3 x2, vehicle.dodge.charger_2020 x2, vehicle.dodge.charger_police x2, vehicle.dodge.charger_police_2020 x3, vehicle.ford.ambulance x2, vehicle.ford.crown x3, vehicle.ford.mustang x2, vehicle.jeep.wrangler_rubicon x3, vehicle.lincoln.mkz_2017 x2, vehicle.lincoln.mkz_2020 x2, vehicle.mercedes.coupe x2, vehicle.mercedes.coupe_2020 x1, vehicle.mercedes.sprinter x2, vehicle.micro.microlino x2, vehicle.mini.cooper_s x2, vehicle.mini.cooper_s_2021 x2, vehicle.nissan.micra x2, vehicle.nissan.patrol x3, vehicle.nissan.patrol_2021 x2, vehicle.seat.leon x2, vehicle.tesla.model3 x3, vehicle.toyota.prius x2, vehicle.volkswagen.t2 x2, vehicle.volkswagen.t2_2021 x2).

## Per-minute summary

| Minute | Unique vehicles | Target vehicles | YOLO detections | Mean visible | Moving vehicles | Full | No HSV | No Temporal | No Dedup |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 22 | 1 | 555 | 1.332 | 70/70 | 1 | 2 | 1 | 20 |
| 1 | 14 | 4 | 271 | 0.773 | 70/70 | 2 | 2 | 2 | 32 |
| 2 | 22 | 2 | 620 | 1.453 | 70/70 | 1 | 2 | 1 | 17 |
| 3 | 17 | 3 | 511 | 1.178 | 70/70 | 1 | 2 | 1 | 31 |
| 4 | 13 | 1 | 314 | 0.805 | 70/70 | 1 | 2 | 1 | 6 |
| 5 | 14 | 0 | 419 | 1.002 | 70/70 | 1 | 2 | 1 | 18 |
| 6 | 15 | 1 | 497 | 1.053 | 70/70 | 1 | 2 | 1 | 17 |
| 7 | 17 | 2 | 468 | 1.105 | 70/70 | 1 | 1 | 1 | 20 |
| 8 | 9 | 1 | 249 | 0.615 | 67/70 | 1 | 2 | 1 | 13 |
| 9 | 15 | 1 | 461 | 1.018 | 70/70 | 1 | 2 | 1 | 12 |

Moving vehicles: displaced > 5 m between the start of the minute and the next.

## Stability

- Memory (RSS MB / CUDA allocated MB) samples: 0.0s: 3320.7/42.6, 60.0s: 3324.1/42.6, 120.0s: 3325.5/42.6, 180.0s: 3325.9/42.6, 240.0s: 3326.8/42.6, 300.0s: 3328.1/42.6, 360.0s: 3328.5/42.6, 420.0s: 3328.9/42.6, 480.0s: 3329.8/42.6, 540.0s: 3331.1/42.6, 599.9s: 3331.5/42.6
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
