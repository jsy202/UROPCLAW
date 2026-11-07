# Verification

초기 3분 탐색 실험 완료 시점의 검증 기록이다. 현재 상태와 최종 비교는 [후속 10분 실험](../progressive_filter_study/README.md)을 참조한다.

- `.venv-carla-e2e/bin/python -m pytest -q`: **142 passed,1 skipped,2 warnings** in27.36s. The skip is the historical pre-fix v1 equivalence test; warnings were already present in the baseline test suite.
- `.venv-carla-e2e/bin/python -m py_compile validation/carla_e2e/temporal_filter_study/*.py`: passed.
- `git diff --check`: passed.
- `verify_archive.py`:40 complete condition cells,72,000 JSONL frames,72,000 JPEGs,9,460,907,112image bytes. Validated frame/index/sensor/time continuity, image existence, JPEG markers, sampled dimensions, successful owned-actor cleanup. SHA256 recorded for every image in each local archive; set and metadata hashes in results/archive_inventory.csv.
- Independent read-only reviewer reproduced N1/N2/N3 aggregate counts, unique actors, development N2 selection and bootstrap intervals. Revalidated all40archives and inspected scene/missed-target images. No Important finding remained.
- All actual-VLM commands are excluded from postprocess.py and blocked by execution_policy.json. CLI denial was verified. There are no actual-VLM results in this comparison. One prior connectivity probe is excluded and separately preserved.
- CARLA server and capture supervisor stopped after40completed recordings. No ongoing capture or actualVLM process.
- Production files under harness/ are unchanged relative to the repository baseline. Temporal N3 remains the production default.
