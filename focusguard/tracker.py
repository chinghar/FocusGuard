"""DistractionTracker: polls the frontmost app/site during Work Mode and
nudges the user back to work after sustained continuous distraction.

Runs in a background thread, started/stopped exactly at the Work/Rest
mode boundary (see FocusGuardApp / SessionManager). The continuous-time
counter resets the instant the frontmost app/site stops being a
distraction — a brief glance at a distracting tab can't accumulate
toward the threshold, and switching back to work always starts the
count over from zero.

A query that fails (AppleScript permission not granted yet, a momentary
osascript hiccup) or returns no URL at all (mid-navigation on a
JS-heavy site, a browser window with no tabs) is treated as "unknown",
not as "not a distraction" — an unknown poll leaves the current streak
untouched rather than resetting it on what might just be a transient
read.
"""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable

from focusguard.distraction_list import DistractionListManager
from focusguard.frontmost import (
    BROWSER_TAB_SCRIPTS,
    BrowserQueryError,
    get_active_browser_tab_url,
    get_frontmost_app_name,
)
from focusguard.notify import send_alert
from focusguard.streak import StreakAlerter

# Temporary diagnostic tracing while debugging a report of missed website
# distractions — set FOCUSGUARD_DEBUG=1 to log every poll's outcome to
# stderr. TODO: remove once the underlying issue is confirmed fixed.
_DEBUG_LOG = os.environ.get("FOCUSGUARD_DEBUG") == "1"


@dataclass
class _Observation:
    is_unknown: bool
    is_distraction: bool
    label: str | None  # app name or domain, for the notification text


class DistractionTracker:
    def __init__(
        self,
        distraction_list: DistractionListManager,
        config: dict[str, Any],
        on_distraction_event: Callable[[str | None, float], None] | None = None,
    ) -> None:
        self._distraction_list = distraction_list
        self._config = config
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._alerter = StreakAlerter(
            threshold_seconds=lambda: self._config["distractions"]["continuous_threshold_seconds"],
            repeat=lambda: self._config["distractions"]["repeat_notification"],
            on_alert=self._fire_notification,
            on_streak_end=on_distraction_event,
        )

    @property
    def poll_interval_seconds(self) -> float:
        return self._config["distractions"]["poll_interval_seconds"]

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._alerter.reset()
        self._thread = threading.Thread(target=self._run, daemon=True, name="DistractionTracker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)  # ensures no concurrent access before the flush below
        self._thread = None
        # Flush any in-progress alerting streak as a completed distraction
        # event — otherwise a distraction still active when Work Mode ends
        # would silently vanish from analytics instead of being logged.
        self._alerter.end_active_streak()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                observation = self._observe()
                self._update(observation)
                if _DEBUG_LOG:
                    print(
                        f"FocusGuard: [tracker] unknown={observation.is_unknown} "
                        f"distraction={observation.is_distraction} label={observation.label!r} "
                        f"streak={self._alerter.streak_seconds:.1f}s",
                        file=sys.stderr,
                        flush=True,
                    )
            except Exception as exc:  # noqa: BLE001 - one bad poll must never silently kill the loop
                print(f"FocusGuard: DistractionTracker poll failed: {exc!r}", file=sys.stderr, flush=True)
            self._stop_event.wait(self.poll_interval_seconds)

    def _observe(self) -> _Observation:
        app_name = get_frontmost_app_name()
        if app_name is None:
            return _Observation(is_unknown=True, is_distraction=False, label=None)

        if self._distraction_list.is_distraction_app(app_name):
            return _Observation(is_unknown=False, is_distraction=True, label=app_name)

        if app_name in BROWSER_TAB_SCRIPTS:
            try:
                url = get_active_browser_tab_url(app_name)
            except BrowserQueryError:
                return _Observation(is_unknown=True, is_distraction=False, label=None)
            if url is None:
                # osascript succeeded but returned no URL — happens
                # transiently mid-navigation on JS-heavy single-page sites
                # (e.g. Reddit's client-side routing), not just when a
                # browser genuinely has no tab open. Treat as unknown
                # rather than resetting an in-progress streak on what's
                # very likely just a momentary blank read between polls.
                return _Observation(is_unknown=True, is_distraction=False, label=None)
            if self._distraction_list.is_distraction_domain(url):
                return _Observation(is_unknown=False, is_distraction=True, label=url)
            return _Observation(is_unknown=False, is_distraction=False, label=None)

        return _Observation(is_unknown=False, is_distraction=False, label=None)

    def _update(self, observation: _Observation) -> None:
        if observation.is_unknown:
            return
        self._alerter.update(observation.is_distraction, observation.label)

    def _fire_notification(self, label: str | None, elapsed_seconds: float) -> None:
        minutes = int(elapsed_seconds // 60)
        target = label or "a distraction"
        send_alert(title="Lock Back In!", message=f"You've been on {target} for {minutes}+ min.")
