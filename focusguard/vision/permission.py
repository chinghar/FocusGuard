"""One-time camera permission request, triggered from the main thread.

macOS requires the *initial* camera authorization dialog to be
triggered from the main thread's run loop. WebcamMonitor's capture loop
runs on a background thread by design (so it never blocks the menu
bar) — attempting cv2.VideoCapture there before authorization is
decided fails outright rather than prompting (confirmed: OpenCV bails
with "can not spin main run loop from other thread" instead of showing
the dialog). This module resolves authorization separately, from the
main thread, before that background thread ever touches the camera.
Once the user has answered once, the decision is cached by macOS and
background-thread camera access works normally for the rest of the
process's lifetime.

No frame is captured and the camera is not opened by this call — it
only resolves the OS permission decision.
"""

from __future__ import annotations

import threading

import AVFoundation

_TIMEOUT_SECONDS = 120


def ensure_camera_authorized() -> bool:
    """Resolve camera authorization. Must be called from the main thread.

    Returns True if the camera is (or becomes, after the user responds
    to the prompt this may trigger) authorized, False otherwise.
    """
    status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
        AVFoundation.AVMediaTypeVideo
    )
    if status == AVFoundation.AVAuthorizationStatusAuthorized:
        return True
    if status != AVFoundation.AVAuthorizationStatusNotDetermined:
        return False  # previously denied/restricted — re-prompting won't help

    resolved = threading.Event()
    granted = False

    def _on_response(access_granted: bool) -> None:
        nonlocal granted
        granted = access_granted
        resolved.set()

    AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
        AVFoundation.AVMediaTypeVideo, _on_response
    )
    resolved.wait(timeout=_TIMEOUT_SECONDS)
    return granted
