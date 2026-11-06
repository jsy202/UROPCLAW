# Verification

Primary data:30complete600-second recordings at10Hz;180,000JSONL frames and180,000JPEG images.12development recordings and18held-out recordings, allTown10HD_Opt. The user reduced the planned40recordings during the30th capture. No31st capture or directory was started.

- `verify_archive.py --root validation/carla_e2e/progressive_filter_study --expected-recordings 30`:30archives verified;24,739,912,274image bytes. Every frame/index/sensor/time sequence and image reference was checked. Every JPEG was fingerprinted and its start/end markers checked; dimensions800×600 were decoded on samples every100images and the final image. Owned-actor cleanup succeeded for every recording.
- Image hashes are kept in each local `images.sha256`; image-set, frame JSONL, manifest and detector-weight hashes are in [archive_inventory.csv](results/archive_inventory.csv).
- Replay:28independent configurations,840per-recording rows,56aggregate rows. N1 and factor101 agree across all non-CPU summary metrics. Development selection was frozen asN1 before evaluating the18held-out recordings.
- Independent read-only review reproduced stage counts, unique actors, N1/N2/N3 comparisons, development choice, paired bootstrap intervals, miss diagnosis and boundary sensitivity. No material correctness issue remained.
- `.venv-carla-e2e/bin/python -m pytest -q`:152passed,1historical skip,2existing warnings. The skip is the retained pre-fixv1equivalence test; warnings come from invalid-input fake detector comparisons. New30-recording schedule regressions failed before the scope change and passed after it. Historical live-runner reference changes passed37targeted tests.
- Report generation completed successfully from the verified data. Stage plots and the three-weather scene collage were visually inspected. The first development archive was used for temporary report smoke checks; synthetic smoke outputs were deleted and never mixed into study results.
- ActualVLM and alerts were not called. One connectivity probe from before the earlier no-VLM instruction is excluded from all comparisons. Request metrics count triggers, not successfulVLM responses or final alerts.
- The capture supervisor was held before its next-job transition while the30th child finished. It was then interrupted for owned-server cleanup. Its intentional interrupt traceback is not a capture failure. All30manifests areCOMPLETE, and no ownedCARLA process remained after shutdown.
- Raw captures remain on the host under`runs/`; results, representative evidence and source are versioned. The earlier40×180-second archive remains separate. [Source scope and historical local checkpoints](SOURCE_PROVENANCE.md).

N3 provided measured request suppression but failed the prespecified episode-loss and confirmation-delay criteria. Reports retain both its benefits and losses, distinguish episodes from vehicles and unassociated requests from proven errors, and do not claim a universally optimal architecture.
