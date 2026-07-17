"""Native macOS notifications via osascript — no extra dependency."""

from __future__ import annotations

import subprocess

DEVNULL = subprocess.DEVNULL


def send_notification(title: str, subtitle: str, message: str) -> None:
    """A passive banner — for informational messages (calibration status,
    session summaries) that don't need the user's immediate attention."""
    script = (
        f'display notification "{_escape(message)}" '
        f'with title "{_escape(title)}" subtitle "{_escape(subtitle)}"'
    )
    subprocess.run(["osascript", "-e", script], check=False)


def send_alert(title: str, message: str, sound_name: str = "Ping") -> None:
    """A harder-to-miss nudge: a system sound plus a modal dialog the
    user has to dismiss — for "you're off track" moments where a passive
    notification banner is too easy to not notice.

    Both the sound and the dialog are launched via Popen, not run() —
    display alert blocks until the user clicks OK, and the caller here
    is typically a tracker's background polling thread. Blocking that
    thread on subprocess.run() would freeze polling until the dialog is
    dismissed, and worse, could stall stop()'s thread.join() past its
    timeout when Work Mode ends — risking the camera not releasing
    promptly. Popen lets the dialog run in its own detached process
    while the polling loop continues immediately.
    """
    sound_path = f"/System/Library/Sounds/{sound_name}.aiff"
    subprocess.Popen(["afplay", sound_path], stdout=DEVNULL, stderr=DEVNULL)

    script = f'display alert "{_escape(title)}" message "{_escape(message)}" as warning'
    subprocess.Popen(["osascript", "-e", script], stdout=DEVNULL, stderr=DEVNULL)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')
