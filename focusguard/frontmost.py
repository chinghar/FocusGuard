"""Frontmost app + active browser tab URL, via AppKit and AppleScript.

Read-only OS queries only. The app name / URL returned here is compared
against the distraction list in memory and immediately discarded —
nothing in this module writes to disk or leaves the machine.
"""

from __future__ import annotations

import subprocess

from AppKit import NSWorkspace

BROWSER_TAB_SCRIPTS: dict[str, str] = {
    "Safari": 'tell application "Safari" to return URL of current tab of front window',
    "Google Chrome": 'tell application "Google Chrome" to return URL of active tab of front window',
    "Arc": 'tell application "Arc" to return URL of active tab of front window',
}

OSASCRIPT_TIMEOUT_SECONDS = 2


class BrowserQueryError(Exception):
    """The AppleScript tab query failed or timed out.

    This means "can't tell right now" — e.g. Automation permission not
    yet granted, or the browser is momentarily unresponsive — not "no
    distraction". Callers must not treat it as evidence either way.
    """


def get_frontmost_app_name() -> str | None:
    """Return the frontmost app's name, or None if it can't be determined."""
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        name = app.localizedName()
        return str(name) if name else None
    except Exception:
        return None


def get_active_browser_tab_url(app_name: str) -> str | None:
    """Return the active tab URL for a supported browser.

    Returns None when there's legitimately no URL to report (app isn't
    a supported browser, or the browser has no window open). Raises
    BrowserQueryError when the query itself failed.
    """
    script = BROWSER_TAB_SCRIPTS.get(app_name)
    if script is None:
        return None
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=OSASCRIPT_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise BrowserQueryError(str(exc)) from exc
    if result.returncode != 0:
        raise BrowserQueryError(result.stderr.strip() or "osascript failed")
    return result.stdout.strip() or None
