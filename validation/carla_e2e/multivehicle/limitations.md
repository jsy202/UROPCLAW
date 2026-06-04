# Limitations

## Scope

- Simulation only: CARLA 0.9.13 Town10HD_Opt at low render quality. Not
  real-road, real-camera, or real-vehicle validation.
- One deterministic scene (seed 42, one corridor, one camera pose, one probe
  blueprint `vehicle.tesla.model3`) replayed in every run. Repetitions measure
  run-to-run stability of the system on that scene, not generalisation across
  scenes, maps, weather, lighting, or camera poses.
- Fake VLM always confirms and Fake Alert always delivers. Neither the Real VLM
  nor a real notification service is measured. Target events therefore reflect
  the production path up to and including AlertPolicy with a deterministic
  VLM verdict.
- A newly obtained pretrained YOLOv8s weight is used (the original research
  weight is unavailable).

## Scene construction choices (validation-only, measured reasons in DEF-MV-03..09)

- The corridor is restricted to straight (<= 10 deg yaw spread), junction-free
  80 m road with verified line of sight. Curved roads, junction behaviour and
  probe interaction with cross-traffic are therefore not exercised by the probe
  (background vehicles still drive through junctions).
- The probe uses TM autopilot without `set_path` and with lane changes
  disabled; adherence is measured (max deviation reported per run) rather than
  enforced.
- The camera captures every 0.1 s synchronous tick (`sensor_tick=0.0`), i.e.
  10 Hz, instead of `sensor_tick=0.1`, which skipped synchronous ticks.
- Wall-clock latency is measured while CARLA is paused between synchronous
  ticks; it reflects pipeline processing time for a frame, not real-time
  streaming under a free-running simulator.

## Measurement

- Probe FOV visibility and actor/track association use geometric projection of
  CARLA bounding boxes and IoU, without occlusion. They are evidence only and
  never affect production decisions. Street furniture (banners, lamp posts)
  occludes part of the view, so projected visibility can precede actual
  visibility.
- Real YOLO false positives occur in this scene (e.g. a "truck" box over a
  street banner/lamp post in `evidence/smoke/max_detections_annotated.png`);
  they are counted in `yolo_detections` like any other box.
- Track fragmentation is real: in every benchmark run the probe appears as two
  production track IDs (9 and 12). Temporal confirmation keeps emitting for a
  confirmed track, so each Target run raises 15 blue candidates; the production
  deduplicator suppresses 14 and one reaches Fake VLM/AlertPolicy. Hence there
  is exactly one probe E2E alert sample per Target run (10 in total).
- All 10 repetitions per scenario produced identical perception counts; the
  repetitions show stability and latency variation on one deterministic scene,
  not independent accuracy samples.
- E2E samples end at the first temporal confirmation's colour rejection or at
  AlertPolicy allow; dedup-suppressed or AlertPolicy-rejected candidates have no
  terminal sample. Sample counts per subset are reported with every statistic.
- CARLA 0.9.13 has no TM synchronous-mode getter; cleanup sets TM synchronous
  mode to `False`. World settings are restored to their captured values.
- Historical 46,372 / 28,736 / 3,298 / 53 values are not compared with these
  measurements because their units are not established as identical.
