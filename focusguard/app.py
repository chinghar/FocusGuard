"""Menu-bar UI: Work/Rest toggle backed by SessionManager, plus the
distraction-list/webcam settings and the live capture indicator.

SessionManager is the single source of truth for whether monitoring
should be active — the menu-bar UI reads and drives it but never keeps
an independent mode flag of its own, so the displayed state and the
actual active-state can't silently drift apart. Starts in Rest Mode on
every launch: monitoring never resumes just because the app was quit
while in Work Mode last time.

DistractionTracker and WebcamMonitor are each registered with
SessionManager exactly once, at construction — the same instances are
started/stopped on every subsequent Work/Rest transition.

The menu bar title is never set ad hoc from inside a mode-transition
method — `_update_indicator` is the single place that derives it from
current state (mode + calibrating + capturing), called immediately
after any transition and every second via a timer, so the icon can't
drift from what's actually happening to the camera. It's polled from
the main thread rather than pushed from WebcamMonitor's background
thread, avoiding any cross-thread AppKit UI call.

The status item has no native NSMenu — clicking it shows a custom
NSPopover (focusguard/popover.py) instead, wired up in
_setup_status_item_interaction via rumps.events.before_start (the
public rumps hook that fires right after the status item exists but
before the run loop starts). Right-click still shows a minimal native
Quit-only menu, built inside popover.py.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import rumps
from AppKit import NSEventMaskLeftMouseUp, NSEventMaskRightMouseUp

from focusguard import db
from focusguard.analytics import AnalyticsRecorder, SessionSummary
from focusguard.config import load_config, save_config
from focusguard.distraction_list import DistractionListManager
from focusguard.popover import build_popover_controller
from focusguard.session import SessionManager
from focusguard.tracker import DistractionTracker
from focusguard.vision.permission import ensure_camera_authorized
from focusguard.webcam_monitor import WebcamMonitor

TITLE_REST = "⚪️ FocusGuard"
TITLE_WORK = "🟢 FocusGuard"
TITLE_WORK_CALIBRATING = "🟡📷 FocusGuard"
TITLE_WORK_CAPTURING = "🔴📷 FocusGuard"


class FocusGuardApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(name="FocusGuard", title=TITLE_REST, quit_button="Quit FocusGuard")
        self.config = load_config()
        self.session_manager = SessionManager()
        self.analytics = AnalyticsRecorder(self.config)
        self.distraction_list = DistractionListManager(self.config)
        self.tracker = DistractionTracker(
            self.distraction_list,
            self.config,
            on_distraction_event=lambda label, elapsed: self.analytics.log_event(
                "app_site", label, elapsed
            ),
        )
        self.webcam_monitor = WebcamMonitor(
            self.config,
            on_distraction_event=lambda label, elapsed: self.analytics.log_event(
                "webcam", label, elapsed
            ),
        )
        self.session_manager.on_stop(self.tracker.stop)
        self.session_manager.on_stop(self.webcam_monitor.stop)

        self.popover_controller = build_popover_controller(self)
        rumps.events.before_start.register(self._setup_status_item_interaction)

        self.indicator_timer = rumps.Timer(self._update_indicator, 1)
        self.indicator_timer.start()

    def _setup_status_item_interaction(self) -> None:
        """Fires via rumps.events.before_start — after rumps has created
        the status item (so self._nsapp.nsstatusitem exists) but before
        the run loop starts. Detaches the native menu and routes clicks
        to the popover controller instead; see focusguard/popover.py."""
        try:
            status_item = self._nsapp.nsstatusitem
            status_item.setMenu_(None)
            button = status_item.button()
            button.setTarget_(self.popover_controller)
            button.setAction_("statusItemClicked:")
            button.sendActionOn_(NSEventMaskLeftMouseUp | NSEventMaskRightMouseUp)
        except Exception as exc:  # noqa: BLE001 - a wiring failure shouldn't crash startup
            print(f"FocusGuard: popover wiring failed: {exc!r}", file=sys.stderr, flush=True)

    # -- mode switching -----------------------------------------------

    def toggle_mode(self, sender=None) -> None:
        if self.session_manager.is_active:
            self._enter_rest_mode()
        else:
            self._enter_work_mode()
        self._update_indicator(None)

    def _enter_work_mode(self) -> None:
        self.session_manager.start_session()
        self.analytics.start_session()
        self.tracker.start()
        if self.webcam_monitor.enabled and not ensure_camera_authorized():
            # Camera permission not granted — webcam detection sits this
            # session out rather than silently retrying in the background.
            rumps.alert(
                title="Camera Access Needed",
                message=(
                    "FocusGuard doesn't have camera permission, so webcam "
                    "attention detection is off for this session. Grant "
                    "access in System Settings → Privacy & Security → "
                    "Camera, then toggle Work Mode again."
                ),
            )
        else:
            self.webcam_monitor.start()

    def _enter_rest_mode(self) -> None:
        # stop_session() joins the tracker/webcam threads before returning,
        # which flushes any still-active alerting streak as a completed
        # distraction event — so end_session() below sees the full picture,
        # not a session missing whatever was happening right as it ended.
        _session, errors = self.session_manager.stop_session()
        summary = self.analytics.end_session()
        if summary is not None:
            self._show_session_summary(summary, via_notification=True)
        if errors:
            # A monitor's teardown failed — surface it rather than
            # silently trusting that tracking (or the camera) actually
            # stopped.
            rumps.notification(
                title="FocusGuard",
                subtitle="Rest Mode teardown issue",
                message="A monitor did not shut down cleanly. Check the console log.",
            )

    def _update_indicator(self, sender: rumps.Timer | None) -> None:
        if not self.session_manager.is_active:
            self.title = TITLE_REST
        else:
            if self.webcam_monitor.is_calibrating:
                self.title = TITLE_WORK_CALIBRATING
            elif self.webcam_monitor.is_capturing:
                self.title = TITLE_WORK_CAPTURING
            else:
                self.title = TITLE_WORK

        # Runs every second via the timer, so the popover (if open)
        # reflects live status too — not just after an explicit action.
        self.popover_controller.refresh_status_only()

    def _sync_ui_state(self) -> None:
        """Refresh the popover's display from the single source of truth
        (self.config / session_manager / trackers).

        Called after any state-changing action so the popover never shows
        a stale value after something changes it from any code path.
        """
        self._update_indicator(None)
        self.popover_controller.refresh()

    # -- distraction list ----------------------------------------------

    def _add_website(self, sender: rumps.MenuItem) -> None:
        response = rumps.Window(
            message="Enter a domain (e.g. reddit.com):",
            title="Add Distraction Website",
            ok="Add",
            cancel="Cancel",
        ).run()
        domain = response.text.strip()
        if response.clicked and domain:
            self.distraction_list.add_domain(domain)
            self._sync_ui_state()

    def _add_app(self, sender: rumps.MenuItem) -> None:
        response = rumps.Window(
            message="Enter an app name exactly as it appears in the menu bar (e.g. TikTok):",
            title="Add Distraction App",
            ok="Add",
            cancel="Cancel",
        ).run()
        app_name = response.text.strip()
        if response.clicked and app_name:
            self.distraction_list.add_app(app_name)
            self._sync_ui_state()

    def _remove_website_prompt(self, sender: rumps.MenuItem | None) -> None:
        """Prompts for a domain to remove — the popover has no per-item
        click target (it's a read-only text summary), so this is a
        simple type-the-name-to-remove flow rather than clicking an item."""
        response = rumps.Window(
            message="Enter the exact domain to remove (see the list above):",
            title="Remove Distraction Website",
            ok="Remove",
            cancel="Cancel",
        ).run()
        domain = response.text.strip()
        if response.clicked and domain:
            self.distraction_list.remove_domain(domain)
            self._sync_ui_state()

    def _remove_app_prompt(self, sender: rumps.MenuItem | None) -> None:
        """Prompts for an app name to remove — see _remove_website_prompt."""
        response = rumps.Window(
            message="Enter the exact app name to remove (see the list above):",
            title="Remove Distraction App",
            ok="Remove",
            cancel="Cancel",
        ).run()
        app_name = response.text.strip()
        if response.clicked and app_name:
            self.distraction_list.remove_app(app_name)
            self._sync_ui_state()

    # -- distraction settings --------------------------------------------

    def _toggle_repeat(self, sender: rumps.MenuItem) -> None:
        new_value = not self.config["distractions"]["repeat_notification"]
        self.config["distractions"]["repeat_notification"] = new_value
        save_config(self.config)
        self._sync_ui_state()

    # -- webcam settings ---------------------------------------------------

    def _toggle_webcam_enabled(self, sender: rumps.MenuItem) -> None:
        new_value = not self.config["webcam"]["enabled"]
        self.config["webcam"]["enabled"] = new_value
        save_config(self.config)
        if not new_value:
            # Privacy-critical: release the camera immediately, don't
            # wait for the next Work/Rest cycle.
            self.webcam_monitor.stop()
        elif self.session_manager.is_active:
            self.webcam_monitor.start()
        self._sync_ui_state()

    def _toggle_webcam_repeat(self, sender: rumps.MenuItem) -> None:
        new_value = not self.config["webcam"]["repeat_notification"]
        self.config["webcam"]["repeat_notification"] = new_value
        save_config(self.config)
        self._sync_ui_state()

    def _toggle_phone_detection(self, sender: rumps.MenuItem) -> None:
        new_value = not self.config["webcam"]["phone_detection_enabled"]
        self.config["webcam"]["phone_detection_enabled"] = new_value
        save_config(self.config)
        # PhoneDetector is only created at the start of a webcam session —
        # restart it now so the change takes effect immediately rather
        # than silently waiting for the next Work Mode toggle.
        if self.session_manager.is_active and self.webcam_monitor.enabled:
            self.webcam_monitor.stop()
            self.webcam_monitor.start()
        self._sync_ui_state()

    def _recalibrate_webcam(self, sender: rumps.MenuItem) -> None:
        self.webcam_monitor.recalibrate()
        if self.session_manager.is_active and self.webcam_monitor.enabled:
            self.webcam_monitor.stop()
            self.webcam_monitor.start()
            rumps.alert(
                title="Recalibrating",
                message="Look at your screen normally when calibration starts.",
            )
        else:
            rumps.alert(
                title="Recalibrate",
                message="Baseline cleared — calibration will run at the start of your next Work Mode session.",
            )

    # -- analytics ---------------------------------------------------------

    def _toggle_analytics_enabled(self, sender: rumps.MenuItem) -> None:
        new_value = not self.config["analytics"]["enabled"]
        self.config["analytics"]["enabled"] = new_value
        save_config(self.config)
        if self.session_manager.is_active:
            if new_value:
                self.analytics.start_session()
            else:
                # Finalize what's been collected so far rather than leaving
                # an open-ended session row; re-enabling starts a fresh one.
                self.analytics.end_session()
        self._sync_ui_state()

    def _show_last_summary(self, sender: rumps.MenuItem) -> None:
        if self.analytics.last_summary is None:
            rumps.alert(
                title="No Session Yet",
                message="Complete a Work Mode session with analytics enabled to see a summary here.",
            )
            return
        self._show_session_summary(self.analytics.last_summary, via_notification=False)

    def _show_session_summary(self, summary: SessionSummary, via_notification: bool) -> None:
        minutes_off_task = summary.total_off_task_seconds / 60
        longest_streak_minutes = summary.longest_streak_seconds / 60
        message = (
            f"{summary.distraction_count} distractions, "
            f"{minutes_off_task:.0f} min off-task, "
            f"longest streak: {longest_streak_minutes:.0f} min"
        )
        if via_notification:
            rumps.notification(title="FocusGuard", subtitle="Session Summary", message=message)
        else:
            rumps.alert(title="Last Session Summary", message=message)

    def _reveal_database(self, sender: rumps.MenuItem) -> None:
        if not db.DB_PATH.exists():
            rumps.alert(
                title="No Database Yet",
                message="No analytics have been recorded yet — enable analytics and complete a Work Mode session first.",
            )
            return
        subprocess.run(["open", "-R", str(db.DB_PATH)], check=False)

    def _export_csv(self, sender: rumps.MenuItem) -> None:
        if not db.fetch_all_sessions():
            rumps.alert(title="Nothing to Export", message="No sessions recorded yet.")
            return
        export_path = Path.home() / "Downloads" / f"focusguard_sessions_{datetime.now():%Y%m%d_%H%M%S}.csv"
        export_path.parent.mkdir(parents=True, exist_ok=True)
        db.export_csv(export_path)
        subprocess.run(["open", "-R", str(export_path)], check=False)


def run() -> None:
    FocusGuardApp().run()
