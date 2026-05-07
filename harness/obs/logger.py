import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import logging
from datetime import datetime, timezone
from config import LOG_DIR
from core.envelope import VehicleObservation, AgentDecision, PolicyDecision

log = logging.getLogger(__name__)


def _log_path():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"events_{datetime.now().strftime('%Y%m%d')}.jsonl"


def _write(entry: dict) -> None:
    with _log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_tick(
    agent_id: str,
    obs: VehicleObservation,
    decision: AgentDecision,
    policy: PolicyDecision,
) -> None:
    _write({
        "ts":         datetime.now(timezone.utc).isoformat(),
        "type":       "tick",
        "agent":      agent_id,
        "speed_kmh":  obs.speed_kmh,
        "front_dist": obs.front_vehicle_dist_m,
        "maneuver":   decision.maneuver,
        "target_spd": decision.target_speed_kmh,
        "policy":     policy.action,
        "policy_msg": policy.reason,
    })


def log_collision(agent_id: str, other_id: str | None = None) -> None:
    _write({
        "ts":    datetime.now(timezone.utc).isoformat(),
        "type":  "collision",
        "agent": agent_id,
        "other": other_id,
    })
    log.warning(f"[{agent_id}] COLLISION with {other_id}")


def log_arrival(agent_id: str, destination: str) -> None:
    _write({
        "ts":          datetime.now(timezone.utc).isoformat(),
        "type":        "arrival",
        "agent":       agent_id,
        "destination": destination,
    })
    log.info(f"[{agent_id}] ARRIVED at {destination}")
