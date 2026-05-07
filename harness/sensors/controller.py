import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import carla
import logging
from config import POLICY_MAX_SPEED_KMH
from core.envelope import AgentDecision

log = logging.getLogger(__name__)

# 비례 제어 게인
KP = 1.0 / 30.0   # 30 km/h 오차 → 전체 출력


def apply(vehicle: carla.Vehicle, decision: AgentDecision, current_speed_kmh: float) -> None:
    ctrl = carla.VehicleControl()
    target = min(decision.target_speed_kmh, POLICY_MAX_SPEED_KMH)
    error  = target - current_speed_kmh

    if decision.maneuver == "stop":
        ctrl.throttle, ctrl.brake, ctrl.steer = 0.0, 1.0, 0.0
    elif error > 0:
        ctrl.throttle = min(error * KP, 1.0)
        ctrl.brake    = 0.0
    else:
        ctrl.throttle = 0.0
        ctrl.brake    = min(-error * KP, 1.0)

    # 차선 변경 조향
    if decision.maneuver == "change_left":
        ctrl.steer = -0.3
    elif decision.maneuver == "change_right":
        ctrl.steer = 0.3
    else:
        ctrl.steer = 0.0

    vehicle.apply_control(ctrl)
    log.debug(
        f"ctrl throttle={ctrl.throttle:.2f} brake={ctrl.brake:.2f} steer={ctrl.steer:.2f}"
    )
