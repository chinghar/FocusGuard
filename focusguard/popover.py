"""The primary FocusGuard UI: a custom NSPopover (not a native NSMenu)
that appears when you click the menu-bar icon, showing the full
card-based settings content — Mode, Distraction List, Webcam, Analytics
— in one consistent, "sleek" surface instead of navigating a plain
macOS dropdown.

This replaces the native menu entirely for left-click. A native NSMenu
attached via NSStatusItem.setMenu_() is a hard macOS constraint — it
cannot be restyled (no custom colors/spacing/rounded corners; Apple
keeps menu-bar dropdowns visually consistent system-wide on purpose).
An NSPopover anchored to the status item, showing an arbitrary custom
NSView, is the standard technique other "sleek popup" menu-bar apps
use to get around that. rumps doesn't support this out of the box (it
wires NSStatusItem.setMenu_() directly — see FocusGuardApp), so the
status item's menu is detached and its button's click handler is
rewired to this controller instead. Right-click still shows a minimal
native menu with just Quit, since that's not something worth
reinventing and is a well-understood macOS convention.

Every control here calls straight into FocusGuardApp's existing
handlers (the same ones used before this became a popover) rather than
duplicating any config-mutation or side-effect logic, so there is
exactly one implementation of "what happens when you toggle webcam
monitoring" no matter what UI triggered it. `FocusGuardApp._sync_ui_state`
calls back into `refresh()` here whenever state changes from any
source.

Visual style: grouped "card" sections (rounded, layered background),
SF Symbols section icons, NSSwitch toggles, and semantic system colors
throughout (NSColor.labelColor / .secondaryLabelColor / .controlBackgroundColor
/ .windowBackgroundColor) rather than hardcoded values, matching modern
macOS System Settings styling and adapting automatically to Dark Mode.
"""

from __future__ import annotations

import objc
from AppKit import (
    NSApp,
    NSButton,
    NSColor,
    NSControlSizeLarge,
    NSEventTypeRightMouseUp,
    NSFont,
    NSFontWeightMedium,
    NSFontWeightSemibold,
    NSImage,
    NSImageView,
    NSMenu,
    NSMenuItem,
    NSMinYEdge,
    NSNoBorder,
    NSObject,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSRoundedBezelStyle,
    NSScrollView,
    NSSwitch,
    NSTextField,
    NSTextFieldSquareBezel,
    NSView,
    NSViewController,
)
from Foundation import NSMakePoint, NSMakeRect

from focusguard.config import save_config

CONTENT_WIDTH_TOTAL = 540
MARGIN = 24
CARD_PADDING = 18
CONTENT_WIDTH = CONTENT_WIDTH_TOTAL - 2 * MARGIN
CARD_INNER_WIDTH = CONTENT_WIDTH - 2 * CARD_PADDING
CARD_GAP = 24
CORNER_RADIUS = 12.0
# NSPopover silently clips content taller than the available screen space
# below the status item — it does NOT scroll or shrink cards on its own.
# The actual card content stays its full natural height (unchanged from
# the original design); this just caps how much of it is visible at once
# through a scroll view, so nothing is ever lost off-screen again.
MAX_POPOVER_HEIGHT = 700


class _Layout:
    """Tracks a top-down y cursor so control frames don't need to be
    hand-computed and re-adjusted every time a row is added or removed."""

    def __init__(self, x: float, top_y: float, width: float) -> None:
        self.x = x
        self.y = top_y
        self.width = width

    def row(self, height: float, spacing: float = 8) -> tuple:
        """Returns a plain (x, y, width, height) tuple — NOT an NSRect,
        whose actual memory layout is a nested (origin, size) struct that
        doesn't support flat indexing the way a plain tuple does."""
        self.y -= height
        frame = (self.x, self.y, self.width, height)
        self.y -= spacing
        return frame

    def half_row(self, height: float, spacing: float = 8) -> tuple:
        """Two side-by-side (x, y, width, height) tuples within the current row."""
        self.y -= height
        gap = 10
        half_width = (self.width - gap) / 2
        left = (self.x, self.y, half_width, height)
        right = (self.x + half_width + gap, self.y, half_width, height)
        self.y -= spacing
        return left, right


