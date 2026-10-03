"""Manifest serialization and Target/Non-target parity checks."""

from __future__ import annotations

import copy
import json
from pathlib import Path


def _probe(vehicles):
    probes = [vehicle for vehicle in vehicles if vehicle.get("kind") == "probe"]
    if len(probes) != 1:
        raise ValueError("manifest must contain exactly one planned probe")
    return probes[0]


def build_non_target_manifest(target_manifest, probe_color="255,0,0"):
    result = copy.deepcopy(target_manifest)
    if result.get("scenario") != "target":
        raise ValueError("non-target manifest must be derived from target manifest")
    result["scenario"] = "non_target"
    probe = _probe(result["planned_scene"]["vehicles"])
    probe["color"] = probe_color
    result["actual_spawned_scene"] = {"vehicles": []}
    return result


def _parity_projection(manifest):
    projected = copy.deepcopy(manifest)
    projected.pop("actual_spawned_scene", None)
    projected["scenario"] = "parity"
    probe = _probe(projected["planned_scene"]["vehicles"])
    probe["color"] = "<probe-colour>"
    return projected


def validate_manifest_parity(target_manifest, non_target_manifest):
    target_probe = _probe(target_manifest["planned_scene"]["vehicles"])
    non_target_probe = _probe(non_target_manifest["planned_scene"]["vehicles"])
    if target_manifest.get("scenario") != "target" or non_target_manifest.get("scenario") != "non_target":
        raise ValueError("manifest parity failed: scenario labels are invalid")
    if target_probe.get("color") == non_target_probe.get("color"):
        raise ValueError("manifest parity failed: probe colours must differ")
    if _parity_projection(target_manifest) != _parity_projection(non_target_manifest):
        raise ValueError("manifest parity failed: only probe colour may differ")
    return True


def write_manifest(path, manifest):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_manifest(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if "planned_scene" not in value or "actual_spawned_scene" not in value:
        raise ValueError("manifest requires planned_scene and actual_spawned_scene")
    return value
