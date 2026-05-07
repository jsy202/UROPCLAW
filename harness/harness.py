#!/usr/bin/env python3
"""CARLA-OpenClaw Harness — entry point"""

import sys
import json
import signal
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sensors.manager import CarlaManager
from sensors.camera import CameraManager
from core.pipeline import Pipeline
from core.session_store import init as db_init
from gateway.proxy import start as proxy_start
from obs.evaluator import evaluate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("harness.log"),
    ],
)
log = logging.getLogger("harness")

manager = CarlaManager()
camera: CameraManager | None = None
pipeline: Pipeline | None = None
_print_eval_report: bool = False


def _shutdown(sig, frame):
    log.info("Shutdown signal received")
    if pipeline:
        pipeline.stop()
        metrics_summary = pipeline.metrics_summary()
        print("\n=== Final Metrics ===")
        print(json.dumps(metrics_summary, indent=2, ensure_ascii=False))
    if camera:
        camera.destroy_all()
    manager.destroy_all()
    result = evaluate()
    print("\n=== Evaluation ===")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if _print_eval_report:
        from evaluation.metrics import REPORT_PATH
        print(f"\neval_report path: {REPORT_PATH}")
    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="CARLA-OpenClaw Harness")
    parser.add_argument("--spawn-indices", type=str, default=None,
                        help='JSON dict e.g. \'{"uropclaw1":0,"uropclaw2":1}\' (legacy self-driving mode)')
    parser.add_argument("--eval-only", action="store_true",
                        help="마지막 로그 평가 결과만 출력")
    parser.add_argument("--capture-only", action="store_true",
                        help="카메라 캡처만 실행 (제어 없음)")
    parser.add_argument("--proxy-port", type=int, default=19000,
                        help="CARLA Proxy API 포트 (기본 19000)")
    parser.add_argument("--baseline", choices=["A", "B", "C", "proposed"],
                        default="proposed",
                        help="Evaluation baseline mode (default: proposed)")
    parser.add_argument("--eval-report", action="store_true",
                        help="종료 시 eval_report.json 경로 출력")

    # ── Surveillance mode arguments ──────────────────────────────────────────
    parser.add_argument("--map", type=str, default=None,
                        help="CARLA map name (e.g. Town05). Overrides CARLA_MAP env var")
    parser.add_argument("--target-color", type=str, default=None,
                        help="Target vehicle color to spawn (e.g. blue, red)")
    parser.add_argument("--bg-count", type=int, default=None,
                        help="Background NPC vehicle count (default: 20)")
    parser.add_argument("--target-count", type=int, default=None,
                        help="Target vehicle count to spawn (default: 2)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility (default: 42)")

    args = parser.parse_args()

    if args.eval_only:
        print(json.dumps(evaluate(), indent=2, ensure_ascii=False))
        return

    global _print_eval_report
    _print_eval_report = args.eval_report

    db_init()
    log.info("Session DB initialized")

    proxy_start(port=args.proxy_port)
    log.info(f"CARLA Proxy API started on port {args.proxy_port}")

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        # ── 1. CARLA 연결 및 맵 로드 ──────────────────────────────────────────
        manager.connect(map_name=args.map)

        # ── 2. 배경 NPC 차량 스폰 ─────────────────────────────────────────────
        manager.spawn_background_vehicles(count=args.bg_count)

        # ── 3. 목표 색상 차량 스폰 (--target-color 지정 시) ───────────────────
        if args.target_color:
            manager.spawn_target_vehicle(
                target_color=args.target_color,
                count=args.target_count,
            )

        # ── 4. 고정 CCTV 카메라 부착 ──────────────────────────────────────────
        from config import CCTV_CAMERAS
        global camera
        camera = CameraManager(manager.world)
        for cam_id, loc in CCTV_CAMERAS.items():
            camera.attach_fixed(cam_id, loc)

        # ── 5. 파이프라인 초기화 ──────────────────────────────────────────────
        global pipeline
        pipeline = Pipeline(
            world=manager.world,
            manager=manager,
            camera=camera,
            baseline_mode=args.baseline,
        )
        camera.set_frame_queue(pipeline.frame_queue)

        if args.capture_only:
            log.info("Capture-only mode")
            import time
            while True:
                camera.tick()
                time.sleep(1.0)
        else:
            pipeline.start()
            pipeline.join()  # SIGINT/SIGTERM 올 때까지 대기

    except Exception as e:
        log.error(f"Harness error: {e}", exc_info=True)
        if camera:
            camera.destroy_all()
        manager.destroy_all()
        sys.exit(1)


if __name__ == "__main__":
    main()