def _card(frame) -> NSView:
    """A rounded, layered-background container view — subviews are added
    to it directly and positioned relative to its own (0, 0) origin, not
    the parent's, since that's how AppKit view coordinate spaces nest."""
    view = NSView.alloc().initWithFrame_(NSMakeRect(*frame))
    view.setWantsLayer_(True)
    layer = view.layer()
    layer.setCornerRadius_(CORNER_RADIUS)
    layer.setBackgroundColor_(NSColor.controlBackgroundColor().CGColor())
    return view


def _icon(frame, symbol_name: str) -> NSImageView:
    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol_name, None)
    image.setTemplate_(True)
    view = NSImageView.alloc().initWithFrame_(NSMakeRect(*frame))
    view.setImage_(image)
    view.setContentTintColor_(NSColor.secondaryLabelColor())
    return view


def _section_header(card: NSView, layout: _Layout, title: str, symbol_name: str) -> None:
    frame = layout.row(24, 14)
    x, y, _w, h = frame
    card.addSubview_(_icon((x, y + 2, 18, 18), symbol_name))
    label = NSTextField.alloc().initWithFrame_(NSMakeRect(x + 26, y, 300, h))
    label.setStringValue_(title)
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setFont_(NSFont.systemFontOfSize_weight_(15, NSFontWeightSemibold))
    label.setTextColor_(NSColor.labelColor())
    card.addSubview_(label)


def _label(frame, text: str, secondary: bool = False) -> NSTextField:
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(*frame))
    field.setStringValue_(text)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    field.setFont_(NSFont.systemFontOfSize_(13))
    field.setTextColor_(NSColor.secondaryLabelColor() if secondary else NSColor.labelColor())
    return field


def _switch_row(card: NSView, layout: _Layout, title: str, target, action: str) -> NSSwitch:
    """A settings-app-style row: label on the left, pill toggle on the
    right. Returns the switch so the caller can stash it for refresh()."""
    frame = layout.row(24, 10)
    x, y, w, h = frame
    label = _label((x, y + 3, w - 60, 18), title)
    card.addSubview_(label)
    sw = NSSwitch.alloc().initWithFrame_(NSMakeRect(x + w - 40, y - 3, 40, 26))
    sw.setTarget_(target)
    sw.setAction_(action)
    card.addSubview_(sw)
    return sw


def _wrapping_readonly_field(frame, text: str = "") -> NSTextField:
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(*frame))
    field.setStringValue_(text)
    field.setBezeled_(True)
    field.setBezelStyle_(NSTextFieldSquareBezel)
    field.setDrawsBackground_(True)
    field.setBackgroundColor_(NSColor.textBackgroundColor())
    field.setEditable_(False)
    field.setSelectable_(True)
    field.setFont_(NSFont.systemFontOfSize_(12))
    field.setTextColor_(NSColor.labelColor())
    cell = field.cell()
    cell.setWraps_(True)
    cell.setScrollable_(False)
    return field


def _editable_field(frame, value: str = "") -> NSTextField:
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(*frame))
    field.setStringValue_(value)
    field.setEditable_(True)
    field.setSelectable_(True)
    field.setFont_(NSFont.systemFontOfSize_(13))
    return field


def _button(frame, title: str, target, action: str, large: bool = False) -> NSButton:
    button = NSButton.alloc().initWithFrame_(NSMakeRect(*frame))
    button.setBezelStyle_(NSRoundedBezelStyle)
    button.setTitle_(title)
    button.setTarget_(target)
    button.setAction_(action)
    if large:
        button.setControlSize_(NSControlSizeLarge)
        button.setFont_(NSFont.systemFontOfSize_weight_(13, NSFontWeightMedium))
    return button


