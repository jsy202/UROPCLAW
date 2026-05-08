#!/usr/bin/env python3
"""
Town03_Opt surveillance scenario startup.

uropclaw2, uropclaw3, uropclaw4 each ride in a stationary observer vehicle.
Their vehicle's front camera feeds the YOLO pipeline.
When a target-colored vehicle is detected, each uropclaw reports on Discord.

Usage:
    python3 start.py
    python3 start.py --target-color red
    python3 start.py --target-color blue --bg-count 25 --patrol
"""

import sys
import signal
import logging
import argparse
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import carla

from sensors.camera import CameraManager
from core.pipeline import Pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("start")

# uropclaw1~4 observer 차량 배치 위치 (Town03_Opt 실측 spawn point 기반)
# 각 차량은 해당 위치에서 정차하며 전방 카메라로 감시
OBSERVER_SPAWNS = {
    "uropclaw1": {"sp_index":  2},   # x≈-74, y≈-50  — 서부 도로
    "uropclaw2": {"sp_index": 13},   # x≈97,  y≈63   — 중앙 교차로
    "uropclaw3": {"sp_index":  6},   # x≈16,  y≈-134 — 남부 직선도로
    "uropclaw4": {"sp_index":  7},   # x≈134, y≈-75  — 동남부 도로
}

COLOR_TO_CARLA_RGB = {
    "red":        "255,0,0",
    "blue":       "0,0,255",
    "green":      "0,200,0",
    "yellow":     "255,255,0",
    "white":      "255,255,255",
    "black":      "10,10,10",
    "gray_silver":"150,150,150",
    "orange":     "255,140,0",
}

CARLA_HOST = "localhost"
CARLA_PORT = 2000
CARLA_TM_PORT = 8000
RANDOM_SEED = 42

_pipeline: Pipeline | None = None
_all_actors: list[carla.Actor] = []
_camera: CameraManager | None = None
_world: carla.World | None = None


def _shutdown(sig, frame):
    log.info("Shutdown signal received — cleaning up")
    if _pipeline:
        _pipeline.stop()
    if _camera:
        _camera.destroy_all()
    for actor in _all_actors:
        try:
            if actor.is_alive:
                actor.destroy()
        except Exception:
            pass
    if _world:
        try:
            s = _world.get_settings()
            s.synchronous_mode = False
            _world.apply_settings(s)
        except Exception:
            pass
    sys.exit(0)


def spawn_observers(world, tm, spawn_points: list, patrol: bool) -> dict[str, carla.Actor]:
    """Spawn one observer vehicle per uropclaw2/3/4."""
    bp_lib = world.get_blueprint_library()
    # 눈에 띄지 않는 중형 차량 선택
    bp = bp_lib.filter("vehicle.tesla.model3")[0]

    observers: dict[str, carla.Actor] = {}
    for agent_id, cfg in OBSERVER_SPAWNS.items():
        sp = spawn_points[cfg["sp_index"]]
        vehicle = world.try_spawn_actor(bp, sp)
        if vehicle is None:
            # 해당 포인트 점유됐으면 근처 포인트 시도
            for alt_sp in spawn_points[cfg["sp_index"]+1: cfg["sp_index"]+10]:
                vehicle = world.try_spawn_actor(bp, alt_sp)
                if vehicle:
                    break
        if vehicle:
            if patrol:
                vehicle.set_autopilot(True, CARLA_TM_PORT)
                log.info(f"[{agent_id}] observer vehicle spawned (patrol mode)")
            else:
                vehicle.set_autopilot(False, CARLA_TM_PORT)
                log.info(f"[{agent_id}] observer vehicle spawned (stationary)")
            observers[agent_id] = vehicle
        else:
            log.error(f"[{agent_id}] failed to spawn observer vehicle")
    return observers


def spawn_background(world, tm, count: int, seed: int,
                     occupied_ids: set) -> list[carla.Actor]:
    """Spawn NPC background vehicles (skip observer-occupied spawn points)."""
    random.seed(seed)
    bp_lib = world.get_blueprint_library()
    vehicle_bps = [
        bp for bp in bp_lib.filter("vehicle.*")
        if bp.get_attribute("number_of_wheels").as_int() == 4
    ]
    spawn_points = world.get_map().get_spawn_points()
    random.shuffle(spawn_points)

    spawned = []
    for sp in spawn_points:
        if len(spawned) >= count:
            break
        bp = random.choice(vehicle_bps)
        actor = world.try_spawn_actor(bp, sp)
        if actor:
            actor.set_autopilot(True, CARLA_TM_PORT)
            spawned.append(actor)

    log.info(f"Background NPC vehicles: {len(spawned)}/{count}")
    return spawned


