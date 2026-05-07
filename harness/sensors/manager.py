import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import random
import carla
import logging
from config import (
    CARLA_HOST, CARLA_PORT, CARLA_TM_PORT, CARLA_TIMEOUT,
    CARLA_MAP, BACKGROUND_VEHICLE_COUNT, TARGET_VEHICLE_COUNT,
    RANDOM_SEED, COLOR_TO_CARLA_RGB,
    VEHICLE_BLUEPRINT, AGENT_IDS,
)

log = logging.getLogger(__name__)


class CarlaManager:
    def __init__(self) -> None:
        self.client: carla.Client | None = None
        self.world: carla.World | None = None
        self.tm: carla.TrafficManager | None = None

        # Legacy: agent_id → vehicle (자율주행 모드 호환용)
        self.vehicles: dict[str, carla.Vehicle] = {}

        # Surveillance mode actor lists
        self._bg_vehicles: list[carla.Actor] = []
        self._target_vehicles: list[carla.Actor] = []

        # Union of all spawned actors (vehicles + legacy)
        self._all_actors: list[carla.Actor] = []

    # ── Connection ──────────────────────────────────────────────────────────

    def connect(self, map_name: str | None = None) -> None:
        """Connect to CARLA and optionally load a map.

        If *map_name* (or ``CARLA_MAP`` env var) differs from the currently
        loaded map, the new map is loaded before returning.  Synchronous mode
        (fixed 0.05 s step) is always enabled so that ``world.tick()`` from
        the pipeline controls simulation time.
        """
        self.client = carla.Client(CARLA_HOST, CARLA_PORT)
        self.client.set_timeout(CARLA_TIMEOUT)

        target_map = map_name or CARLA_MAP
        current_map = self.client.get_world().get_map().name

        # CARLA stores full asset paths such as /Game/Carla/Maps/Town05;
        # compare only the trailing segment.
        if not current_map.endswith(target_map):
            log.info(f"Loading map {target_map!r} (current: {current_map!r})")
            self.world = self.client.load_world(target_map)
        else:
            self.world = self.client.get_world()
            log.info(f"Map already loaded: {current_map!r}")

        # Enable synchronous mode
        settings = self.world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        self.world.apply_settings(settings)

        self.tm = self.client.get_trafficmanager(CARLA_TM_PORT)
        self.tm.set_synchronous_mode(True)
        self.tm.set_random_device_seed(RANDOM_SEED)

        log.info(
            f"CARLA connected — server {self.client.get_server_version()} "
            f"/ map {self.world.get_map().name}"
        )

    # ── Surveillance: NPC background vehicles ───────────────────────────────

    def spawn_background_vehicles(self, count: int | None = None) -> None:
        """Spawn *count* NPC 4-wheel vehicles with autopilot enabled.

        Uses ``BACKGROUND_VEHICLE_COUNT`` from config when *count* is ``None``.
        Skips spawn points that are already occupied (``try_spawn_actor``).
        """
        n = count if count is not None else BACKGROUND_VEHICLE_COUNT
        random.seed(RANDOM_SEED)

        bp_lib = self.world.get_blueprint_library()
        vehicle_bps = [
            bp for bp in bp_lib.filter("vehicle.*")
            if bp.get_attribute("number_of_wheels").as_int() == 4
        ]
        spawn_points = self.world.get_map().get_spawn_points()
        random.shuffle(spawn_points)

        spawned = 0
        for sp in spawn_points:
            if spawned >= n:
                break
            bp = random.choice(vehicle_bps)
            actor = self.world.try_spawn_actor(bp, sp)
            if actor is not None:
                actor.set_autopilot(True, CARLA_TM_PORT)
                self._bg_vehicles.append(actor)
                self._all_actors.append(actor)
                spawned += 1

        if spawned < n:
            log.warning(
                f"Only spawned {spawned}/{n} background vehicles "
                f"(not enough free spawn points)"
            )
        else:
            log.info(f"Spawned {spawned} background vehicles")

    # ── Surveillance: target-coloured vehicles ──────────────────────────────

    def spawn_target_vehicle(
        self,
        target_color: str,
        count: int | None = None,
    ) -> list[carla.Actor]:
        """Spawn *count* vehicles painted with *target_color* and autopilot on.

        *target_color* must be a key in ``COLOR_TO_CARLA_RGB`` (config).
        Returns the list of successfully spawned actors.
        """
        n = count if count is not None else TARGET_VEHICLE_COUNT
        carla_rgb = COLOR_TO_CARLA_RGB.get(target_color)
        if carla_rgb is None:
            log.warning(
                f"Unknown target color {target_color!r}. "
                f"Known colors: {list(COLOR_TO_CARLA_RGB.keys())}. "
                f"Falling back to blue (0,0,255)."
            )
            carla_rgb = "0,0,255"

        bp_lib = self.world.get_blueprint_library()
        colorable_bps = [
            bp for bp in bp_lib.filter("vehicle.*")
            if bp.has_attribute("color")
            and bp.get_attribute("number_of_wheels").as_int() == 4
        ]
        if not colorable_bps:
            log.error("No colorable 4-wheel vehicle blueprints found — skipping target spawn")
            return []

        spawn_points = self.world.get_map().get_spawn_points()
        # Use a different seed offset so target vehicles land at different spots
        # than background vehicles when both use the same base seed.
        random.seed(RANDOM_SEED + 100)
        random.shuffle(spawn_points)

        spawned: list[carla.Actor] = []
        for sp in spawn_points:
            if len(spawned) >= n:
                break
            bp = random.choice(colorable_bps)
            bp.set_attribute("color", carla_rgb)
            actor = self.world.try_spawn_actor(bp, sp)
            if actor is not None:
                actor.set_autopilot(True, CARLA_TM_PORT)
                self._target_vehicles.append(actor)
                self._all_actors.append(actor)
                spawned.append(actor)
                log.info(
                    f"Spawned target vehicle: color={target_color!r} "
                    f"rgb=({carla_rgb}) actor_id={actor.id}"
                )

        if len(spawned) < n:
            log.warning(f"Only spawned {len(spawned)}/{n} target vehicles")

        return spawned

    # ── Legacy: per-agent vehicle spawn (self-driving mode) ─────────────────

    def spawn_vehicles(self, spawn_indices: dict[str, int] | None = None) -> None:
        """Spawn one dedicated vehicle per agent ID (legacy self-driving mode).

        Uses ``VEHICLE_BLUEPRINT`` and ``AGENT_IDS`` from config.
        Populated actors are stored in ``self.vehicles`` and ``self._all_actors``.
        """
        bp_lib = self.world.get_blueprint_library()
        bp = bp_lib.filter(VEHICLE_BLUEPRINT)[0]
        spawn_points = self.world.get_map().get_spawn_points()

        for i, agent_id in enumerate(AGENT_IDS):
            idx = (spawn_indices or {}).get(agent_id, i)
            if idx >= len(spawn_points):
                log.warning(f"Spawn point {idx} unavailable for {agent_id}")
                continue
            vehicle = self.world.spawn_actor(bp, spawn_points[idx])
            vehicle.set_autopilot(False, CARLA_TM_PORT)
            self.vehicles[agent_id] = vehicle
            self._all_actors.append(vehicle)
            log.info(f"Spawned {agent_id} → actor {vehicle.id} at spawn {idx}")

    # ── Cleanup ─────────────────────────────────────────────────────────────

    def destroy_all(self) -> None:
        """Destroy every spawned actor and restore asynchronous simulation mode."""
        for actor in self._all_actors:
            try:
                if actor.is_alive:
                    actor.destroy()
            except Exception as e:
                log.warning(f"Failed to destroy actor {getattr(actor, 'id', '?')}: {e}")

        self._all_actors.clear()
        self._bg_vehicles.clear()
        self._target_vehicles.clear()
        self.vehicles.clear()

        # Restore async mode so the CARLA server is not left ticking only on
        # external tick() calls after the harness exits.
        if self.world is not None:
            try:
                settings = self.world.get_settings()
                settings.synchronous_mode = False
                self.world.apply_settings(settings)
            except Exception as e:
                log.warning(f"Could not restore async mode: {e}")

        log.info("All actors destroyed, async mode restored")
