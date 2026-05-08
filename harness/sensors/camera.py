import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import carla
import time
import logging
import numpy as np
from pathlib import Path
from datetime import datetime
from queue import Queue
from typing import Optional
from config import (
    WORKSPACE_BASE, CAMERA_WIDTH, CAMERA_HEIGHT,
    CAMERA_FOV, CAMERA_MOUNTS, CAPTURE_INTERVAL_S,
)

log = logging.getLogger(__name__)


def _capture_dir(agent_id: str, mount: str) -> Path:
    return WORKSPACE_BASE / agent_id / "captures" / mount


def _carla_image_to_ndarray(image: carla.Image) -> np.ndarray:
    raw = np.frombuffer(image.raw_data, dtype=np.uint8)
    rgba = raw.reshape((image.height, image.width, 4))
    return rgba[:, :, :3][:, :, ::-1].copy()  # RGBA → BGR


class CameraManager:
    def __init__(self, world: carla.World | None):
        self.world = world
        # camera_id → { mount → sensor }
        # For vehicle-mounted cameras: camera_id == agent_id, mount == e.g. "front"
        # For fixed CCTV cameras:      camera_id == e.g. "cam_02", mount == "fixed"
        self._sensors: dict[str, dict[str, carla.Sensor]] = {}
        # camera_id → { mount → latest carla.Image }
        self._frames: dict[str, dict[str, carla.Image]] = {}
        # camera_id → { mount → latest np.ndarray (BGR) }
        self._np_frames: dict[str, dict[str, np.ndarray]] = {}
        self._last_capture: dict[str, float] = {}
        # optional external queue for pipeline integration
        self._frame_queue: Optional[Queue] = None
        # all spawned sensor actors (for cleanup)
        self._actors_to_destroy: list[carla.Actor] = []

    def set_frame_queue(self, q: Queue) -> None:
        self._frame_queue = q

    def attach(self, agent_id: str, vehicle: carla.Vehicle) -> None:
        """Attach vehicle-mounted cameras to *vehicle* for *agent_id*."""
        bp_lib = self.world.get_blueprint_library()
        cam_bp = bp_lib.find("sensor.camera.rgb")
        cam_bp.set_attribute("image_size_x", str(CAMERA_WIDTH))
        cam_bp.set_attribute("image_size_y", str(CAMERA_HEIGHT))
        cam_bp.set_attribute("fov", str(CAMERA_FOV))

        self._sensors[agent_id] = {}
        self._frames[agent_id] = {}
        self._np_frames[agent_id] = {}
        self._last_capture[agent_id] = 0.0

        for mount, t in {k: v for k, v in CAMERA_MOUNTS.items() if k == "front"}.items():
            transform = carla.Transform(
                carla.Location(x=t["x"], y=t["y"], z=t["z"]),
                carla.Rotation(pitch=t["pitch"], yaw=t["yaw"], roll=t["roll"]),
            )
            sensor = self.world.spawn_actor(cam_bp, transform, attach_to=vehicle)
            sensor.listen(
                lambda img, aid=agent_id, m=mount: self._on_frame(aid, m, img)
            )
            self._sensors[agent_id][mount] = sensor
            self._actors_to_destroy.append(sensor)
            log.info(f"Camera [{mount}] attached to {agent_id}")

    def _on_frame(self, agent_id: str, mount: str, image: carla.Image) -> None:
        self._frames[agent_id][mount] = image
        arr = _carla_image_to_ndarray(image)
        self._np_frames[agent_id][mount] = arr

        if self._frame_queue is not None:
            camera_id = f"{agent_id}_{mount}"
            try:
                loc = image.transform.location
                rot = image.transform.rotation
                self._frame_queue.put_nowait({
                    "camera_id": camera_id,
                    "agent_id": agent_id,
                    "frame": arr,
                    "timestamp": time.time(),
                    "cam_location": {"x": loc.x, "y": loc.y, "z": loc.z},
                    "cam_rotation": {"pitch": rot.pitch, "yaw": rot.yaw, "roll": rot.roll},
                })
            except Exception:
                pass  # Drop if full

    def get_latest_frame(self, agent_id: str, mount: str = "front") -> Optional[np.ndarray]:
        return self._np_frames.get(agent_id, {}).get(mount)

    def tick(self) -> dict[str, str]:
        """Save PNG every CAPTURE_INTERVAL_S seconds. Returns {agent_id: front_capture_path}."""
        now = time.time()
        saved: dict[str, str] = {}

        for agent_id in self._sensors:
            if now - self._last_capture.get(agent_id, 0.0) < CAPTURE_INTERVAL_S:
                continue
            frames = self._frames.get(agent_id, {})
            if not frames:
                continue

            ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:19]
            for mount, image in frames.items():
                out_dir = _capture_dir(agent_id, mount)
                out_dir.mkdir(parents=True, exist_ok=True)
                path = out_dir / f"{ts}.png"
                image.save_to_disk(str(path))
                if mount == "front":
                    saved[agent_id] = str(path)

            self._last_capture[agent_id] = now
            log.debug(f"[{agent_id}] captured {ts}")

        return saved

    def attach_fixed(self, camera_id: str, location: dict[str, float]) -> None:
        """Spawn a fixed CCTV camera at an absolute world-space position.

        The sensor is *not* attached to any parent actor — it floats at the
        given world coordinates, simulating a pole-mounted CCTV unit.

        Args:
            camera_id: Logical identifier used as the camera key in all internal
                dicts and in frame-queue payloads (e.g. ``"cam_02"``).
            location: Dict with keys ``x``, ``y``, ``z`` (metres) and
                ``pitch``, ``yaw`` (degrees, CARLA convention).  ``roll`` is
                assumed 0 when absent.
        """
        if self.world is None:
            raise RuntimeError("CameraManager.world is not set — call after CarlaManager.connect()")

        bp_lib = self.world.get_blueprint_library()
        bp = bp_lib.find("sensor.camera.rgb")
        bp.set_attribute("image_size_x", str(CAMERA_WIDTH))
        bp.set_attribute("image_size_y", str(CAMERA_HEIGHT))
        bp.set_attribute("fov", str(CAMERA_FOV))
        bp.set_attribute("sensor_tick", "0.0667")  # ~15 fps

        transform = carla.Transform(
            carla.Location(
                x=location["x"],
                y=location["y"],
                z=location["z"],
            ),
            carla.Rotation(
                pitch=location["pitch"],
                yaw=location["yaw"],
                roll=location.get("roll", 0.0),
            ),
        )

        # No attach_to argument → sensor is anchored at the world transform
        sensor = self.world.spawn_actor(bp, transform)
        sensor.listen(lambda img, cid=camera_id: self._on_frame(cid, "fixed", img))

        self._sensors.setdefault(camera_id, {})["fixed"] = sensor
        self._frames.setdefault(camera_id, {})
        self._np_frames.setdefault(camera_id, {})
        self._last_capture.setdefault(camera_id, 0.0)
        self._actors_to_destroy.append(sensor)

        log.info(
            f"Fixed CCTV camera attached: {camera_id!r} at "
            f"({location['x']}, {location['y']}, {location['z']}) "
            f"pitch={location['pitch']} yaw={location['yaw']}"
        )

    def destroy_all(self) -> None:
        """Stop and destroy all sensor actors owned by this manager."""
        for actor in self._actors_to_destroy:
            try:
                if actor.is_alive:
                    actor.stop()
                    actor.destroy()
            except Exception as e:
                log.warning(f"Failed to destroy sensor actor {getattr(actor, 'id', '?')}: {e}")
        self._actors_to_destroy.clear()
        self._sensors.clear()
        log.info("All camera sensors destroyed")

    def detach_all(self, to_destroy: list[carla.Actor]) -> None:
        """Legacy helper: stop sensors and hand actors to an external destroy list.

        Prefer ``destroy_all()`` for new code.  This method is retained for
        backwards compatibility with callers that manage actor lifetimes
        externally.
        """
        for sensors in self._sensors.values():
            for sensor in sensors.values():
                try:
                    sensor.stop()
                    to_destroy.append(sensor)
                except Exception:
                    pass
        self._sensors.clear()
