"""Menu-bar skeleton: Work/Rest toggle only.

No webcam or app/site tracking here yet — those are separate monitors
added in later phases, started/stopped from ``_enter_work_mode`` /
``_enter_rest_mode`` below. Keeping the mode switch isolated first means
the "camera is never active outside Work Mode" guarantee is structural:
a monitor can only ever be started from one call site.
"""

from __future__ import annotations

from enum import Enum

import rumps

from focusguard.config import load_config


class Mode(Enum):
    REST = "rest"
    WORK = "work"


TITLE_REST = "⚪️ FocusGuard"
TITLE_WORK = "🟢 FocusGuard"


class FocusGuardApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(name="FocusGuard", title=TITLE_REST, quit_button="Quit FocusGuard")
        self.config = load_config()
        self.mode = Mode.REST

        self.toggle_item = rumps.MenuItem("Start Work Mode", callback=self.toggle_mode)
        self.status_item = rumps.MenuItem("Status: Rest Mode")
        self.status_item.set_callback(None)  # display-only, not clickable

        self.menu = [
            self.status_item,
            None,  # separator
            self.toggle_item,
        ]

    def toggle_mode(self, sender: rumps.MenuItem) -> None:
        if self.mode is Mode.REST:
            self._enter_work_mode()
        else:
            self._enter_rest_mode()

    def _enter_work_mode(self) -> None:
        self.mode = Mode.WORK
        self.title = TITLE_WORK
        self.status_item.title = "Status: Work Mode"
        self.toggle_item.title = "Stop Work Mode"
        # Later phases: start webcam monitor + app/site tracker here.

    def _enter_rest_mode(self) -> None:
        self.mode = Mode.REST
        self.title = TITLE_REST
        self.status_item.title = "Status: Rest Mode"
        self.toggle_item.title = "Start Work Mode"
        # Later phases: stop webcam monitor + app/site tracker here.


def run() -> None:
    FocusGuardApp().run()
