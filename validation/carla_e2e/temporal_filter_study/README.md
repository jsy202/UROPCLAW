# Temporal / filter structure study — 초기 3분 탐색

이 폴더는 10Hz · 실행당 180초/1,800장의 초기 자료다. 최종 비교는 [10분/6,000장 후속 실험](../progressive_filter_study/README.md)에서 별도로 수행한다. 두 자료를 섞어 집계하지 않는다.

- [결과와 해석](SUMMARY.ko.md)
- [문제·진단·해결 과정](RESEARCH_LOG.ko.md)
- [상세 결과표](REPORT.ko.md)
- [비교 그래프](results/window_tradeoff.png)
- [실제 촬영 장면](results/scene_comparison.jpg)
- [실패·성공 사례 이미지 목록](results/evidence/cases.csv)

40 completed recordings, 72,000 RGB frames.16 development /24 held-out recordings. Actual VLM execution is disabled by explicit user instruction; see execution_policy.json. At the time of the historical comparison, production was unchanged. A subsequent user decision removed temporal confirmation from production; the retained historical rule module still reproduces the original experiment.

From the repository root:

```bash
.venv-carla-e2e/bin/python validation/carla_e2e/temporal_filter_study/postprocess.py
```

The postprocessor reuses saved captures and runs only analysis, synthetic stress probes, evidence export, development label audit and report generation. It does not collect more videos or call an actual VLM.

Host archive locations:

- `runs/<condition>/images/000000.jpg` … `001799.jpg`: every RGB frame, JPEG quality85.
- `runs/<condition>/frames.jsonl`: detections/colors computed from original sensor input, GT projections and frame/simulation timing. JPEG evidence is not the pixel-exact detector input.
- `runs/<condition>/manifest.json`: map/weather/traffic/seed/environment/weight SHA256/cleanup.
- `runs/<condition>/analysis/`: independently replayed events and scores.
- `results/`: aggregate/per-recording/per-episode/stratified/paired-delay/CI tables and charts.
- `label_audit/`: development-only paint-label crop audit.
- `vlm_probe/`: one connectivity probe from before the no-VLM instruction, excluded from study results.
- `interrupted/`: next-job initialization stopped with0frames/0images at the collection limit, excluded.

Raw archives are preserved locally and excluded from git due to size. Portable reports, plots and source code are versioned. The old60-recording/full-VLM design is retained as superseded history in protocol.md; its top section defines the final authorized scope.

Current no-temporal presence/order comparisons:

```bash
.venv-carla-e2e/bin/python validation/carla_e2e/temporal_filter_study/compare_no_temporal.py
```

[6-configuration report](no_temporal_structure/REPORT.ko.md). This reuses the same40archives via local symlinks; original26-configuration outputs remain intact.
