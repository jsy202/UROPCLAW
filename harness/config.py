import os
from pathlib import Path

# CARLA
CARLA_HOST = os.getenv("CARLA_HOST", "localhost")
CARLA_PORT = int(os.getenv("CARLA_PORT", "2000"))
CARLA_TM_PORT = int(os.getenv("CARLA_TM_PORT", "8000"))
CARLA_TIMEOUT = 10.0

# Paths
BASE_DIR = Path(__file__).parent
WORKSPACE_BASE = BASE_DIR.parent / "workspaces"
LOG_DIR = BASE_DIR.parent / "logs"

# Timing
CAPTURE_INTERVAL_S = float(os.getenv("CAPTURE_INTERVAL_S", "5.0"))
STATE_INTERVAL_S = float(os.getenv("STATE_INTERVAL_S", "1.0"))

# Agents
AGENT_IDS = ["uropclaw1", "uropclaw2", "uropclaw3", "uropclaw4"]
VEHICLE_BLUEPRINT = os.getenv("VEHICLE_BLUEPRINT", "vehicle.tesla.model3")

# Camera
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_FOV = 90

CAMERA_MOUNTS = {
    "front": {"x":  2.5, "y":  0.0, "z": 1.2, "pitch": -5.0, "yaw":   0.0, "roll": 0.0},
    "rear":  {"x": -2.5, "y":  0.0, "z": 1.2, "pitch": -5.0, "yaw": 180.0, "roll": 0.0},
    "left":  {"x":  0.0, "y": -1.0, "z": 1.5, "pitch":  0.0, "yaw": -90.0, "roll": 0.0},
    "right": {"x":  0.0, "y":  1.0, "z": 1.5, "pitch":  0.0, "yaw":  90.0, "roll": 0.0},
}

# Safety policy thresholds
POLICY_MIN_FRONT_DIST_M = 3.0
POLICY_MAX_SPEED_KMH = 80.0

# ── Surveillance mode settings ────────────────────────────────────────────────

# CARLA map to load
CARLA_MAP = os.getenv("CARLA_MAP", "Town05")

# NPC background vehicle count
BACKGROUND_VEHICLE_COUNT = int(os.getenv("BG_VEHICLE_COUNT", "20"))

# Target (colored) vehicle count
TARGET_VEHICLE_COUNT = int(os.getenv("TARGET_VEHICLE_COUNT", "2"))

# Random seed for reproducible spawning
RANDOM_SEED = int(os.getenv("RANDOM_SEED", "42"))

# Fixed CCTV camera positions (zone: 2, 3, 4)
# Keys correspond to Discord-bot agent IDs: cam_02 → uropclaw2, etc.
# Transform: (x, y, z) world position in metres; pitch/yaw in degrees (CARLA convention)
CCTV_CAMERAS: dict[str, dict[str, float]] = {
    "cam_02": {"x":  20.0, "y":  10.0, "z": 6.0, "pitch": -20.0, "yaw": 180.0},
    "cam_03": {"x": -20.0, "y":  10.0, "z": 6.0, "pitch": -20.0, "yaw":   0.0},
    "cam_04": {"x":   0.0, "y": -30.0, "z": 6.0, "pitch": -20.0, "yaw":  90.0},
}

# Mapping from human-readable color name to CARLA vehicle colour attribute string
COLOR_TO_CARLA_RGB: dict[str, str] = {
    "red":         "255,0,0",
    "blue":        "0,0,255",
    "green":       "0,255,0",
    "yellow":      "255,255,0",
    "white":       "255,255,255",
    "black":       "10,10,10",
    "gray_silver": "150,150,150",
    "orange":      "255,140,0",
}
