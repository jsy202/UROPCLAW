# CARLA E2E Validation Limitations

- The managed execution environment cannot access the host CARLA network/process namespace or GPU devices. Real CARLA/GPU commands must therefore be run manually in a normal host terminal.
- The host camera smoke measured matching CARLA 0.9.13 client/server versions, a world query, and ten RGB frames, but it did not exercise perception or the pipeline.
- The managed environment could not resolve PyPI or the official PyTorch wheel index. The isolated AI environment must be prepared from the host, and its actual installed versions remain unmeasured until that command completes.
- No perception, tracking, VLM, alert, queue, drop, E2E latency, or repeated scenario result has been measured.
- GPU identity and driver information from `nvidia-smi` do not demonstrate PyTorch CUDA inference.
- No inference result or AI accuracy statement can be made.
- The one-second final-decision boundary was defined in the design but has zero samples; it is not evaluated.
- Real VLM execution has not been attempted. No credentials were added or changed.
- Existing synthetic validation results remain separate and are not used as substitutes or comparison baselines.
