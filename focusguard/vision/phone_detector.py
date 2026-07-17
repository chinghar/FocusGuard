"""Phone-in-frame detection via mediapipe's ObjectDetector task
(EfficientDet-Lite0, COCO classes) — a distinct signal from head pose:
a phone visibly in the camera frame is independent evidence of
distraction regardless of what the head-pose estimate says.

Same discipline as pose.py: a frame goes in, a bool comes out, and
nothing about the frame's contents is retained past this call.
"""

from __future__ import annotations

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.vision import ObjectDetector, ObjectDetectorOptions, RunningMode

from focusguard.vision.model import ensure_object_detector_model

_PHONE_CATEGORY = "cell phone"  # exact COCO label name used by this model


class PhoneDetector:
    def __init__(self, confidence_threshold: float = 0.5) -> None:
        model_path = ensure_object_detector_model()
        options = ObjectDetectorOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=RunningMode.IMAGE,
            max_results=5,
            score_threshold=confidence_threshold,
            category_allowlist=[_PHONE_CATEGORY],
        )
        self._detector = ObjectDetector.create_from_options(options)

    def detect(self, frame_bgr: np.ndarray) -> bool:
        """Return True if a phone is visible anywhere in `frame_bgr`."""
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._detector.detect(mp_image)
        return len(result.detections) > 0

    def close(self) -> None:
        self._detector.close()
