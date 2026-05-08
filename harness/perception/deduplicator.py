from __future__ import annotations

import threading
from dataclasses import dataclass, field

_OPENCLAW_COOLDOWN = 5.0
_DISCORD_COOLDOWN = 120.0


@dataclass
class _Entry:
    last_verify: float = 0.0
    last_alert: float = 0.0


class Deduplicator:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def _get_or_create(self, key: str) -> _Entry:
        if key not in self._entries:
            self._entries[key] = _Entry()
        return self._entries[key]

    def should_verify(self, key: str, now: float) -> bool:
        with self._lock:
            entry = self._get_or_create(key)
            if now - entry.last_verify >= _OPENCLAW_COOLDOWN:
                entry.last_verify = now
                return True
            return False

    def should_alert(self, key: str, now: float) -> bool:
        with self._lock:
            entry = self._get_or_create(key)
            if now - entry.last_alert >= _DISCORD_COOLDOWN:
                entry.last_alert = now
                return True
            return False

    def cleanup(self, now: float, ttl: float = 600.0) -> None:
        with self._lock:
            stale = [
                k for k, e in self._entries.items()
                if (now - e.last_verify > ttl) and (now - e.last_alert > ttl)
            ]
            for k in stale:
                del self._entries[k]
