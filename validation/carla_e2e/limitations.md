# CARLA E2E Validation Limitations

- The managed execution environment cannot access the host CARLA network/process namespace or GPU devices. Real CARLA/GPU commands must therefore be run manually in a normal host terminal.
- The host camera smoke measured matching CARLA 0.9.13 client/server versions, a world query, and ten RGB frames, but it did not exercise perception or the pipeline.
- The managed environment could not resolve PyPI or the official PyTorch wheel index. The isolated AI environment was therefore prepared in the normal host terminal; actual versions are recorded in `environment.md` and host evidence.
- The passed one-frame YOLO smoke returned zero boxes, but the later controlled positive gate detected the vehicle in 60/60 frames and verified the output contract.
- The observed 3,806.716 ms first-inference latency includes cold-start effects and is not used as representative latency. The separate 50-frame steady-state gate is retained as detector-only evidence and is not full E2E latency.
- The production Python 3.7 annotation-import defect was fixed minimally on the validation branch by postponing annotations in the files listed in `real_pipeline/defects.md` and importing `Literal` from `typing_extensions`. This change has not been merged to `main`.
- No perception, tracking, VLM, alert, queue, drop, E2E latency, or repeated scenario result has been measured.
- CUDA inference was demonstrated by the YOLO gates, but this does not establish perception accuracy.
- The one-second final-decision boundary was defined in the design but has zero samples; it is not evaluated.
- Real VLM execution has not been attempted. No credentials were added or changed.
- Existing synthetic validation results remain separate and are not used as substitutes or comparison baselines.
