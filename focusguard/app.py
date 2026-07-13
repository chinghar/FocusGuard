"""Menu-bar UI: Work/Rest toggle backed by SessionManager.

SessionManager is the single source of truth for whether monitoring
should be active — the menu-bar UI reads and drives it but never keeps
an independent mode flag of its own, so the displayed state and the
actual active-state can't silently drift apart. Starts in Rest Mode on
every launch: monitoring never resumes just because the app was quit
while in Work Mode last time.
"""

from __future__ import annotations

import rumps

from focusguard.config import load_config
from focusguard.session import SessionManager

TITLE_REST = "⚪️ FocusGuard"
TITLE_WORK = "🟢 FocusGuard"


class FocusGuardApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(name="FocusGuard", title=TITLE_REST, quit_button="Quit FocusGuard")
        self.config = load_config()
        self.session_manager = SessionManager()

        self.toggle_item = rumps.MenuItem("Start Work Mode", callback=self.toggle_mode)
        self.status_item = rumps.MenuItem("Status: Rest Mode")
        self.status_item.set_callback(None)  # display-only, not clickable

        self.menu = [
            self.status_item,
            None,  # separator
            self.toggle_item,
        ]

    def toggle_mode(self, sender: rumps.MenuItem) -> None:
        if self.session_manager.is_active:
            self._enter_rest_mode()
        else:
            self._enter_work_mode()

    def _enter_work_mode(self) -> None:
        self.session_manager.start_session()
        self.title = TITLE_WORK
        self.status_item.title = "Status: Work Mode"
        self.toggle_item.title = "Stop Work Mode"
        # Later phases: webcam monitor + app/site tracker register their
        # stop hooks via self.session_manager.on_stop(...) and start here.

    def _enter_rest_mode(self) -> None:
        _session, errors = self.session_manager.stop_session()
        self.title = TITLE_REST
        self.status_item.title = "Status: Rest Mode"
        self.toggle_item.title = "Start Work Mode"
        if errors:
            # A monitor's teardown failed — surface it rather than
            # silently trusting that tracking actually stopped.
            rumps.notification(
                title="FocusGuard",
                subtitle="Rest Mode teardown issue",
                message="A monitor did not shut down cleanly. Check the console log.",
            )


def run() -> None:
    FocusGuardApp().run()
