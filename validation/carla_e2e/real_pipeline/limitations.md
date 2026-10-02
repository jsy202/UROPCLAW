# Limitations

- This is system-level validation with actual CARLA simulation RGB input and
  Real YOLO. It is not real-road or real-vehicle validation.
- The original research weight was unavailable. The ignored `yolov8s.pt` is a
  newly obtained post-project pretrained weight, so the conditions are not the
  same as the historical research run.
- The controlled target and non-target differ by CARLA vehicle colour while
  sharing one blueprint and fixed pose. This validates the existing colour
  path but does not estimate broad scene or perception accuracy.
- E2E latency samples cover decision-bearing temporal-confirmation frames.
  Frames without a terminal event decision remain in frame/detection/drop
  counts but not the latency distribution; therefore the one-second result
  must not be generalized to every camera frame.
- Frame-level HSV pass means a supported non-`unknown` colour, not equality to
  the active mission colour. The production pipeline does not discard
  `unknown` classifications before IoU tracking, so HSV-pass and tracking
  frames are observed stages rather than guaranteed mathematical subsets.
- Queue depth is sampled every 10 ms and may miss shorter transients. Ending
  depth and production drop counters are also recorded.
- Timeout injection raises the same `subprocess.TimeoutExpired` handled by the
  production worker after a configurable validation delay; it does not consume
  a real external service's full 25-second timeout.
- VLM failures currently exercise the production fail-open policy. A resulting
  alert is not evidence that the VLM correctly recognized a target.
- Fake VLM and Fake Alert remove external-service variability and do not
  measure Real VLM quality, latency, delivery, authentication, or cost.
- Historical YOLO 46,372 / HSV 28,736 / Tracking 3,298 / VLM 53 values have
  unverified unit equivalence and are not compared or used for a reduction
  percentage.
- The host runner connects to an externally managed CARLA process and does not
  restart or reconfigure it. Host load and server rendering conditions may
  affect latency.
