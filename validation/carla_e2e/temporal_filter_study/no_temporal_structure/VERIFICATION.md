# Follow-up verification

- Production no longer imports, allocates or invokes TemporalConfirm. Matched current HSV colour gates candidates immediately; unknown/unmatched observations are rejected. Existing tracking and target dedup remain.
- Single-target-observation test failed under the3-observation implementation and passed after removal. Gap/stale/current-crop/different-target/dedup regressions pass with synthetic detector and fake VLM.
- Six-configuration matrix covers all HSV/dedup presence pairs and early/late HSV tracking alternatives. Tests forbid Confirm.update for all six variants.
- All40 original archives reused via ignored local symlink workdirs. No new capture, no realVLM, original26-configuration analysis not overwritten.
- Four presence variants reproduce their corresponding historical factor000/factor001/factor100/N1 outcomes exactly (apart from config names and measured CPU timing), independently checked.
- Historical live host instrumentation depending on TemporalConfirm now rejects before simulator setup and points to789bec9. Benchmark aggregate-only mode remains available. Three failing→passing guard regressions cover these entrypoints.
- Fresh complete suite: **148 passed,1 historical skip,2 pre-existing warnings**,28.48s.
- Plot exporter and py_compile verified; git diff --check passed.
- Previous study's142-pass verification and unchanged-production statement describe the measurement-time baseline, not this subsequent removal.