def spawn_target(world, tm, color: str, count: int, seed: int) -> list[carla.Actor]:
    """Spawn target-colored vehicles with autopilot near observer zones."""
    carla_rgb = COLOR_TO_CARLA_RGB.get(color)
    if not carla_rgb:
        log.warning(f"Unknown color '{color}'")
        return []

    bp_lib = world.get_blueprint_library()
    colorable = [
        bp for bp in bp_lib.filter("vehicle.*")
        if bp.has_attribute("color")
        and bp.get_attribute("number_of_wheels").as_int() == 4
    ]
    spawn_points = world.get_map().get_spawn_points()

    # observer 차량들 근처 스폰 포인트 우선 (시야에 들어오도록)
    observer_indices = {cfg["sp_index"] for cfg in OBSERVER_SPAWNS.values()}
    priority = [sp for i, sp in enumerate(spawn_points) if i in observer_indices]
    rest = [sp for i, sp in enumerate(spawn_points) if i not in observer_indices]
    random.seed(seed + 100)
    random.shuffle(rest)
    ordered = priority + rest

    spawned = []
    for sp in ordered:
        if len(spawned) >= count:
            break
        bp = random.choice(colorable)
        bp.set_attribute("color", carla_rgb)
        actor = world.try_spawn_actor(bp, sp)
        if actor:
            actor.set_autopilot(True, CARLA_TM_PORT)
            spawned.append(actor)
            log.info(f"Target vehicle spawned: {color}({carla_rgb}) "
                     f"at x={sp.location.x:.1f}, y={sp.location.y:.1f}")

    if len(spawned) < count:
        log.warning(f"Only spawned {len(spawned)}/{count} target vehicles")
    return spawned


def main():
    global _pipeline, _all_actors, _camera, _world

    parser = argparse.ArgumentParser(description="Town03 Surveillance Scenario")
    parser.add_argument("--target-color", type=str, default="blue",
                        help="Target vehicle color to spawn (default: blue)")
    parser.add_argument("--target-count", type=int, default=2,
                        help="Number of target vehicles (default: 2)")
    parser.add_argument("--bg-count", type=int, default=20,
                        help="Background NPC count (default: 20)")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument("--patrol", action="store_true",
                        help="Observer vehicles patrol (autopilot) instead of stationary")
    parser.add_argument("--baseline", choices=["A", "B", "C", "proposed"],
                        default="proposed")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # CARLA 연결 (Town03_Opt 이미 로드됨, 재로딩 없음)
    client = carla.Client(CARLA_HOST, CARLA_PORT)
    client.set_timeout(60.0)  # 메모리 부하 시 tick이 느릴 수 있으므로 여유있게
    world = client.get_world()
    _world = world
    log.info(f"Connected — map: {world.get_map().name}")

    # 동기화 모드 (10 FPS — CARLA 부하 완화)
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = 0.1  # 10 FPS (0.05=20FPS 대비 절반 부하)
    world.apply_settings(settings)

    tm = client.get_trafficmanager(CARLA_TM_PORT)
    tm.set_synchronous_mode(True)
    tm.set_random_device_seed(args.seed)

    spawn_points = world.get_map().get_spawn_points()

    # 1. Observer 차량 스폰 (uropclaw2~4 탑승 차량)
    observers = spawn_observers(world, tm, spawn_points, args.patrol)
    _all_actors.extend(observers.values())

    # 2. 배경 NPC 스폰
    occupied = set(OBSERVER_SPAWNS[k]["sp_index"] for k in observers)
    bg = spawn_background(world, tm, args.bg_count, args.seed, occupied)
    _all_actors.extend(bg)

    # 3. 목표 색상 차량 스폰
    targets = []
    if args.target_color:
        targets = spawn_target(world, tm, args.target_color, args.target_count, args.seed)
        _all_actors.extend(targets)

    # 4. 각 observer 차량에 카메라 부착 (front만 파이프라인에 사용)
    camera = CameraManager(world)
    _camera = camera
    for agent_id, vehicle in observers.items():
        camera.attach(agent_id, vehicle)

    # 5. 파이프라인 시작
    pipeline = Pipeline(world=world, baseline_mode=args.baseline)
    _pipeline = pipeline
    camera.set_frame_queue(pipeline.frame_queue)

    log.info("")
    log.info("=" * 55)
    log.info("  SURVEILLANCE SCENARIO READY")
    log.info("=" * 55)
    log.info(f"  Map        : {world.get_map().name}")
    log.info(f"  Mode       : {'patrol' if args.patrol else 'stationary'} observer")
    log.info(f"  BG traffic : {len(bg)} NPC vehicles")
    log.info(f"  Target     : {args.target_color} × {len(targets)} vehicle(s)")
    log.info(f"  Cameras    :")
    for agent_id in observers:
        sp_idx = OBSERVER_SPAWNS[agent_id]["sp_index"]
        sp = spawn_points[sp_idx]
        log.info(f"    {agent_id} — x={sp.location.x:.1f}, y={sp.location.y:.1f}")
    log.info("=" * 55)
    log.info("  Discord에서 아무 에이전트에게나 명령하세요:")
    log.info("  예) '@uropclaw2 파란 SUV 추적해줘'")
    log.info("  예) '@uropclaw3 빨간 세단 감시 시작'")
    log.info("=" * 55)

    pipeline.start()
    pipeline.join()


if __name__ == "__main__":
    main()
