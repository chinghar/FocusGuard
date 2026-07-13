# FocusGuard

A local-only macOS menu-bar app that helps you stay on task during work
sessions. No cloud services, no data leaves the machine — this matters
especially for the webcam feed, which is never saved or transmitted.

## Status

Phase 0: project skeleton. Work/Rest mode toggle in the menu bar only.
No webcam capture, no app/site tracking, no analytics yet — those land
in later phases, gated behind the same Work Mode switch so the "camera
never active outside Work Mode" guarantee holds from day one.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
source .venv/bin/activate
python3 main.py
```

A menu-bar item labeled "⚪️ FocusGuard" appears. Click it and choose
"Start Work Mode" to toggle — the icon switches to "🟢 FocusGuard" and
back. Quit anytime via "Quit FocusGuard" in the menu.

## Config

On first run, a default config is written to `~/.focusguard/config.json`
(thresholds, distraction app/domain list, analytics opt-in). This path
is derived from `Path.home()`, never hardcoded, so the project is
portable to other users/machines.

## Project layout

```
focusguard/
  app.py      rumps.App — menu bar UI, Work/Rest mode state
  config.py   load/save ~/.focusguard/config.json, defaults
main.py       entry point
```
