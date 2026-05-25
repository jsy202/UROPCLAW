# Limitations

- No multi-vehicle result exists until the host smoke is executed and passes.
- The corridor is topology-derived at runtime; an unsuitable map topology or
  occupied spawn points causes a recorded FAIL rather than a reduced scene.
- Traffic Manager determinism can still be affected by uncontrolled actors
  already present in the host world. Their count is recorded and they are not
  deleted.
- CARLA 0.9.13 does not expose a Traffic Manager synchronous-mode getter used by
  this runner. The original TM mode therefore cannot be observed; cleanup sets
  TM synchronous mode to `False`, the standard CARLA validation shutdown
  pattern. World `synchronous_mode`, `fixed_delta_seconds`, and
  `no_rendering_mode` are independently restored to their captured primitive
  values even when the validation body raises.
- Probe FOV visibility and actor/track association use geometric projection and
  IoU for evaluation only; they are not a replacement for perception ground
  truth and never affect production decisions.
- The tracker diagnostics use projected actor boxes and can report ambiguous
  associations under occlusion.
- E2E event latency is not produced by this smoke runner. It remains a full
  benchmark metric after the smoke gate passes.
- The camera readiness gate permits up to ten setup ticks before the fixed
  fifty-tick pre-roll. Readiness ticks are recorded and excluded from pre-roll
  and measurement counters.
- Fake VLM and Fake Alert results do not measure Real VLM or real notification
  service behavior.
