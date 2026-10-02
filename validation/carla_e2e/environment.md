# CARLA E2E Environment

Status: **CARLA camera and one-frame CUDA YOLO smoke PASS; positive/steady-state gate pending**

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
| One-frame CUDA YOLO smoke | PASS — 800×600 CARLA frame, CUDA device, detector contract; zero boxes |

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
| setuptools | 68.0.0 | provides `pkg_resources`, required by Ultralytics 8.0.145 at import time |

The exact requested packages are recorded in `requirements-py37.txt`. The CARLA wheel is installed separately from the local 0.9.13 distribution so it cannot resolve to the already present user-level CARLA 0.9.15 package.

## Installation result

The initial managed-environment installation could not reach either PyPI or the official PyTorch wheel index because DNS resolution was unavailable. The environment was subsequently prepared from a normal host terminal in `.venv-carla-e2e`; no system Python package, driver, or CUDA toolkit was changed. The setup log retains an intermediate `pkg_resources` import failure. Installing and pinning `setuptools==68.0.0` resolved that dependency before the successful one-frame smoke; the failure remains in evidence rather than being rewritten.

Actual host smoke environment:

| Field | Result |
|---|---|
| torch version | 1.13.1+cu117 |
| torchvision version | 0.14.1+cu117 |
| CUDA available | true |
| torch CUDA version | 11.7 |
| torch GPU name | NVIDIA GeForce RTX 3060 |
| ultralytics version | 8.0.145 |
| OpenCV version | 4.8.1 |
| NumPy version | 1.21.6 |
| YOLO weight filename | `yolov8s.pt` |
| Weight source | Ultralytics pretrained YOLOv8s asset obtained after the original project |
| Weight checksum | `268e5bb54c640c96c3510224833bc2eeacab4135c6deb41502156e39986b562d` |

## Weight provenance search

The repository, `/home/jsy202`, pip cache, common model extensions (`*.pt`, `*.onnx`, `*.engine`), and likely Ultralytics cache locations were searched. No original research YOLO weight was found. The host later obtained a new pretrained `yolov8s.pt`; it remains ignored by Git.

Required disclosure: **Post-project CARLA validation used a newly obtained pretrained YOLOv8s weight because the original research weight was unavailable.** This weight is not committed, and its SHA-256 is recorded above.

## Camera smoke gate

The server was started independently in the normal host environment with `-RenderOffScreen -quality-level=Low`. The host runner connected to `127.0.0.1:2000`, observed matching 0.9.13 client/server versions, queried `Town10HD_Opt`, spawned an RGB camera, received ten 800×600 frames, saved a PNG, and destroyed the sensor. The runner returned exit code 0. Raw evidence is under `evidence/host_smoke/`.

The camera portion and one-frame CUDA inference portion are PASS. The first inference took 3,806.716 ms and returned zero raw boxes; it is treated only as cold-start evidence and not as representative performance. The positive-detection and warm-up/steady-state gate remains pending. No CARLA E2E benchmark measurements have been collected.
