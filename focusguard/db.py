"""SQLite schema + queries for opt-in session/distraction analytics.

Nothing here is ever written unless AnalyticsRecorder.enabled is True
— see analytics.py, which is the single gate all logging passes
through. This module has no opinion on that; it just persists whatever
it's told to. Lives at ~/.focusguard/focusguard.db, alongside
config.json.

Each function opens its own short-lived connection rather than sharing
one across calls, since distraction events are logged from whichever
background thread (DistractionTracker or WebcamMonitor) detects them —
sqlite3 connections aren't safe to share across threads, but a fresh
connection per call, opened and closed within the calling thread, is.
"""

from __future__ import annotations

import csv
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from focusguard.config import CONFIG_DIR, DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL,
    end_time TEXT
);

CREATE TABLE IF NOT EXISTS distraction_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    event_end_time TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('webcam', 'app_site')),
    label TEXT,
    duration_seconds REAL NOT NULL
);
"""


@dataclass
class DistractionEvent:
    type: str
    label: str | None
    duration_seconds: float
    event_end_time: datetime


@contextmanager
def _connect():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_session(start_time: datetime) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO sessions (start_time, end_time) VALUES (?, NULL)",
            (start_time.isoformat(),),
        )
        return cursor.lastrowid


def close_session(session_id: int, end_time: datetime) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE sessions SET end_time = ? WHERE id = ?",
            (end_time.isoformat(), session_id),
        )


def insert_distraction_event(
    session_id: int,
    type_: str,
    label: str | None,
    duration_seconds: float,
    event_end_time: datetime,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO distraction_events "
            "(session_id, event_end_time, type, label, duration_seconds) VALUES (?, ?, ?, ?, ?)",
            (session_id, event_end_time.isoformat(), type_, label, duration_seconds),
        )


def fetch_events_for_session(session_id: int) -> list[DistractionEvent]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT type, label, duration_seconds, event_end_time "
            "FROM distraction_events WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    return [
        DistractionEvent(
            type=row[0],
            label=row[1],
            duration_seconds=row[2],
            event_end_time=datetime.fromisoformat(row[3]),
        )
        for row in rows
    ]


def fetch_all_sessions() -> list[tuple[int, datetime, datetime | None]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, start_time, end_time FROM sessions ORDER BY start_time"
        ).fetchall()
    return [
        (row[0], datetime.fromisoformat(row[1]), datetime.fromisoformat(row[2]) if row[2] else None)
        for row in rows
    ]


def export_csv(path: Path) -> None:
    """Write one row per (session, event) pair — sessions with no events
    still appear once, with blank event columns, via the LEFT JOIN."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT s.id, s.start_time, s.end_time, e.type, e.label, e.duration_seconds, e.event_end_time "
            "FROM sessions s LEFT JOIN distraction_events e ON e.session_id = s.id "
            "ORDER BY s.start_time, e.event_end_time"
        ).fetchall()

    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "session_id",
                "session_start",
                "session_end",
                "event_type",
                "event_label",
                "event_duration_seconds",
                "event_end_time",
            ]
        )
        writer.writerows(rows)
