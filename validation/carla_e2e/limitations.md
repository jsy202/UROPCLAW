# CARLA E2E Validation Limitations

- The managed execution environment cannot access the host CARLA network/process namespace or GPU devices. Real CARLA/GPU commands must therefore be run manually in a normal host terminal.
- The host camera smoke measured matching CARLA 0.9.13 client/server versions, a world query, and ten RGB frames, but it did not exercise perception or the pipeline.
- The managed environment could not resolve PyPI or the official PyTorch wheel index. The isolated AI environment was therefore prepared in the normal host terminal; actual versions are recorded in `environment.md` and host evidence.
- The passed one-frame YOLO smoke returned zero boxes. It proves CUDA execution and output-contract compatibility only; it does not prove positive vehicle detection.
- The observed 3,806.716 ms first-inference latency includes cold-start effects and is not used as representative latency. Warm-up-separated steady-state measurement is pending.
- The existing production pipeline does not currently import under Python 3.7: `harness/config.py` evaluates PEP 585 `dict[...]` annotations and raises `TypeError: 'type' object is not subscriptable`. A static scan found the same annotation pattern without postponed evaluation in eight additional harness modules. This does not block the isolated YOLO gate, but it must be addressed or explicitly isolated before full pipeline repetitions.
- No perception, tracking, VLM, alert, queue, drop, E2E latency, or repeated scenario result has been measured.
- GPU identity and driver information from `nvidia-smi` do not demonstrate PyTorch CUDA inference.
- No inference result or AI accuracy statement can be made.
- The one-second final-decision boundary was defined in the design but has zero samples; it is not evaluated.
- Real VLM execution has not been attempted. No credentials were added or changed.
- Existing synthetic validation results remain separate and are not used as substitutes or comparison baselines.
