#!/usr/bin/env python3
"""
YOLO + 색상 필터 디버그 스냅샷 도구.

실행 중인 CARLA에서 프레임을 캡처하여
- YOLO 바운딩박스 (클래스, 신뢰도)
- 색상 분류 결과 (중앙 60% 영역 기준)
를 시각화한 이미지를 저장합니다.

Usage:
    python3 debug_snap.py                   # 기본 (5프레임, uropclaw1~4 전체)
    python3 debug_snap.py --agent uropclaw3 --frames 3
    python3 debug_snap.py --out /tmp/debug
"""

import sys
import argparse
import logging
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import carla
from perception.yolo_detector import detect, Detection
from perception.color_filter import classify_color

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("debug_snap")

# 색상 → BGR (시각화용)
_COLOR_BGR = {
    "red":         (0, 0, 255),
    "blue":        (255, 100, 0),
    "green":       (0, 200, 0),
    "yellow":      (0, 220, 220),
    "white":       (220, 220, 220),
    "black":       (60, 60, 60),
    "gray_silver": (160, 160, 160),
    "orange":      (0, 140, 255),
    "unknown":     (180, 180, 180),
}

OBSERVER_SP = {
    "uropclaw1": 2,
    "uropclaw2": 13,
    "uropclaw3": 6,
    "uropclaw4": 7,
}


def _draw(frame: np.ndarray, detections: list[Detection], target_color: str) -> np.ndarray:
    vis = frame.copy()
    for det in detections:
        color_name = classify_color(frame, det.bbox)
        x1, y1, x2, y2 = det.bbox

        # bbox 색상: 목표 색상 일치 시 흰색 테두리 추가
        box_color = _COLOR_BGR.get(color_name, (180, 180, 180))
        thickness = 3 if color_name == target_color else 1
        cv2.rectangle(vis, (x1, y1), (x2, y2), box_color, thickness)

        # 중앙 60% 분석 영역 표시 (반투명 느낌)
        h, w = y2 - y1, x2 - x1
        ax1 = x1 + int(w * 0.10)
        ax2 = x2 - int(w * 0.10)
        ay1 = y1 + int(h * 0.20)
        ay2 = y2 - int(h * 0.20)
        cv2.rectangle(vis, (ax1, ay1), (ax2, ay2), box_color, 1)

        label = f"{det.class_name} {det.confidence:.2f} | {color_name}"
        (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        ty = max(y1 - 4, lh + 2)
        cv2.rectangle(vis, (x1, ty - lh - 2), (x1 + lw, ty + 2), box_color, -1)
        cv2.putText(vis, label, (x1, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)

    # 범례
    legend_y = 20
    for cname, bgr in _COLOR_BGR.items():
        cv2.rectangle(vis, (8, legend_y - 10), (22, legend_y + 2), bgr, -1)
        cv2.putText(vis, cname, (26, legend_y), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1)
        legend_y += 16

    return vis


def capture_and_annotate(agent_id: str, sp_index: int, n_frames: int,
                          out_dir: Path, target_color: str) -> None:
    client = carla.Client("localhost", 2000)
    client.set_timeout(10.0)
    world = client.get_world()

    bp_lib = world.get_blueprint_library()
    cam_bp = bp_lib.find("sensor.camera.rgb")
    cam_bp.set_attribute("image_size_x", "640")
    cam_bp.set_attribute("image_size_y", "360")
    cam_bp.set_attribute("fov", "90")
    cam_bp.set_attribute("sensor_tick", "0.2")  # 5 FPS

    # observer 차량 찾기 (스폰된 Tesla Model3)
    spawn_points = world.get_map().get_spawn_points()
    sp = spawn_points[sp_index]

    # 기존 차량 목록에서 가장 가까운 차량 사용 (재스폰 없이)
    vehicles = [a for a in world.get_actors() if "vehicle" in a.type_id]
    vehicle = min(vehicles, key=lambda v: v.get_location().distance(sp.location), default=None)

    if vehicle is None:
        log.error(f"[{agent_id}] 차량을 찾을 수 없습니다")
        return

    log.info(f"[{agent_id}] 가장 가까운 차량: {vehicle.type_id} "
             f"(거리 {vehicle.get_location().distance(sp.location):.1f}m)")

    transform = carla.Transform(
        carla.Location(x=2.5, y=0.0, z=1.2),
        carla.Rotation(pitch=-5.0, yaw=0.0),
    )
    sensor = world.spawn_actor(cam_bp, transform, attach_to=vehicle)

    collected: list[np.ndarray] = []

    def _on_image(img: carla.Image) -> None:
        if len(collected) < n_frames:
            raw = np.frombuffer(img.raw_data, dtype=np.uint8)
            rgba = raw.reshape((img.height, img.width, 4))
            bgr = rgba[:, :, :3][:, :, ::-1].copy()
            collected.append(bgr)

    sensor.listen(_on_image)
    log.info(f"[{agent_id}] {n_frames}프레임 수집 중...")

    deadline = time.time() + 15.0
    while len(collected) < n_frames and time.time() < deadline:
        time.sleep(0.1)

    sensor.stop()
    sensor.destroy()

    if not collected:
        log.error(f"[{agent_id}] 프레임 수집 실패")
        return

    log.info(f"[{agent_id}] {len(collected)}프레임 수집 완료, YOLO 실행 중...")

    for i, frame in enumerate(collected):
        detections = detect(frame)
        annotated = _draw(frame, detections, target_color)

        fname = out_dir / f"{agent_id}_frame{i:02d}.jpg"
        cv2.imwrite(str(fname), annotated)

        colors_found = [classify_color(frame, d.bbox) for d in detections]
        log.info(f"  frame{i:02d}: {len(detections)}개 탐지 "
                 f"→ 색상: {colors_found} → 저장: {fname}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="all",
                        help="uropclaw1~4 또는 all (기본: all)")
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument("--target-color", default="blue")
    parser.add_argument("--out", default="/tmp/uropclaw_debug")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    agents = OBSERVER_SP if args.agent == "all" else {args.agent: OBSERVER_SP[args.agent]}

    for agent_id, sp_idx in agents.items():
        capture_and_annotate(agent_id, sp_idx, args.frames, out_dir, args.target_color)

    log.info(f"\n완료! 저장 위치: {out_dir}")
    log.info(f"파일 목록:")
    for f in sorted(out_dir.glob("*.jpg")):
        log.info(f"  {f}")


if __name__ == "__main__":
    main()
