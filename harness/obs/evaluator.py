import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
from collections import defaultdict
from pathlib import Path
from config import LOG_DIR


def evaluate(log_file: Path | None = None) -> dict:
    if log_file is None:
        files = sorted(LOG_DIR.glob("events_*.jsonl"))
        if not files:
            return {"error": "no log files found"}
        log_file = files[-1]

    events = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    ticks      = [e for e in events if e["type"] == "tick"]
    collisions = [e for e in events if e["type"] == "collision"]
    arrivals   = [e for e in events if e["type"] == "arrival"]
    overrides  = [t for t in ticks if t.get("policy") == "override"]

    speeds: dict[str, list[float]] = defaultdict(list)
    for t in ticks:
        speeds[t["agent"]].append(t["speed_kmh"])

    avg_speed = {
        aid: round(sum(v) / len(v), 2)
        for aid, v in speeds.items() if v
    }

    score = max(0, 100 - len(collisions) * 20 - len(overrides))

    return {
        "log_file":        str(log_file),
        "total_ticks":     len(ticks),
        "collisions":      len(collisions),
        "arrivals":        len(arrivals),
        "policy_overrides": len(overrides),
        "avg_speed_kmh":   avg_speed,
        "score":           score,
    }
