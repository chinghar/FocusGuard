"""Webcam capture wrapper.

Frames are only ever read into a short-lived local variable by the
caller and passed straight to the pose estimator — nothing here writes
a frame to disk, buffers it, or exposes it beyond a single read() call.
The underlying device is opened only while a WebcamMonitor session is
running and must always be released via release(), including on error
paths — this is what keeps "camera never active outside Work Mode" true
in practice, not just in intent.
"""

from __future__ import annotations

import cv2
import numpy as np


class Camera:
    def __init__(self, index: int = 0) -> None:
        self._index = index
        self._capture: cv2.VideoCapture | None = None

    @property
    def is_open(self) -> bool:
        return self._capture is not None and self._capture.isOpened()

    def open(self) -> bool:
        if self.is_open:
            return True
        capture = cv2.VideoCapture(self._index)
        if not capture.isOpened():
            capture.release()
            return False
        self._capture = capture
        return True

    def read(self) -> np.ndarray | None:
        if not self.is_open:
            return None
        ok, frame = self._capture.read()
        return frame if ok else None

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = None
