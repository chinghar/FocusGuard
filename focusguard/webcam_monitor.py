"""WebcamMonitor: samples the webcam at a low rate during Work Mode,
estimates head pose, and nudges the user after sustained off-track
posture — looking down or looking away, past a personal calibration
baseline.

Runs in its own background thread, started/stopped exactly at the
Work/Rest boundary, mirroring DistractionTracker and sharing the same
StreakAlerter so both signals nudge consistently. Camera lifecycle is
strict: the device is opened only inside the thread started by
start(), and release() always runs in a finally block — including if
calibration or a frame read raises — so "camera never active outside
Work Mode" holds on error paths too, not just the happy path. No frame
is ever retained past the single estimate() call that consumes it;
only the derived (pitch, yaw) numbers exist beyond that point.

`is_capturing` / `is_calibrating` are plain bools the menu bar polls
for the visible camera indicator (a trust requirement: the indicator
must reflect reality, never lag or fake a state). They're written only
from this monitor's own thread and read from the main thread; CPython
attribute reads/writes are atomic enough for this simple flag-polling
use, so no lock is needed for them.

A calibration pass runs automatically the first time this monitor
starts with no stored baseline; recalibrate() clears the baseline so
the next start() calibrates again (e.g. after moving the camera).

Unlike DistractionTracker's app/site signal (a clean, discrete "did the
frontmost app change" check), head pose is a noisy continuous
measurement — natural micro-movements near the pitch/yaw threshold
cause the classification to flicker back to "attentive" for a single
poll even mid-slouch. Resetting the whole streak on that one poll (as
StreakAlerter normally does on any non-flagged sample) would silently
multiply how long a real nudge takes to arrive. So only entering an
off-track streak is immediate; leaving one requires
`attentive_debounce_polls` consecutive confirmed-attentive polls first
— see _poll_once.

A phone visibly in the camera frame (PhoneDetector, object detection —
a different signal than head pose) is treated as off-track regardless
of what pitch/yaw says, and feeds the same streak/debounce rather than
a separate timer: seeing a phone is independent evidence of
distraction even if the head happens to be angled "attentively." It
runs on every frame regardless of whether a face was found, since a
phone held up close enough to occlude the face is exactly the case
where face detection alone would otherwise miss it.

Sustained absence — no face found, and no phone detected either — is
itself an off-track reason ("absent"), not silently ignored. A single
missed frame isn't (blinks, momentary tracking loss); it only becomes
an alert if it persists past the same sustained_threshold_seconds as
everything else.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, Callable

from focusguard.notify import send_alert, send_notification
from focusguard.streak import StreakAlerter
from focusguard.vision.camera import Camera
from focusguard.vision.classifier import Posture, PostureClassifier
from focusguard.vision.phone_detector import PhoneDetector
from focusguard.vision.pose import HeadPoseEstimator

# Set FOCUSGUARD_DEBUG=1 to log every poll's pitch/yaw/posture to stderr —
# same flag DistractionTracker uses, so one env var traces both signals.
_DEBUG_LOG = os.environ.get("FOCUSGUARD_DEBUG") == "1"


class WebcamMonitor:
    def __init__(
        self,
        config: dict[str, Any],
        on_distraction_event: Callable[[str | None, float], None] | None = None,
    ) -> None:
        self._config = config
        self._classifier = PostureClassifier(config)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._alerter = StreakAlerter(
            threshold_seconds=lambda: self._config["webcam"]["sustained_threshold_seconds"],
            repeat=lambda: self._config["webcam"]["repeat_notification"],
            on_alert=self._fire_notification,
            on_streak_end=on_distraction_event,
        )

        self.is_capturing = False
        self.is_calibrating = False
        # Consecutive attentive polls seen since the last off-track poll —
        # see attentive_debounce_polls in config.py for why this exists.
        self._consecutive_attentive = 0

    @property
    def enabled(self) -> bool:
        return self._config["webcam"]["enabled"]

    @property
    def sample_interval_seconds(self) -> float:
        return self._config["webcam"]["sample_interval_seconds"]

    def start(self) -> None:
        if not self.enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._alerter.reset()
        self._consecutive_attentive = 0
        self._thread = threading.Thread(target=self._run, daemon=True, name="WebcamMonitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)  # ensures no concurrent access before the flush below
        self._thread = None
        # _run's finally block already releases the camera and clears
        # these, but guarantee the indicator reflects "off" even if the
        # thread never got far enough to run that block.
        self.is_capturing = False
        self.is_calibrating = False
        # Flush any in-progress alerting streak as a completed distraction
        # event — otherwise off-track posture still active when Work Mode
        # ends would silently vanish from analytics instead of being logged.
        self._alerter.end_active_streak()

    def recalibrate(self) -> None:
        self._classifier.clear_baseline()

    def _run(self) -> None:
        camera = Camera(index=self._config["webcam"]["camera_index"])
        estimator = HeadPoseEstimator()
        phone_detector = (
            PhoneDetector(confidence_threshold=self._config["webcam"]["phone_detection_confidence_threshold"])
            if self._config["webcam"]["phone_detection_enabled"]
            else None
        )
        try:
            if not camera.open():
                return
            self.is_capturing = True

            if self._classifier.baseline is None:
                self._calibrate(camera, estimator)
                if self._stop_event.is_set():
                    return

            while not self._stop_event.is_set():
                try:
                    self._poll_once(camera, estimator, phone_detector)
                except Exception as exc:  # noqa: BLE001 - one bad poll must never silently kill the loop
                    print(f"FocusGuard: WebcamMonitor poll failed: {exc!r}", file=sys.stderr, flush=True)
                self._stop_event.wait(self.sample_interval_seconds)
        finally:
            estimator.close()
            if phone_detector is not None:
                phone_detector.close()
            camera.release()
            self.is_capturing = False
            self.is_calibrating = False

    def _calibrate(self, camera: Camera, estimator: HeadPoseEstimator) -> None:
        self.is_calibrating = True
        send_notification(
            title="FocusGuard",
            subtitle="Calibrating",
            message="Look at your screen normally for a few seconds...",
        )
        duration = self._config["webcam"]["calibration_duration_seconds"]
        deadline = time.monotonic() + duration
        pitches: list[float] = []
        yaws: list[float] = []
        while time.monotonic() < deadline and not self._stop_event.is_set():
            frame = camera.read()
            if frame is not None:
                sample = estimator.estimate(frame)
                if sample is not None:
                    pitches.append(sample.pitch)
                    yaws.append(sample.yaw)
            self._stop_event.wait(0.2)

        self.is_calibrating = False

        if pitches and yaws:
            self._classifier.set_baseline(
                pitch=sum(pitches) / len(pitches),
                yaw=sum(yaws) / len(yaws),
            )
            send_notification(title="FocusGuard", subtitle="Calibration complete", message="")
        else:
            # No face detected during calibration — baseline stays
            # unset. classify() defaults to attentive rather than guess,
            # and calibration retries next time Work Mode starts.
            send_notification(
                title="FocusGuard",
                subtitle="Calibration incomplete",
                message="Couldn't see your face — will retry next Work Mode session.",
            )

    def _poll_once(
        self, camera: Camera, estimator: HeadPoseEstimator, phone_detector: PhoneDetector | None
    ) -> None:
        frame = camera.read()
        if frame is None:
            if _DEBUG_LOG:
                print("FocusGuard: [webcam] frame read failed", file=sys.stderr, flush=True)
            return  # transient read failure — leave any active streak untouched

        # Phone detection runs on the raw frame regardless of whether a
        # face was found — it doesn't need one, and gating it behind face
        # detection was a real bug: a phone held up close enough to
        # occlude the face would fail face detection and then never even
        # get checked for a phone, silently doing nothing either way.
        phone_detected = phone_detector.detect(frame) if phone_detector is not None else False
        sample = estimator.estimate(frame)
        face_detected = sample is not None
        posture = self._classifier.classify(sample.pitch, sample.yaw) if face_detected else None

        # Priority: a visible phone is the most specific evidence of
        # distraction (wins even over an "attentive" pose reading). No
        # face at all — camera can't see you, whether you've stepped
        # away or something's blocking the view — is its own off-track
        # reason rather than silently doing nothing forever. Posture only
        # applies once a face was actually found.
        if phone_detected:
            label = "looking at your phone"
            is_off_track = True
        elif not face_detected:
            label = "absent"
            is_off_track = True
        elif posture is not Posture.ATTENTIVE:
            label = posture.value
            is_off_track = True
        else:
            label = None
            is_off_track = False

        if is_off_track:
            self._consecutive_attentive = 0
            self._alerter.update(True, label)
        else:
            self._consecutive_attentive += 1
            debounce = self._config["webcam"]["attentive_debounce_polls"]
            if self._consecutive_attentive >= debounce:
                # Confirmed attentive for long enough — the streak, if
                # any, is really over now.
                self._alerter.update(False, None)
            # else: a single (or still-insufficient) attentive reading —
            # likely noise near the threshold, not a real return to the
            # screen. Leave any in-progress streak untouched, same as an
            # unknown/unreadable poll would.

        if _DEBUG_LOG:
            if face_detected:
                baseline = self._classifier.baseline
                d_pitch = sample.pitch - baseline.pitch if baseline else None
                d_yaw = sample.yaw - baseline.yaw if baseline else None
                pose_str = (
                    f"pitch={sample.pitch:.1f} yaw={sample.yaw:.1f} "
                    f"(delta pitch={d_pitch and round(d_pitch, 1)} yaw={d_yaw and round(d_yaw, 1)}) "
                    f"posture={posture.value} "
                )
            else:
                pose_str = "face=none "
            print(
                f"FocusGuard: [webcam] {pose_str}phone={phone_detected} label={label} "
                f"consecutive_attentive={self._consecutive_attentive} "
                f"streak={self._alerter.streak_seconds:.1f}s",
                file=sys.stderr,
                flush=True,
            )

    def _fire_notification(self, label: str | None, elapsed_seconds: float) -> None:
        seconds = int(elapsed_seconds)
        description = label or "off-track"
        send_alert(title="Lock Back In!", message=f"You've been {description} for {seconds}+ sec.")
