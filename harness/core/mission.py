from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from config import WORKSPACE_BASE

_MISSION_PATH = WORKSPACE_BASE / "uropclaw1" / "state" / "mission.json"


def read_mission() -> Optional[dict]:
    try:
        text = _MISSION_PATH.read_text(encoding="utf-8")
        return json.loads(text)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_mission(mission: dict) -> None:
    _MISSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MISSION_PATH.write_text(json.dumps(mission, ensure_ascii=False, indent=2), encoding="utf-8")


def is_active() -> bool:
    mission = read_mission()
    if mission is None:
        return False
    return bool(mission.get("active", False))


def get_target_color() -> Optional[str]:
    mission = read_mission()
    if mission is None:
        return None
    color = mission.get("target_color")
    if not color:
        return None
    return str(color)
