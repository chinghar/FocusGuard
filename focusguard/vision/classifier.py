"""Posture classification against a personal calibration baseline.

Head geometry varies, and the pitch/yaw numbers out of pose.py aren't
absolute — a baseline captured while the user looks at their screen
normally cancels out camera angle, head shape, and any systematic bias
in the pose math itself. Calibration stores only two small floats
(pitch/yaw baseline degrees) in config.json — never any image or
landmark data.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from focusguard.config import save_config


class Posture(Enum):
    ATTENTIVE = "attentive"
    LOOKING_DOWN = "looking down"
    LOOKING_AWAY = "looking away"


@dataclass
class Baseline:
    pitch: float
    yaw: float


class PostureClassifier:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    @property
    def baseline(self) -> Baseline | None:
        cal = self._config["webcam"]["calibration"]
        if cal is None:
            return None
        return Baseline(pitch=cal["pitch"], yaw=cal["yaw"])

    def set_baseline(self, pitch: float, yaw: float) -> None:
        self._config["webcam"]["calibration"] = {"pitch": pitch, "yaw": yaw}
        save_config(self._config)

    def clear_baseline(self) -> None:
        self._config["webcam"]["calibration"] = None
        save_config(self._config)

    def classify(self, pitch: float, yaw: float) -> Posture:
        baseline = self.baseline
        if baseline is None:
            # Shouldn't happen once calibrated — never misclassify on a
            # missing baseline, since a false "off-track" here would be
            # an alert with no calibration behind it.
            return Posture.ATTENTIVE

        pitch_delta = pitch - baseline.pitch
        yaw_delta = yaw - baseline.yaw

        pitch_threshold = self._config["webcam"]["pitch_down_threshold_degrees"]
        yaw_threshold = self._config["webcam"]["yaw_away_threshold_degrees"]

        if pitch_delta >= pitch_threshold:
            return Posture.LOOKING_DOWN
        if abs(yaw_delta) >= yaw_threshold:
            return Posture.LOOKING_AWAY
        return Posture.ATTENTIVE
