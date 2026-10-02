# CARLA E2E Environment

Status: **CARLA camera smoke PASS; Real YOLO smoke pending host execution**

Observed on 2026-10-03 (Asia/Seoul).

## Host

| Item | Observed value |
|---|---|
| OS | Ubuntu 22.04 host, Linux 6.8.0 x86_64 |
| GPU | NVIDIA GeForce RTX 3060, 8192 MiB |
| NVIDIA driver | 595.91.07 |
| Driver-reported maximum CUDA | 13.2 |
| System Python | 3.10.12 (not modified) |
| Validation Python | 3.7.17 in `.venv-carla-e2e` |
| CARLA server installation | `/home/jsy202/carla-0.9.13`, version 0.9.13 |
| CARLA Python client source | bundled `carla-0.9.13-cp37-cp37m-manylinux_2_27_x86_64.whl` |
| `client.get_client_version()` | 0.9.13 |
| `client.get_server_version()` | 0.9.13 |
| CARLA world | `Carla/Maps/Town10HD_Opt` |
| RGB camera smoke | PASS — 10 frames, 800×600, first-frame PNG saved |

No NVIDIA driver, CUDA toolkit, system Python package, or system-wide dependency was installed or changed.

## Intended pinned AI environment

| Package | Pin | Reason |
|---|---:|---|
| torch | 1.13.1+cu117 | final PyTorch line supporting Python 3.7; CUDA runtime is wheel-local |
| torchvision | 0.14.1+cu117 | official matching pair for torch 1.13.1 |
| ultralytics | 8.0.145 | Python 3.7-compatible YOLOv8 release; avoids forcing a current Python requirement |
| opencv-python | 4.8.1.78 | Python 3.7-compatible OpenCV wheel |
| numpy | 1.21.6 | final NumPy release supporting Python 3.7 |
| pytest | 7.4.4 | Python 3.7-compatible test runner |
| requests | 2.31.0 | Python 3.7-compatible HTTP dependency |

The exact requested packages are recorded in `requirements-py37.txt`. The CARLA wheel is installed separately from the local 0.9.13 distribution so it cannot resolve to the already present user-level CARLA 0.9.15 package.

## Installation result

The initial managed-environment installation could not reach either PyPI or the official PyTorch wheel index because DNS resolution was unavailable. The ignored `.venv-carla-e2e` directory was no longer present when work resumed after the host camera smoke, so no installed AI package version is inferred from that earlier attempt. `prepare_host_yolo_env.sh` recreates or reuses only that isolated path from a normal host terminal; it never deletes an existing environment and never installs system-wide packages. See `evidence/environment/dependency_install.log` for the earlier failed attempt.

Consequently these required fields are not measured:

| Field | Result |
|---|---|
| torch version | BLOCKED — package unavailable |
| torchvision version | BLOCKED — package unavailable |
| CUDA available | NOT MEASURED — torch unavailable |
| torch CUDA version | NOT MEASURED — torch unavailable |
| torch GPU name | NOT MEASURED — torch unavailable |
| ultralytics version | BLOCKED — package unavailable |
| OpenCV version | BLOCKED — package unavailable |
| YOLO weight filename | BLOCKED — original unavailable and download unavailable |
| Weight source | BLOCKED |
| Weight checksum | NOT MEASURED |

## Weight provenance search

The repository, `/home/jsy202`, pip cache, common model extensions (`*.pt`, `*.onnx`, `*.engine`), and likely Ultralytics cache locations were searched. No original research YOLO weight was found. Because network resolution failed, a new pretrained weight was not downloaded.

If network access is restored, this validation must use and disclose: **Post-project CARLA validation used a newly downloaded YOLOv8s pretrained weight because the original research weight was unavailable.** That future weight must remain uncommitted and its SHA-256 must be recorded before a measured run.

## Camera smoke gate

The server was started independently in the normal host environment with `-RenderOffScreen -quality-level=Low`. The host runner connected to `127.0.0.1:2000`, observed matching 0.9.13 client/server versions, queried `Town10HD_Opt`, spawned an RGB camera, received ten 800×600 frames, saved a PNG, and destroyed the sensor. The runner returned exit code 0. Raw evidence is under `evidence/host_smoke/`.

The camera portion of the gate is PASS. The overall Real YOLO gate remains pending until the host installs the pinned AI dependencies, records CUDA/GPU properties and weight checksum, and produces `evidence/yolo_smoke/result.json` with `status=PASS`. No CARLA E2E benchmark measurements have been collected.
