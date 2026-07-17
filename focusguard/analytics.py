"""AnalyticsRecorder: the single gate opt-in session/distraction logging
passes through.

DistractionTracker and WebcamMonitor call log_event() unconditionally,
same as they always fire an alert unconditionally — they have no idea
whether analytics is on. Every method here checks `enabled` (read live
from config) before touching the database, so "no events are logged
unless I've turned this on" is enforced in exactly one place rather
than scattered across every signal source.

A session only exists in the database between start_session() and
end_session() — there's no "always-on" background logging of session
start/stop the way SessionManager keeps for its own in-memory
bookkeeping; those are unrelated (SessionManager's history is never
persisted and isn't gated by this opt-in at all).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from focusguard import db


@dataclass
class SessionSummary:
    session_id: int
    start: datetime
    end: datetime
    distraction_count: int
    total_off_task_seconds: float
    longest_streak_seconds: float


class AnalyticsRecorder:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._session_id: int | None = None
        self._session_start: datetime | None = None
        self.last_summary: SessionSummary | None = None

    @property
    def enabled(self) -> bool:
        return self._config["analytics"]["enabled"]

    def start_session(self) -> None:
        if not self.enabled or self._session_id is not None:
            return
        self._session_start = datetime.now()
        self._session_id = db.insert_session(self._session_start)

    def end_session(self) -> SessionSummary | None:
        if self._session_id is None:
            return None
        session_id = self._session_id
        start = self._session_start
        end = datetime.now()
        db.close_session(session_id, end)
        events = db.fetch_events_for_session(session_id)
        summary = _compute_summary(session_id, start, end, events)
        self._session_id = None
        self._session_start = None
        self.last_summary = summary
        return summary

    def log_event(self, event_type: str, label: str | None, duration_seconds: float) -> None:
        if self._session_id is None:
            return  # analytics disabled, or no session currently open
        db.insert_distraction_event(self._session_id, event_type, label, duration_seconds, datetime.now())


def _merge_intervals(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Union overlapping intervals so simultaneous webcam + app/site
    distractions (e.g. looking down at a phone while also idling on a
    social app) aren't double-counted toward total off-task time."""
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda iv: iv[0])
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _compute_summary(
    session_id: int, start: datetime, end: datetime, events: list[db.DistractionEvent]
) -> SessionSummary:
    intervals = []
    for event in events:
        event_start = event.event_end_time - timedelta(seconds=event.duration_seconds)
        clipped_start = max(event_start, start)
        clipped_end = min(event.event_end_time, end)
        if clipped_start < clipped_end:
            intervals.append((clipped_start, clipped_end))

    merged = _merge_intervals(intervals)
    total_off_task = sum((e - s).total_seconds() for s, e in merged)

    cursor = start
    longest_streak = 0.0
    for interval_start, interval_end in merged:
        longest_streak = max(longest_streak, (interval_start - cursor).total_seconds())
        cursor = interval_end
    longest_streak = max(longest_streak, (end - cursor).total_seconds())

    return SessionSummary(
        session_id=session_id,
        start=start,
        end=end,
        distraction_count=len(events),
        total_off_task_seconds=total_off_task,
        longest_streak_seconds=longest_streak,
    )
