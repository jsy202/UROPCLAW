# Experiment B limitations

- One map (Town10HD_Opt), one fixed camera pose (reused from Experiment A), one
  traffic configuration (70 TM vehicles, seed 42, 8-colour palette with 9 blue
  vehicles). Results do not generalise to other scenes, densities, weather,
  lighting or camera placements.
- Three full 10-minute runs were executed. They are not bit-identical: YOLO
  counts first differ at frame 33 (rendering/GPU inference) and Traffic
  Manager traffic diverges from about 138 s. Within a run all four branches
  share identical frames and detections; across runs, numbers vary
  (No Dedup 186-222 triggers). Three runs are not enough for confidence
  intervals.
- VLM requests are counted triggers. No VLM (real or fake) is called, so no VLM
  accuracy, latency or cost is measured, and AlertPolicy is not exercised.
- The shadow branches replicate the production YoloWorker + OpenClawWorker
  decision flow with production classes; equivalence with the threaded
  production Pipeline is unit-tested on synthetic input, not on CARLA frames.
  Temporal, dedup and tracker-reconnect windows run on simulation time, i.e.
  as a real-time 10 Hz camera would timestamp frames. Production's 2 s
  stale-frame drop (wall clock) is not applicable and not exercised.
- Ablation definitions are validation choices: No HSV skips colour
  classification and the target gate (constant label, so temporal voting runs
  on track persistence); No Temporal confirms every track observed in the
  current frame. Other definitions could give different numbers.
- Production dedup is a 30 s cooldown keyed by camera agent, not by vehicle.
  Branches with dedup are therefore capped near 20 triggers per 10 minutes, and
  distinct target vehicles arriving within 30 s of a trigger get no VLM request
  (Full reached 6/5/6 of 9 target vehicles).
- Observed production behaviour (unchanged): TemporalConfirm is updated for
  tracks not matched in the current frame, so stale tracks can produce
  candidates/triggers whose bbox crop shows no vehicle (Run 3: 88 of 215 Full
  candidates, 4 of 11 Full triggers).
- Ground truth (projection, centre-ray line of sight, IoU >= 0.30 association)
  is evidence only. `unassociated` includes stale-track crops, parked map props
  that are not CARLA actors, and YOLO false positives (e.g. the street banner);
  it is not a precise false-positive count.
- Scene artefacts: a street banner/lamp post occludes part of the view and
  caused at least one false-blue candidate on a yellow car.
- Frames are processed synchronously while CARLA is paused; wall-clock timing
  (about 46 ms/frame) is not real-time road latency. RSS grew about 12 MB over
  10 minutes with in-memory per-frame records; CUDA memory stayed flat.
- A newly obtained pretrained YOLOv8s weight is used (original research weight
  unavailable).
- Historical 46,372 / 28,736 / 3,298 / 53 values are not compared.
