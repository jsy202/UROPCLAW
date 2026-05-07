"""
SQLite 기반 세션 상태 관리
- 세션 생성·갱신·재개
- Checkpoint 저장·복원
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from config import BASE_DIR

DB_PATH = BASE_DIR / "harness_state.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init() -> None:
    with _lock, _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id   TEXT PRIMARY KEY,
            agent_id     TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'active',
            created_at   TEXT NOT NULL,
            last_active  TEXT NOT NULL,
            tick_count   INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS checkpoints (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   TEXT NOT NULL,
            tick         INTEGER NOT NULL,
            state_json   TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            UNIQUE(session_id, tick)
        );
        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   TEXT NOT NULL,
            tick         INTEGER NOT NULL,
            event_type   TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at   TEXT NOT NULL
        );
        """)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Session ───────────────────────────────────────────────

def create_session(session_id: str, agent_id: str) -> None:
    with _lock, _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO sessions VALUES (?,?,?,?,?,?)",
            (session_id, agent_id, "active", _now(), _now(), 0),
        )


def tick_session(session_id: str) -> int:
    """tick_count 증가 후 새 tick 번호 반환"""
    with _lock, _conn() as con:
        con.execute(
            "UPDATE sessions SET tick_count=tick_count+1, last_active=? WHERE session_id=?",
            (_now(), session_id),
        )
        row = con.execute(
            "SELECT tick_count FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        return row["tick_count"] if row else 0


def get_session(session_id: str) -> dict | None:
    with _lock, _conn() as con:
        row = con.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def resume_session(agent_id: str) -> dict | None:
    """마지막 active 세션 반환 (재시작 시 재개용)"""
    with _lock, _conn() as con:
        row = con.execute(
            "SELECT * FROM sessions WHERE agent_id=? AND status='active' ORDER BY last_active DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
        return dict(row) if row else None


def close_session(session_id: str) -> None:
    with _lock, _conn() as con:
        con.execute(
            "UPDATE sessions SET status='closed', last_active=? WHERE session_id=?",
            (_now(), session_id),
        )


# ── Checkpoint ────────────────────────────────────────────

def save_checkpoint(session_id: str, tick: int, state: dict) -> None:
    with _lock, _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO checkpoints VALUES (NULL,?,?,?,?)",
            (session_id, tick, json.dumps(state, ensure_ascii=False), _now()),
        )


def load_latest_checkpoint(session_id: str) -> dict | None:
    with _lock, _conn() as con:
        row = con.execute(
            "SELECT * FROM checkpoints WHERE session_id=? ORDER BY tick DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return {"tick": row["tick"], "state": json.loads(row["state_json"])}


# ── Event log (DB 버전) ───────────────────────────────────

def log_event(session_id: str, tick: int, event_type: str, payload: dict) -> None:
    with _lock, _conn() as con:
        con.execute(
            "INSERT INTO events VALUES (NULL,?,?,?,?,?)",
            (session_id, tick, event_type,
             json.dumps(payload, ensure_ascii=False), _now()),
        )
