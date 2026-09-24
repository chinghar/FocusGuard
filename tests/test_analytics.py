"""Regression test for AnalyticsRecorder's session summary math.

Pure Python, no macOS/AppKit dependencies.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from focusguard import analytics, db


class ComputeSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2024, 1, 1, 9, 0, 0)
        self.end = self.start + timedelta(hours=1)

    def test_longest_streak_is_zero_with_no_distractions(self) -> None:
        summary = analytics._compute_summary(1, self.start, self.end, [])
        self.assertEqual(summary.longest_streak_seconds, 0.0)

    def test_longest_streak_is_the_longest_single_distraction(self) -> None:
        events = [
            db.DistractionEvent(
                type="app_site",
                label="reddit.com",
                duration_seconds=300,
                event_end_time=self.start + timedelta(minutes=10),
            ),
            db.DistractionEvent(
                type="webcam",
                label="looking down",
                duration_seconds=600,
                event_end_time=self.start + timedelta(minutes=40),
            ),
        ]
        summary = analytics._compute_summary(2, self.start, self.end, events)
        self.assertEqual(summary.longest_streak_seconds, 600.0)
        self.assertEqual(summary.total_off_task_seconds, 900.0)


if __name__ == "__main__":
    unittest.main()
