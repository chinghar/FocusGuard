"""SessionManager: single source of truth for whether monitoring is active.

Owns work-session start/stop timestamps and the monitor teardown
contract: any component that starts background work when a session
begins (webcam sampler, app/site tracker, ...) registers a stop
callback via `on_stop`. `stop_session` guarantees every registered
callback runs before the switch to Rest Mode is considered complete —
a monitor cannot be left running because one callback raised, and the
caller is told if any teardown failed so it can surface that instead
of silently trusting a broken stop.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable


@dataclass
class Session:
    start: datetime
    end: datetime | None = None


class SessionManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_session: Session | None = None
        self._stop_callbacks: list[Callable[[], None]] = []
        self.history: list[Session] = []

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._active_session is not None

    @property
    def current_session(self) -> Session | None:
        with self._lock:
            return self._active_session

    def on_stop(self, callback: Callable[[], None]) -> None:
        """Register a callback to run on every future stop_session call.

        Register once (e.g. at monitor construction), not per-session —
        the callback list persists across start/stop cycles.
        """
        with self._lock:
            self._stop_callbacks.append(callback)

    def start_session(self) -> Session:
        with self._lock:
            if self._active_session is not None:
                return self._active_session
            session = Session(start=datetime.now())
            self._active_session = session
            return session

    def stop_session(self) -> tuple[Session | None, list[Exception]]:
        """Stop the active session, running every registered teardown callback.

        Returns the closed session (or None if nothing was active) and
        any exceptions raised by teardown callbacks. Errors never abort
        the loop — every callback gets a chance to run — but they are
        surfaced to the caller rather than swallowed, since a failed
        teardown could mean a monitor is still capturing.
        """
        with self._lock:
            session = self._active_session
            if session is None:
                return None, []
            callbacks = list(self._stop_callbacks)
            self._active_session = None

        errors: list[Exception] = []
        for callback in callbacks:
            try:
                callback()
            except Exception as exc:  # noqa: BLE001 - one bad monitor must not block the rest
                print(f"FocusGuard: teardown callback failed: {exc!r}", file=sys.stderr)
                errors.append(exc)

        session.end = datetime.now()
        with self._lock:
            self.history.append(session)

        return session, errors
