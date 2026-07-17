"""Shared continuous-streak-until-threshold alerting state machine.

Used by both the distraction tracker (Phase 2) and the webcam monitor
(Phase 3) so "sustained flagged condition -> nudge, reset on any clear
sample" behaves identically everywhere — alerts feel consistent no
matter which signal triggered them, and there's exactly one place this
logic can have a bug.

Callers are responsible for deciding what counts as "flagged" for a
given sample and for skipping the update() call entirely on a sample
they can't classify (transient query failure, no face detected, etc.)
— an unclassifiable sample must never look like "the streak ended".

`on_streak_end` (Phase 4) reports a completed streak's final duration
for analytics logging — but only once it actually crossed the alert
threshold at least once. A streak that never got long enough to nudge
isn't a meaningful "distraction event"; logging every sub-threshold
flicker would make the analytics noisy without making them useful.
"""

from __future__ import annotations

import time
from typing import Callable


class StreakAlerter:
    def __init__(
        self,
        threshold_seconds: Callable[[], float],
        repeat: Callable[[], bool],
        on_alert: Callable[[str | None, float], None],
        on_streak_end: Callable[[str | None, float], None] | None = None,
    ) -> None:
        self._threshold_seconds = threshold_seconds
        self._repeat = repeat
        self._on_alert = on_alert
        self._on_streak_end = on_streak_end or (lambda label, elapsed: None)
        self._streak_start: float | None = None
        self._streak_label: str | None = None
        self._last_alerted_at: float | None = None

    @property
    def streak_seconds(self) -> float:
        if self._streak_start is None:
            return 0.0
        return time.monotonic() - self._streak_start

    def reset(self) -> None:
        """Clear any in-progress streak without reporting it as ended.

        For administrative resets (monitor start/stop) where the streak's
        outcome, if any, is handled separately by the caller — use
        end_active_streak() when a streak should be reported as finished.
        """
        self._streak_start = None
        self._streak_label = None
        self._last_alerted_at = None

    def end_active_streak(self) -> None:
        """End the in-progress streak, if any, reporting it via
        on_streak_end only if it crossed the alert threshold at least once.
        """
        if self._streak_start is not None and self._last_alerted_at is not None:
            elapsed = time.monotonic() - self._streak_start
            self._on_streak_end(self._streak_label, elapsed)
        self.reset()

    def update(self, is_flagged: bool, label: str | None) -> None:
        if not is_flagged:
            self.end_active_streak()
            return

        now = time.monotonic()
        if self._streak_start is None:
            self._streak_start = now
            self._streak_label = label
            self._last_alerted_at = None
            return

        self._streak_label = label or self._streak_label
        elapsed = now - self._streak_start
        threshold = self._threshold_seconds()
        if elapsed < threshold:
            return

        if self._last_alerted_at is None:
            self._on_alert(self._streak_label, elapsed)
            self._last_alerted_at = now
        elif self._repeat() and (now - self._last_alerted_at) >= threshold:
            self._on_alert(self._streak_label, elapsed)
            self._last_alerted_at = now
