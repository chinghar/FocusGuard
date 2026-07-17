"""Head pose (pitch/yaw) estimation from a single BGR frame via
mediapipe's FaceLandmarker task.

Frames are never retained — callers pass a frame in, get a PoseSample
(or None if no face was found) back, and the frame is discarded
immediately after. Only two derived numbers (pitch, yaw) survive past
this call; no landmark coordinates or image data are kept.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python.core.base_options import BaseOptions
from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions, RunningMode

from focusguard.vision.model import ensure_face_landmarker_model


@dataclass
class PoseSample:
    pitch: float  # degrees, raw rotation-matrix decomposition
    yaw: float    # sign/offset handling lives in classifier.py, alongside calibration


class HeadPoseEstimator:
    def __init__(self) -> None:
        model_path = ensure_face_landmarker_model()
        options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=RunningMode.IMAGE,
            num_faces=1,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = FaceLandmarker.create_from_options(options)

    def estimate(self, frame_bgr: np.ndarray) -> PoseSample | None:
        """Return a pose estimate for `frame_bgr`, or None if no face is found."""
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect(mp_image)
        if not result.facial_transformation_matrixes:
            return None

        matrix = np.asarray(result.facial_transformation_matrixes[0])
        rotation = matrix[:3, :3]
        pitch, yaw, _roll = _rotation_matrix_to_euler(rotation)
        return PoseSample(pitch=pitch, yaw=yaw)

    def close(self) -> None:
        self._landmarker.close()


def _rotation_matrix_to_euler(rotation_matrix: np.ndarray) -> tuple[float, float, float]:
    """Extract pitch/yaw/roll (degrees) from a 3x3 rotation matrix.

    Standard X-Y-Z Tait-Bryan decomposition. No sign correction happens
    here — that lives entirely in vision/classifier.py alongside the
    calibration baseline, in one place, so behavior is easy to tune
    against what real hardware actually reports.
    """
    sy = (rotation_matrix[0, 0] ** 2 + rotation_matrix[1, 0] ** 2) ** 0.5
    singular = sy < 1e-6
    if not singular:
        x = np.arctan2(rotation_matrix[2, 1], rotation_matrix[2, 2])
        y = np.arctan2(-rotation_matrix[2, 0], sy)
        z = np.arctan2(rotation_matrix[1, 0], rotation_matrix[0, 0])
    else:
        x = np.arctan2(-rotation_matrix[1, 2], rotation_matrix[1, 1])
        y = np.arctan2(-rotation_matrix[2, 0], sy)
        z = 0.0
    return float(np.degrees(x)), float(np.degrees(y)), float(np.degrees(z))
