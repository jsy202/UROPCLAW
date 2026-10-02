# CARLA E2E Environment

Status: **BLOCKED during dependency installation**

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
| `client.get_client_version()` | 0.9.13 (local client object; server connection not established) |
| `client.get_server_version()` | NOT MEASURED — server did not remain running |

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

The isolated environment and local CARLA 0.9.13 client were created successfully. Ubuntu's Python 3.7 installation has no `ensurepip`, so the already installed user-level pip 24.0 was invoked with pip's `--python .venv-carla-e2e` targeting option; installation still went only into the isolated environment. Installation of PyTorch and the remaining AI dependencies could not reach either PyPI or the official PyTorch wheel index because DNS resolution is unavailable in the execution environment. See `evidence/environment/dependency_install.log`.

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

## Smoke gate

The CARLA executable was also probed with off-screen, low-quality rendering. Both attempts exited with status 1 before opening RPC port 2000 and produced no current CARLA log. The sandbox could query the GPU with `nvidia-smi`, but could not open the current X display; this does not prove that X access caused the off-screen failure. No server connection, world load, or camera callback was claimed.

The full smoke gate therefore failed before measurement for two independent reasons: unavailable AI packages/weight and a CARLA server process that did not remain running. No CARLA performance or E2E measurements were collected.
