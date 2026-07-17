# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec.

Build with:
    source .venv/bin/activate
    pyinstaller FocusGuard.spec

Produces dist/FocusGuard.app — a standalone bundle with its own Python
interpreter and dependencies, launchable by double-click with no
Terminal or venv required.

py2app was tried first (per the brief's suggestion) but hits a known,
documented limitation bundling mediapipe's libmediapipe.dylib: macholib
can't fit the rewritten load-command headers into the binary's existing
header padding ("Mach-O header too large to relocate"), and there's no
supported way to patch that padding onto an already-compiled dylib
after the fact. PyInstaller's binary handling doesn't hit this — its
collect_all() mechanism is also more reliable for mediapipe/cv2's
dynamically-loaded submodules, which is why it's used for all three
heavy/complex packages below rather than relying on default import
tracing.
"""

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

for pkg in ("mediapipe", "cv2", "rumps"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FocusGuard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="FocusGuard",
)

app = BUNDLE(
    coll,
    name="FocusGuard.app",
    icon=None,
    bundle_identifier="com.focusguard.app",
    info_plist={
        "CFBundleName": "FocusGuard",
        "CFBundleDisplayName": "FocusGuard",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        # Menu-bar-only app: no Dock icon, no Cmd-Tab app-switcher entry.
        "LSUIElement": True,
        # Required for macOS to even show the camera permission prompt —
        # without this key, a packaged app's camera access attempt fails
        # silently instead of prompting.
        "NSCameraUsageDescription": (
            "FocusGuard samples your webcam locally during Work Mode to detect "
            "sustained looking-down or looking-away posture. No video frame is "
            "ever saved or transmitted — only a live pitch/yaw reading exists "
            "in memory, discarded immediately after each sample."
        ),
        # Required for the Automation permission prompt that lets FocusGuard
        # ask Safari/Chrome/Arc for the active tab's URL during Work Mode.
        "NSAppleEventsUsageDescription": (
            "FocusGuard checks the frontmost browser's active tab URL during "
            "Work Mode to detect distracting websites. This runs entirely "
            "locally and the URL is never saved beyond the current session."
        ),
        "NSHighResolutionCapable": True,
    },
)
