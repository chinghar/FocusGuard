# FocusGuard

A native macOS menu-bar app that helps you stay on task during work
sessions — webcam-based attention detection, app/website distraction
tracking, and optional local analytics, all gated behind an explicit
Work Mode / Rest Mode switch.

**Privacy principles, enforced structurally, not just by convention:**
- Everything runs locally. No cloud services, no network calls at
  runtime — the only network access FocusGuard ever makes is a one-time
  download of a generic ML model file on first webcam use (see
  [Permissions](#permissions-macos-will-ask-for) below).
- The camera is never active outside Work Mode. Camera open/close is
  reachable from exactly one code path (`WebcamMonitor.start()`/`stop()`,
  wired to the Work/Rest transition), and `stop()` always runs — even on
  error — so there's no path that leaves it running unattended.
- No webcam frame is ever saved to disk or transmitted anywhere. Each
  frame is read, converted to a `(pitch, yaw)` estimate, and discarded —
  only that pair of numbers exists in memory, for one poll cycle.
- The menu-bar icon changes to a distinct 🔴📷 state the instant the
  camera is actually capturing, and 🟡📷 while calibrating — the
  indicator is polled from live state every second, not a static label,
  so it can't drift from what's actually happening.
- Quit anytime via "Quit FocusGuard" in the menu — no background
  helper process, no login item installed without asking.

## Features

- **Work Mode / Rest Mode** toggle — the menu-bar icon makes the current
  mode unambiguous at a glance (⚪️ Rest, 🟢 Work, 🔴📷 Work + camera active).
- **Webcam attention detection** — periodic low-fps head-pose sampling
  (mediapipe FaceLandmarker) flags sustained "looking down" or "looking
  away," with a one-time personal calibration step so it adapts to your
  head geometry and camera angle.
- **App/website distraction tracking** — polls the frontmost app and, for
  Safari/Chrome/Arc, the active tab's URL, against an editable
  domain/app list. Nudges you after continuous (not cumulative) time on
  a distraction past a configurable threshold.
- **Opt-in local analytics** — off by default. When enabled, sessions and
  distraction events are logged to a local SQLite database, with an
  end-of-session summary (distraction count, total off-task time,
  longest uninterrupted streak) and CSV export.
- **Settings window** — one place to see and change everything above,
  in addition to the quicker menu-bar submenus.

## Permissions macOS will ask for

| Permission | When it's requested | Why |
|---|---|---|
| **Camera** | The first time you start Work Mode with webcam detection enabled | To sample frames for head-pose estimation. Requested from the main thread specifically so the system dialog can actually appear — see `focusguard/vision/permission.py`. |
| **Automation** (Apple Events) → Safari / Chrome / Arc | The first time FocusGuard polls a browser's active tab while one of those is frontmost during Work Mode | To read the active tab's URL via AppleScript, entirely locally. |
| **Notifications** | First nudge/summary notification | Native macOS notifications for nudges and session summaries. |

If you deny Camera or Automation access, FocusGuard doesn't retry
silently — webcam or browser-tab detection simply sits out that Work
Mode session, and you can grant access later in **System Settings →
Privacy & Security** and toggle Work Mode again.

On first webcam use, FocusGuard also downloads a ~3.6MB model file
(`face_landmarker.task`) from Google's public model CDN to
`~/.focusguard/models/` — a generic, non-personal set of neural network
weights, not anything derived from your camera. It's cached after the
first download; no further network calls happen.

## Running from source

Requires Python 3.11+ (developed against 3.13) and macOS.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

A menu-bar item labeled "⚪️ FocusGuard" appears. Click it to see Work
Mode, the distraction list, webcam/analytics settings, and "Open
Settings Window..." for the consolidated view.

## Building the standalone .app

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pyinstaller FocusGuard.spec
```

Produces `dist/FocusGuard.app` — double-click to launch, no Terminal or
Python environment needed on the machine that runs it. It has no Dock
icon (`LSUIElement`) — look for it in the menu bar.

**Why PyInstaller and not py2app**, despite py2app being the tool named
in the original brief: py2app hits a documented, unresolved limitation
bundling mediapipe's `libmediapipe.dylib` — macholib can't fit the
rewritten load-command headers into the binary's existing header
padding ("Mach-O header too large to relocate"), and there's no
supported way to patch that padding onto an already-compiled dylib
after the fact. This was verified directly (see `FocusGuard.spec`'s
header comment) before switching approaches. PyInstaller's binary
handling doesn't hit this, and its `collect_all()` mechanism is more
reliable for mediapipe/cv2's dynamically-loaded submodules.

The bundle is large (~250MB) — expected, since it embeds a full Python
interpreter plus opencv and mediapipe's native libraries.

## Configuration

Everything tunable lives in `~/.focusguard/config.json`, created with
sane defaults on first run. Nothing about a specific user or machine is
hardcoded into application logic — the only path baked into the code is
`Path.home() / ".focusguard"`.

Most of it is editable without touching the file directly, via the menu
bar or **Open Settings Window...**: Work/Rest toggle, the distraction
website/app list, both trackers' thresholds and repeat-nudge behavior,
webcam enabled/recalibrate, and the analytics opt-in.

A few advanced, rarely-touched knobs are config-file-only by design (to
keep the UI uncluttered), documented inline in
`focusguard/config.py`:
- `webcam.camera_index` — which camera device to use, for Macs with more than one.
- `webcam.pitch_down_threshold_degrees` / `yaw_away_threshold_degrees` — how far off the calibrated baseline counts as "off-track."
- `webcam.sample_interval_seconds` / `distractions.poll_interval_seconds` — polling cadence.
- `webcam.calibration_duration_seconds` — length of the one-time calibration pass.

Local data files, all under `~/.focusguard/`:
- `config.json` — settings (above).
- `models/face_landmarker.task` — the downloaded ML model (see [Permissions](#permissions-macos-will-ask-for)).
- `focusguard.db` — SQLite analytics database, only ever written to if you've opted in via `analytics.enabled`.

## Adapting this for another user or machine

The app was built with portability in mind from Phase 0, so adapting it
doesn't require touching application logic:

1. **Personal thresholds/lists** — just run the app; `~/.focusguard/config.json`
   is created per-user automatically, and the Settings window covers
   the common adjustments (distraction list, thresholds, webcam
   on/off, analytics opt-in).
2. **Changing the out-of-the-box defaults** for a fresh install (e.g.
   shipping this to someone else with a different starter distraction
   list) — edit `DEFAULT_CONFIG` in `focusguard/config.py`. That's the
   single source of truth for first-run defaults; nothing else needs to
   change.
3. **Multiple cameras** — set `webcam.camera_index` in config.json (or
   ask them to try `0`, `1`, ... until the right one responds).
4. **Adding a new supported browser** — browsers need their own
   AppleScript "get the active tab's URL" snippet (syntax differs per
   browser), so this is a small code change rather than a config value:
   add an entry to `BROWSER_TAB_SCRIPTS` in `focusguard/frontmost.py`
   with the app's exact name (as `NSWorkspace` reports it) and its
   tab-URL AppleScript.
5. **Packaging for someone else's machine** — build a fresh
   `dist/FocusGuard.app` per the instructions above and hand them the
   `.app` bundle directly; it carries no per-user state (that all lives
   in `~/.focusguard/` on whichever machine runs it).

## Project layout

```
focusguard/
  app.py                 rumps.App — menu bar UI, mode toggle, all menu wiring
  settings_window.py     Native AppKit settings window (PyObjC), mirrors the menu
  session.py             SessionManager — single source of truth for active/inactive
  streak.py              Shared "sustained condition -> nudge" state machine
  config.py              Load/save ~/.focusguard/config.json, defaults, paths
  distraction_list.py    Editable distraction domain/app list
  frontmost.py           Frontmost app + browser tab URL (AppKit + AppleScript)
  tracker.py             DistractionTracker — app/site polling loop
  notify.py               Native macOS notifications
  webcam_monitor.py      WebcamMonitor — camera lifecycle, calibration, polling loop
  vision/
    camera.py             cv2.VideoCapture wrapper, guaranteed release
    pose.py                mediapipe FaceLandmarker -> (pitch, yaw)
    classifier.py          Calibration baseline + posture classification
    model.py               One-time model download/cache
    permission.py           Main-thread camera authorization request
  analytics.py            AnalyticsRecorder — opt-in gate + session summary math
  db.py                   SQLite schema, queries, CSV export
main.py                  Entry point
FocusGuard.spec          PyInstaller build config
```
<!-- doc pass 1 -->
<!-- doc pass 2 -->
<!-- doc pass 3 -->
