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

DEFAULT_CONFIG: dict[str, Any] = {
    "webcam": {
        "enabled": True,
        "sample_interval_seconds": 2,
        "looking_away_threshold_seconds": 9,
    },
    "distractions": {
        "continuous_threshold_seconds": 300,
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
        # Off by default since YouTube is often used for work.
        "youtube_is_distraction": False,
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
