#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/home/jsy202/validation-work/UROPCLAW-carla-e2e"
VENV_PATH="$REPO_ROOT/.venv-carla-e2e"
PYTHON37="/usr/bin/python3.7"
USER_PIP="/home/jsy202/.local/bin/pip"
CARLA_WHEEL="/home/jsy202/carla-0.9.13/PythonAPI/carla/dist/carla-0.9.13-cp37-cp37m-manylinux_2_27_x86_64.whl"
REQUIREMENTS="$REPO_ROOT/validation/carla_e2e/requirements-py37.txt"
WEIGHT_DIR="$REPO_ROOT/validation/carla_e2e/weights"
WEIGHT_PATH="$WEIGHT_DIR/yolov8s.pt"
EVIDENCE_DIR="$REPO_ROOT/validation/carla_e2e/evidence/yolo_smoke"
LOG_PATH="$EVIDENCE_DIR/environment_setup.log"

cd "$REPO_ROOT"

if [[ "$(git branch --show-current)" != "validation-carla-e2e" ]]; then
  echo "Refusing to run outside validation-carla-e2e" >&2
  exit 1
fi

for required_path in "$PYTHON37" "$USER_PIP" "$CARLA_WHEEL" "$REQUIREMENTS"; do
  if [[ ! -e "$required_path" ]]; then
    echo "Required path is missing: $required_path" >&2
    exit 1
  fi
done

mkdir -p "$EVIDENCE_DIR"
exec > >(tee "$LOG_PATH") 2>&1

echo "Started: $(date --iso-8601=seconds)"
echo "Repository: $REPO_ROOT"
echo "Branch: $(git branch --show-current)"

if [[ ! -x "$VENV_PATH/bin/python" ]]; then
  if [[ -e "$VENV_PATH" ]]; then
    echo "Refusing to overwrite incomplete existing path: $VENV_PATH" >&2
    exit 1
  fi
  "$PYTHON37" -m venv --without-pip "$VENV_PATH"
fi

"$USER_PIP" --python "$VENV_PATH/bin/python" install "pip==24.0"
"$VENV_PATH/bin/python" -m pip install --no-deps "$CARLA_WHEEL"
"$VENV_PATH/bin/python" -m pip install -r "$REQUIREMENTS"

mkdir -p "$WEIGHT_DIR"
if [[ ! -f "$WEIGHT_PATH" ]]; then
  (
    cd "$WEIGHT_DIR"
    "$VENV_PATH/bin/python" -c 'from ultralytics import YOLO; YOLO("yolov8s.pt")'
  )
fi

if [[ ! -f "$WEIGHT_PATH" ]]; then
  echo "Ultralytics did not produce expected weight: $WEIGHT_PATH" >&2
  exit 1
fi

"$VENV_PATH/bin/python" - <<'PY'
import cv2
import torch
import torchvision
import ultralytics

print("torch={}".format(torch.__version__))
print("torchvision={}".format(torchvision.__version__))
print("torch_cuda={}".format(torch.version.cuda))
print("cuda_available={}".format(torch.cuda.is_available()))
print("gpu_name={}".format(torch.cuda.get_device_name(0) if torch.cuda.is_available() else None))
print("ultralytics={}".format(ultralytics.__version__))
print("opencv={}".format(cv2.__version__))
PY

sha256sum "$WEIGHT_PATH"
echo "Weight source: Ultralytics pretrained YOLOv8s asset obtained after the original project"
echo "Post-project CARLA validation used a newly obtained pretrained YOLOv8s weight because the original research weight was unavailable."
echo "Finished: $(date --iso-8601=seconds)"
