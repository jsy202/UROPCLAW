# CARLA E2E Validation Limitations

- The execution environment could not resolve PyPI or the official PyTorch wheel index. Real YOLO dependencies and a weight were therefore unavailable.
- The CARLA 0.9.13 executable exited with status 1 under the managed execution sandbox, including off-screen mode. No current crash report identified the cause, and no system graphics change was attempted.
- `client.get_client_version()` was measured as 0.9.13, but `client.get_server_version()` was not measured because no connection was established.
- No world, RGB camera, perception, tracking, VLM, alert, queue, drop, latency, completion, or repeated scenario result was measured.
- GPU identity and driver information from `nvidia-smi` do not demonstrate PyTorch CUDA inference.
- No inference result or AI accuracy statement can be made.
- The one-second final-decision boundary was defined in the design but has zero samples; it is not evaluated.
- Real VLM execution was not attempted after the prerequisite smoke gate failed. No credentials were added or changed.
- Existing synthetic validation results remain separate and are not used as substitutes or comparison baselines.
