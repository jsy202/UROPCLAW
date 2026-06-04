# Experiment B v2 limitations

- Same scope limits as Experiment B v1: one map, one camera pose, one traffic
  configuration (70 vehicles, seed 42, 9 blue); simulation only; VLM requests
  are counted triggers (no VLM is called); YOLOv8s is a newly obtained weight.
- Runs are not bit-identical: Run 1 diverges from Runs 2/3 at frame 1386
  (~138.6 s, Traffic Manager), Runs 2 and 3 differ in 26 frames from frame 5028.
  Before (v1) and After (v2) are different executions, so Before/After absolute
  counts are context; the per-run shadow branch comparison is the primary result.
- The shadow branches replicate the fixed production flow; equivalence with the
  production Pipeline is unit-tested on synthetic input, not on CARLA frames.
  Time-dependent windows use simulation time.
- Fragment continuity (same colour, <= 2.0 s, centre within one box diagonal)
  links immediate re-tracks but not all of them: when a vehicle passes behind the
  street banner and reappears more than one box length away, a new track is
  treated as a new target (residual leaks: 5/4/4 Full triggers per run). The
  threshold was not tuned to these runs. Conversely, two different same-colour
  vehicles within 2 s and one box length are merged (unit-tested limitation;
  observed 0 times here: no suppression was owned by a different actor).
- Without re-identification, the same vehicle returning after >= 30 s (TM loop
  traffic) is a new request (4/9/9 such Full triggers). Whether that is desired
  is a product decision.
- Ground-truth target colour comes from the assigned paint. For
  `vehicle.micro.microlino` the body renders blue regardless of the assigned
  colour, so a yellow-assigned Microlino is labelled non-target although it is
  visibly blue; all Full "non-target" triggers in v2 are this vehicle. The v1
  report's non-target counts include the same artefact (v1 files unchanged).
- Actor association and FOV entry use projected boxes and a centre ray; stage
  times are first occurrences and do not prove which pixels the detector used.
- Historical 46,372 / 28,736 / 3,298 / 53 values are not compared.
