"""One-time download/cache of mediapipe model weights (FaceLandmarker,
ObjectDetector).

This is the only network access FocusGuard ever makes, and it fetches
generic, non-personal model files (neural net weights, no user data)
from Google's public model CDN — never anything derived from a webcam
frame, which never leaves this machine. Each model is cached under
~/.focusguard/models/ after its first download; no further network
calls happen once a given file exists.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

from focusguard.config import FACE_LANDMARKER_MODEL_PATH, MODEL_DIR, OBJECT_DETECTOR_MODEL_PATH

FACE_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)
OBJECT_DETECTOR_URL = (
    "https://storage.googleapis.com/mediapipe-models/object_detector/"
    "efficientdet_lite0/float32/latest/efficientdet_lite0.tflite"
)
DOWNLOAD_TIMEOUT_SECONDS = 30


class ModelDownloadError(Exception):
    pass


def _ensure_model(url: str, target_path: Path) -> Path:
    if target_path.exists():
        return target_path

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(target_path.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            tmp_path.write_bytes(response.read())
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise ModelDownloadError(f"Could not download the model from {url}: {exc}") from exc

    tmp_path.rename(target_path)
    return target_path


def ensure_face_landmarker_model() -> Path:
    """Return the local FaceLandmarker model path, downloading on first use."""
    return _ensure_model(FACE_LANDMARKER_URL, FACE_LANDMARKER_MODEL_PATH)


def ensure_object_detector_model() -> Path:
    """Return the local ObjectDetector (EfficientDet-Lite0) model path,
    downloading on first use. Used for phone-in-frame detection."""
    return _ensure_model(OBJECT_DETECTOR_URL, OBJECT_DETECTOR_MODEL_PATH)
