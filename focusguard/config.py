"""Local JSON config: load/save + defaults.

Every threshold, path, and list here is meant to be user-editable at
runtime (via the menu-bar UI in a later phase) — nothing about a specific
user or machine is hardcoded into app logic. This module only knows
about ``Path.home()``, never a literal username.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".focusguard"
CONFIG_PATH = CONFIG_DIR / "config.json"
MODEL_DIR = CONFIG_DIR / "models"
FACE_LANDMARKER_MODEL_PATH = MODEL_DIR / "face_landmarker.task"
OBJECT_DETECTOR_MODEL_PATH = MODEL_DIR / "efficientdet_lite0.tflite"
DB_PATH = CONFIG_DIR / "focusguard.db"

DEFAULT_CONFIG: dict[str, Any] = {
    "webcam": {
        "enabled": True,
        # Index passed to cv2.VideoCapture — 0 is the default/built-in
        # camera. Change if a Mac has multiple cameras and the built-in
        # one isn't the one you want to use.
        "camera_index": 0,
        # ~1-2 fps is plenty for posture sampling and keeps CPU/battery low.
        "sample_interval_seconds": 1,
        # Continuous off-track posture required before nudging — covers
        # both looking-down and looking-away, so brief natural movements
        # (glancing at a notification, stretching) don't trigger anything.
        "sustained_threshold_seconds": 9,
        # Degrees of deviation from the calibrated baseline before a
        # sample counts as off-track. Advanced tuning — edit this file
        # directly; not exposed in the menu to keep it uncluttered.
        "pitch_down_threshold_degrees": 15,
        "yaw_away_threshold_degrees": 20,
        # Consecutive attentive polls required before an in-progress
        # off-track streak is considered actually over. Head pose near
        # the degree thresholds above is noisy — natural micro-movements
        # cause the classification to flicker back to "attentive" for a
        # single poll even mid-slouch. Without this debounce, one such
        # blip wipes the whole streak, silently multiplying how long it
        # really takes to get a nudge. Only the "returning to attentive"
        # direction is debounced — a single off-track poll still starts
        # the streak immediately, so responsiveness there is unaffected.
        "attentive_debounce_polls": 2,
        # A phone visibly in frame is an independent, more specific signal
        # than head pose — it's checked on the same captured frame and
        # feeds the same off-track streak (with its own alert wording),
        # not a separate threshold/timer.
        "phone_detection_enabled": True,
        "phone_detection_confidence_threshold": 0.5,
        "calibration_duration_seconds": 5,
        "repeat_notification": False,
        # Set by the calibration flow on first use: {"pitch": float, "yaw": float}.
        # Never contains image or landmark data, only two baseline angles.
        "calibration": None,
    },
    "distractions": {
        "poll_interval_seconds": 3,
        "continuous_threshold_seconds": 60,
        # Fire one nudge per continuous streak (quiet), or re-nudge every
        # continuous_threshold_seconds for as long as the streak continues.
        "repeat_notification": False,
        "apps": [
            "Instagram",
            "TikTok",
            "Snapchat",
        ],
        "domains": [
            "instagram.com",
            "twitter.com",
            "x.com",
            "tiktok.com",
            "reddit.com",
            "facebook.com",
            "snapchat.com",
        ],
        # YouTube is deliberately left out — often used for work. Add
        # "youtube.com" via the menu's "Add Website" to opt in.
    },
    "analytics": {
        "enabled": False,
    },
}


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _merge_defaults(loaded: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Fill in any keys missing from an older/partial config on disk."""
    merged = dict(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(defaults.get(key), dict):
            merged[key] = _merge_defaults(value, defaults[key])
        else:
            merged[key] = value
    return merged


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))

    with CONFIG_PATH.open("r") as f:
        loaded = json.load(f)
    return _merge_defaults(loaded, DEFAULT_CONFIG)


def save_config(config: dict[str, Any]) -> None:
    ensure_config_dir()
    with CONFIG_PATH.open("w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