class PopoverController(NSObject):
    """Standard PyObjC pattern: NSObject subclasses can't take Python
    __init__ args through alloc().init(), so construction goes through
    the module-level build_popover_controller() factory below, which
    does the two-step alloc/init and then finishes setup as plain Python.

    Plain Python-only helper methods here are marked @objc.python_method
    so PyObjC's class-body scanner doesn't try to bridge them as
    Objective-C selectors (which have different argument-count rules) —
    only the trailing-underscore action methods (wired as button/field/
    status-item targets) are meant to be real selectors.
    """

    @objc.python_method
    def toggle(self, sender_view) -> None:
        """Show the popover anchored below the status item button, or
        close it if already showing — called on a left-click."""
        if self.popover.isShown():
            self.popover.close()
        else:
            self.refresh()
            self.popover.showRelativeToRect_ofView_preferredEdge_(
                sender_view.bounds(), sender_view, NSMinYEdge
            )
            # NSView's default coordinate origin is bottom-left, so an
            # NSScrollView opens scrolled to the BOTTOM of its document by
            # default — the opposite of what's wanted here. Explicitly
            # scroll to the top (highest y = the Mode card, the first
            # thing you should see) every time the popover opens.
            self.content_view.scrollPoint_(NSMakePoint(0, self.total_content_height))

    # -- status item click routing -------------------------------------

    def statusItemClicked_(self, sender) -> None:
        event = NSApp().currentEvent()
        if event is not None and event.type() == NSEventTypeRightMouseUp:
            self._show_quit_menu(sender)
        else:
            self.toggle(sender)

    @objc.python_method
    def _show_quit_menu(self, sender) -> None:
        menu = NSMenu.alloc().init()
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit FocusGuard", "quitClicked:", ""
        )
        item.setTarget_(self)
        menu.addItem_(item)
        event = NSApp().currentEvent()
        NSMenu.popUpContextMenu_withEvent_forView_(menu, event, sender)

    def quitClicked_(self, sender) -> None:
        import rumps

        rumps.quit_application()

    # -- construction ----------------------------------------------------

    @objc.python_method
    def _build_content(self) -> None:
        mode_card_height = 172
        distraction_card_height = 328
        webcam_card_height = 262
        analytics_card_height = 232

        total_height = (
            MARGIN
            + mode_card_height
            + CARD_GAP
            + distraction_card_height
            + CARD_GAP
            + webcam_card_height
            + CARD_GAP
            + analytics_card_height
            + CARD_GAP
            + 32
            + MARGIN
        )

        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, CONTENT_WIDTH_TOTAL, total_height))
        content.setWantsLayer_(True)
        content.layer().setBackgroundColor_(NSColor.windowBackgroundColor().CGColor())

        layout = _Layout(MARGIN, total_height - MARGIN, CONTENT_WIDTH)

        mode_card = _card((MARGIN, layout.y - mode_card_height, CONTENT_WIDTH, mode_card_height))
        content.addSubview_(mode_card)
        inner = _Layout(CARD_PADDING, mode_card_height - CARD_PADDING, CARD_INNER_WIDTH)
        _section_header(mode_card, inner, "Mode", "power.circle.fill")
        self.mode_status_label = _label(inner.row(18, 4), "Status: Rest Mode")
        mode_card.addSubview_(self.mode_status_label)
        self.camera_status_label = _label(inner.row(18, 14), "Camera: off", secondary=True)
        mode_card.addSubview_(self.camera_status_label)
        self.mode_button = _button(
            inner.row(36, 0), "Start Work Mode", self, "modeButtonClicked:", large=True
        )
        mode_card.addSubview_(self.mode_button)
        layout.y -= mode_card_height + CARD_GAP

        distraction_card = _card(
            (MARGIN, layout.y - distraction_card_height, CONTENT_WIDTH, distraction_card_height)
        )
        content.addSubview_(distraction_card)
        inner = _Layout(CARD_PADDING, distraction_card_height - CARD_PADDING, CARD_INNER_WIDTH)
        _section_header(distraction_card, inner, "Distraction List", "network")
        self.distraction_list_field = _wrapping_readonly_field(inner.row(100, 10))
        distraction_card.addSubview_(self.distraction_list_field)
        add_left, add_right = inner.half_row(28, 8)
        distraction_card.addSubview_(_button(add_left, "Add Website...", self, "addWebsiteClicked:"))
        distraction_card.addSubview_(_button(add_right, "Add App...", self, "addAppClicked:"))
        remove_left, remove_right = inner.half_row(28, 14)
        distraction_card.addSubview_(_button(remove_left, "Remove Website...", self, "removeWebsiteClicked:"))
        distraction_card.addSubview_(_button(remove_right, "Remove App...", self, "removeAppClicked:"))

        tx, ty, _tw, _th = inner.row(24, 10)
        distraction_card.addSubview_(_label((tx, ty + 3, 200, 18), "Threshold (minutes)", secondary=True))
        self.distraction_threshold_field = _editable_field((tx + 210, ty, CARD_INNER_WIDTH - 210, 22))
        self.distraction_threshold_field.setTarget_(self)
        self.distraction_threshold_field.setAction_("distractionThresholdChanged:")
        distraction_card.addSubview_(self.distraction_threshold_field)

        self.distraction_repeat_switch = _switch_row(
            distraction_card, inner, "Repeat Nudges While Distracted", self, "toggleDistractionRepeat:"
        )
        layout.y -= distraction_card_height + CARD_GAP

        webcam_card = _card((MARGIN, layout.y - webcam_card_height, CONTENT_WIDTH, webcam_card_height))
        content.addSubview_(webcam_card)
        inner = _Layout(CARD_PADDING, webcam_card_height - CARD_PADDING, CARD_INNER_WIDTH)
        _section_header(webcam_card, inner, "Webcam", "camera.fill")
        self.webcam_enabled_switch = _switch_row(webcam_card, inner, "Enabled", self, "toggleWebcamEnabled:")

        wx, wy, _ww, _wh = inner.row(24, 10)
        webcam_card.addSubview_(_label((wx, wy + 3, 200, 18), "Sustained Threshold (sec)", secondary=True))
        self.webcam_threshold_field = _editable_field((wx + 210, wy, CARD_INNER_WIDTH - 210, 22))
        self.webcam_threshold_field.setTarget_(self)
        self.webcam_threshold_field.setAction_("webcamThresholdChanged:")
        webcam_card.addSubview_(self.webcam_threshold_field)

        self.webcam_repeat_switch = _switch_row(
            webcam_card, inner, "Repeat Nudges While Off-Track", self, "toggleWebcamRepeat:"
        )
        self.phone_detection_switch = _switch_row(
            webcam_card, inner, "Detect Phone in Frame", self, "togglePhoneDetection:"
        )
        webcam_card.addSubview_(_button(inner.row(30, 0), "Recalibrate...", self, "recalibrateClicked:"))
        layout.y -= webcam_card_height + CARD_GAP

        analytics_card = _card(
            (MARGIN, layout.y - analytics_card_height, CONTENT_WIDTH, analytics_card_height)
        )
        content.addSubview_(analytics_card)
        inner = _Layout(CARD_PADDING, analytics_card_height - CARD_PADDING, CARD_INNER_WIDTH)
        _section_header(analytics_card, inner, "Analytics", "chart.bar.fill")
        self.analytics_switch = _switch_row(
            analytics_card, inner, "Log Distraction Events (opt-in)", self, "toggleAnalyticsEnabled:"
        )
        analytics_card.addSubview_(
            _button(inner.row(28, 8), "Last Session Summary...", self, "lastSummaryClicked:")
        )
        analytics_card.addSubview_(
            _button(inner.row(28, 8), "Reveal Database in Finder", self, "revealDatabaseClicked:")
        )
        analytics_card.addSubview_(
            _button(inner.row(28, 0), "Export Session History as CSV...", self, "exportCsvClicked:")
        )
        layout.y -= analytics_card_height + CARD_GAP

        close_frame = (CONTENT_WIDTH_TOTAL - MARGIN - 100, MARGIN, 100, 32)
        content.addSubview_(_button(close_frame, "Done", self, "closeClicked:", large=True))

        # NSPopover clips content taller than the available screen space
        # below the status item rather than scrolling or shrinking it —
        # confirmed directly: the Mode card (at the top of `content`,
        # i.e. the highest y-values) silently disappeared when total_height
        # (1170) exceeded what fit on screen. Every card above stays
        # exactly the size/spacing it was designed with; only the visible
        # viewport is capped, via a scroll view, so nothing is ever lost.
        visible_height = min(total_height, MAX_POPOVER_HEIGHT)
        scroll_view = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, 0, CONTENT_WIDTH_TOTAL, visible_height)
        )
        scroll_view.setDocumentView_(content)
        scroll_view.setHasVerticalScroller_(True)
        scroll_view.setHasHorizontalScroller_(False)
        scroll_view.setAutohidesScrollers_(True)
        scroll_view.setBorderType_(NSNoBorder)
        scroll_view.setDrawsBackground_(False)

        view_controller = NSViewController.alloc().init()
        view_controller.setView_(scroll_view)

        popover = NSPopover.alloc().init()
        popover.setContentViewController_(view_controller)
        popover.setContentSize_((CONTENT_WIDTH_TOTAL, visible_height))
        popover.setBehavior_(NSPopoverBehaviorTransient)
        popover.setDelegate_(self)

        self.view_controller = view_controller
        self.popover = popover
        self.content_view = content
        self.total_content_height = total_height

    # -- refresh -----------------------------------------------------------

    @objc.python_method
    def refresh_status_only(self) -> None:
        """Cheap refresh for the 1-second timer tick: mode/camera status
        only, not the full config resync (list contents, switches)."""
        app = self.app
        if app.session_manager.is_active:
            self.mode_status_label.setStringValue_("Status: Work Mode")
            self.mode_button.setTitle_("Stop Work Mode")
            if app.webcam_monitor.is_calibrating:
                self.camera_status_label.setStringValue_("Camera: calibrating...")
            elif app.webcam_monitor.is_capturing:
                self.camera_status_label.setStringValue_("Camera: capturing")
            else:
                self.camera_status_label.setStringValue_("Camera: off")
        else:
            self.mode_status_label.setStringValue_("Status: Rest Mode")
            self.mode_button.setTitle_("Start Work Mode")
            self.camera_status_label.setStringValue_("Camera: off")

    @objc.python_method
    def refresh(self) -> None:
        """Full resync from current config — called after any setting
        changes, from whichever UI surface changed it."""
        app = self.app
        self.refresh_status_only()

        websites = ", ".join(app.distraction_list.domains) or "(none)"
        apps = ", ".join(app.distraction_list.apps) or "(none)"
        self.distraction_list_field.setStringValue_(f"Websites: {websites}\n\nApps: {apps}")

        threshold_minutes = app.config["distractions"]["continuous_threshold_seconds"] / 60
        self.distraction_threshold_field.setStringValue_(f"{threshold_minutes:g}")
        self.distraction_repeat_switch.setState_(
            1 if app.config["distractions"]["repeat_notification"] else 0
        )

        self.webcam_enabled_switch.setState_(1 if app.config["webcam"]["enabled"] else 0)
        self.webcam_threshold_field.setStringValue_(
            f"{app.config['webcam']['sustained_threshold_seconds']:g}"
        )
        self.webcam_repeat_switch.setState_(1 if app.config["webcam"]["repeat_notification"] else 0)
        self.phone_detection_switch.setState_(1 if app.config["webcam"]["phone_detection_enabled"] else 0)

        self.analytics_switch.setState_(1 if app.config["analytics"]["enabled"] else 0)

    # -- actions -------------------------------------------------------

    def modeButtonClicked_(self, sender) -> None:
        self.app.toggle_mode(None)

    def addWebsiteClicked_(self, sender) -> None:
        self.app._add_website(None)

    def addAppClicked_(self, sender) -> None:
        self.app._add_app(None)

    def removeWebsiteClicked_(self, sender) -> None:
        self.app._remove_website_prompt(None)

    def removeAppClicked_(self, sender) -> None:
        self.app._remove_app_prompt(None)

    def toggleDistractionRepeat_(self, sender) -> None:
        self.app._toggle_repeat(None)

    def toggleWebcamEnabled_(self, sender) -> None:
        self.app._toggle_webcam_enabled(None)

    def toggleWebcamRepeat_(self, sender) -> None:
        self.app._toggle_webcam_repeat(None)

    def togglePhoneDetection_(self, sender) -> None:
        self.app._toggle_phone_detection(None)

    def recalibrateClicked_(self, sender) -> None:
        self.app._recalibrate_webcam(None)

    def toggleAnalyticsEnabled_(self, sender) -> None:
        self.app._toggle_analytics_enabled(None)

    def lastSummaryClicked_(self, sender) -> None:
        self.app._show_last_summary(None)

    def revealDatabaseClicked_(self, sender) -> None:
        self.app._reveal_database(None)

    def exportCsvClicked_(self, sender) -> None:
        self.app._export_csv(None)

    def closeClicked_(self, sender) -> None:
        self.popover.close()

    def distractionThresholdChanged_(self, sender) -> None:
        self._commit_distraction_threshold()

    def webcamThresholdChanged_(self, sender) -> None:
        self._commit_webcam_threshold()

    def popoverWillClose_(self, notification) -> None:
        # Safety net for a field edited but not confirmed with Enter —
        # commit whatever's currently typed before the popover disappears.
        self._commit_distraction_threshold()
        self._commit_webcam_threshold()

    # -- threshold field commit (shared by action + popover-close paths) --

    @objc.python_method
    def _commit_distraction_threshold(self) -> None:
        app = self.app
        text = str(self.distraction_threshold_field.stringValue()).strip()
        try:
            minutes = float(text)
            if minutes <= 0:
                raise ValueError
        except ValueError:
            self.refresh()  # bad input — snap the field back to the last valid value
            return
        current_seconds = app.config["distractions"]["continuous_threshold_seconds"]
        if abs(minutes * 60 - current_seconds) < 1e-9:
            return  # unchanged, avoid a needless save + refresh
        app.config["distractions"]["continuous_threshold_seconds"] = int(minutes * 60)
        save_config(app.config)
        app._sync_ui_state()

    @objc.python_method
    def _commit_webcam_threshold(self) -> None:
        app = self.app
        text = str(self.webcam_threshold_field.stringValue()).strip()
        try:
            seconds = float(text)
            if seconds <= 0:
                raise ValueError
        except ValueError:
            self.refresh()
            return
        current_seconds = app.config["webcam"]["sustained_threshold_seconds"]
        if abs(seconds - current_seconds) < 1e-9:
            return
        app.config["webcam"]["sustained_threshold_seconds"] = seconds
        save_config(app.config)
        app._sync_ui_state()


def build_popover_controller(app) -> PopoverController:
    """Factory for PopoverController — NSObject subclasses can't take
    Python __init__ args through alloc().init(), so construction happens
    here: alloc/init, then plain Python attribute assignment and setup."""
    controller = PopoverController.alloc().init()
    controller.app = app
    controller._build_content()
    controller.refresh()
    return controller
