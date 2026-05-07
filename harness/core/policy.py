import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import POLICY_MIN_FRONT_DIST_M, POLICY_MAX_SPEED_KMH
from core.envelope import AgentDecision, PolicyDecision, VehicleObservation


def check(decision: AgentDecision, obs: VehicleObservation) -> PolicyDecision:
    # 앞차 근접 + 가속 시도 → 강제 감속
    if (
        obs.front_vehicle_dist_m < POLICY_MIN_FRONT_DIST_M
        and decision.maneuver in ("accelerate", "keep_lane")
        and decision.target_speed_kmh > obs.speed_kmh
    ):
        return PolicyDecision(
            action="override",
            reason=f"front dist {obs.front_vehicle_dist_m:.1f}m < {POLICY_MIN_FRONT_DIST_M}m",
            override_decision=AgentDecision(
                maneuver="decelerate",
                target_speed_kmh=max(0.0, obs.speed_kmh - 10.0),
            ),
        )

    # 속도 한계 초과
    if decision.target_speed_kmh > POLICY_MAX_SPEED_KMH:
        return PolicyDecision(
            action="override",
            reason=f"target {decision.target_speed_kmh} > max {POLICY_MAX_SPEED_KMH}",
            override_decision=AgentDecision(
                maneuver=decision.maneuver,
                target_speed_kmh=POLICY_MAX_SPEED_KMH,
                message=decision.message,
            ),
        )

    # 차선 변경 불가
    if decision.maneuver == "change_left" and not obs.left_lane_available:
        return PolicyDecision(
            action="override",
            reason="left lane not available",
            override_decision=AgentDecision(
                maneuver="keep_lane",
                target_speed_kmh=decision.target_speed_kmh,
            ),
        )

    if decision.maneuver == "change_right" and not obs.right_lane_available:
        return PolicyDecision(
            action="override",
            reason="right lane not available",
            override_decision=AgentDecision(
                maneuver="keep_lane",
                target_speed_kmh=decision.target_speed_kmh,
            ),
        )

    return PolicyDecision(action="allow")
