"""Full-screen transparent overlay window and application entry point."""

from __future__ import annotations

import logging
import os
import sys

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QCursor, QGuiApplication, QPainter
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from . import config, state, winapi
from .leaves import LeavesCanvas
from .menu import SlideMenu
from .snow import SnowCanvas
from .widgets import ArrowButton, HtmlPanel

LOGGER = logging.getLogger(__name__)


class HoverTracker(QObject):
    """Poll the cursor and report whether it is over an interactive widget.

    Polling (instead of enter/leave events) is required because while the
    window is click-through it receives no mouse events at all.
    """

    hoverChanged = pyqtSignal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._widgets: list[QWidget] = []
        self.active = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(config.HOVER_POLL_MS)

    def add(self, widget: QWidget) -> None:
        self._widgets.append(widget)

    def is_over(self) -> bool:
        """Whether the cursor currently sits over a tracked widget."""
        pos = QCursor.pos()
        return any(
            w.isVisible() and w.rect().contains(w.mapFromGlobal(pos)) for w in self._widgets
        )

    def _poll(self) -> None:
        active = self.is_over()
        if active != self.active:
            self.active = active
            state.hover_flag = active
            self.hoverChanged.emit(active)


class OverlayWindow(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._screen = None
        self.snow = SnowCanvas(self)
        self.leaves = LeavesCanvas(self)

        self.panels: list[HtmlPanel] = []
        self._panel_box = QWidget(self)
        self._panel_box.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        box_layout = QVBoxLayout(self._panel_box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(config.PANEL_SPACING)
        for panel_id, cfg in config.ACTIVE_PANELS.items():
            panel = HtmlPanel(panel_id, cfg, self._panel_box)
            box_layout.addWidget(panel, alignment=Qt.AlignmentFlag.AlignHCenter)
            self.panels.append(panel)

        self.arrow = ArrowButton(self)
        self.arrow.setObjectName("center_arrow")
        self.arrow.clicked.connect(self.toggle_menu)

        self.menu = SlideMenu(self)
        self.menu.snowToggled.connect(self._on_snow_toggled)
        self.menu.interactiveToggled.connect(self.snow.set_interactive)
        self.menu.windChanged.connect(self.snow.set_wind)
        self.menu.densityChanged.connect(self.snow.set_density)
        self.menu.fallChanged.connect(self.snow.set_fall_scale)
        self.menu.swayChanged.connect(self.snow.set_sway_scale)
        self.menu.sizeChanged.connect(self.snow.set_size_scale)
        self.menu.grabChanged.connect(self.snow.set_grab_radius)
        self.menu.clumpChanged.connect(self.snow.set_clump_max)
        self.menu.pileChanged.connect(self.snow.set_pile_max)
        self.menu.slopeChanged.connect(self.snow.set_pile_slope)
        self.menu.releasedWindChanged.connect(self.snow.set_released_wind)
        self.menu.releasedSpeedChanged.connect(self.snow.set_released_speed)
        self.menu.releasedSwayChanged.connect(self.snow.set_released_sway)
        self.menu.slipToggled.connect(self.snow.set_slip_enabled)
        self.menu.slipLeashChanged.connect(self.snow.set_clump_leash)
        self.menu.slipFollowChanged.connect(self.snow.set_follow_lerp)
        self.menu.windowsToggled.connect(self.snow.set_windows_enabled)
        self.menu.windowPileChanged.connect(self.snow.set_window_pile_max)
        self.menu.windowSlopeChanged.connect(self.snow.set_window_slope)
        self.menu.leavesToggled.connect(self.leaves.set_enabled)
        self.menu.leafDensityChanged.connect(self.leaves.set_density)
        self.menu.leafWindChanged.connect(self.leaves.set_wind)
        self.menu.leafSpeedChanged.connect(self.leaves.set_fall_scale)
        self.menu.leafSizeChanged.connect(self.leaves.set_size_scale)
        self.menu.leafSwirlChanged.connect(self.leaves.set_swirl_scale)
        self.menu.leafInteractiveToggled.connect(self.leaves.set_interactive)
        self.menu.leafWindowChanceChanged.connect(self.leaves.set_window_chance)
        self.menu.clickThroughToggled.connect(self.enable_click_through)

        self._click_through = True
        self._menu_open = False
        self._anim = QPropertyAnimation(self.menu, b"pos", self)
        self._anim.setDuration(config.MENU_SLIDE_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(lambda _value: self._sync_arrow())

        self.hover = HoverTracker(self)
        for panel in self.panels:
            self.hover.add(panel)
        self.hover.add(self.arrow)
        self.hover.add(self.menu)
        self.hover.hoverChanged.connect(self._on_hover_changed)
        self.menu.load_settings()

    # -- menu -----------------------------------------------------------
    def toggle_menu(self) -> None:
        self._menu_open = not self._menu_open
        self.arrow.set_open(self._menu_open)
        self._apply_menu_pos(animate=True)

    def _on_snow_toggled(self, enabled: bool) -> None:
        self.snow.set_enabled(enabled)
        self._apply_menu_pos(animate=True)

    def _menu_target(self) -> QPoint:
        """Menu position for the current open/closed state.

        The menu always fills the work area's height and scrolls internally.
        """
        w, h = self.width(), self.height()
        margin = config.MENU_MARGIN
        self.menu.setFixedHeight(max(120, h - 2 * margin))

        x = w - margin - self.menu.width() if self._menu_open else w
        return QPoint(x, margin)

    def _apply_menu_pos(self, animate: bool) -> None:
        target = self._menu_target()
        self._anim.stop()
        if animate and self.isVisible():
            self._anim.setStartValue(self.menu.pos())
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self.menu.move(target)
            self._sync_arrow()

    def _sync_arrow(self) -> None:
        w, h = self.width(), self.height()
        x = self.menu.x() - self.arrow.width() - config.ARROW_GAP
        x = max(0, min(w - config.ARROW_GAP - self.arrow.width(), x))
        self.arrow.move(x, max(0, (h - self.arrow.height()) // 2))

    # -- layout ---------------------------------------------------------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        self.snow.setGeometry(0, 0, w, h)
        self.leaves.setGeometry(0, 0, w, h)

        self._panel_box.adjustSize()
        box = self._panel_box.size()
        self._panel_box.move((w - box.width()) // 2, (h - box.height()) // 2)

        self._apply_menu_pos(animate=False)
        self.menu.raise_()
        self.arrow.raise_()

    def paintEvent(self, _event) -> None:
        # Windows passes clicks through fully transparent (alpha=0) pixels of a
        # layered window. Painting an almost invisible fill keeps the whole
        # window hit-testable while "Нажатие сквозь" is off, so clicks cannot
        # reach other apps.
        if self._click_through:
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))

    # -- screen geometry -------------------------------------------------
    def apply_available_geometry(self) -> None:
        """Fit the overlay to the work area so it never covers the taskbar."""
        self._bind_screen()

    def _bind_screen(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        if screen is not self._screen:
            if self._screen is not None:
                for signal in (
                    self._screen.availableGeometryChanged,
                    self._screen.geometryChanged,
                ):
                    try:
                        signal.disconnect(self._on_screen_changed)
                    except TypeError:
                        pass
            self._screen = screen
            screen.availableGeometryChanged.connect(self._on_screen_changed)
            screen.geometryChanged.connect(self._on_screen_changed)
        self._fit_to_work_area(screen)

    def _fit_to_work_area(self, screen) -> None:
        self.setGeometry(screen.availableGeometry())

    def _on_screen_changed(self, *_args) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            self._fit_to_work_area(screen)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._bind_screen()

    @property
    def hwnd(self) -> int:
        return int(self.winId())

    def _on_hover_changed(self, active: bool) -> None:
        if not self._click_through:
            # Click-through off: keep the flag pinned to True (overlay takes clicks).
            self.hover.active = True
            state.hover_flag = True
            winapi.set_click_through(self.hwnd, False)
            return
        winapi.set_click_through(self.hwnd, not active)
        LOGGER.debug("hover_flag=%s", active)

    # -- click-through ---------------------------------------------------
    def enable_click_through(self, enabled: bool) -> None:
        """Toggle whether the hover flag tracks the cursor.

        Enabled (default): the flag follows the cursor as usual. Disabled: the
        overlay ignores the cursor and stays fully interactive (hover_flag True).
        """
        self._click_through = enabled
        self.menu.set_click_through(enabled)
        self.update()  # repaint the hit-test fill
        if enabled:
            active = self.hover.is_over()
            self.hover.active = active
            state.hover_flag = active
            winapi.set_click_through(self.hwnd, not active)
        else:
            self.hover.active = True
            state.hover_flag = True
            winapi.set_click_through(self.hwnd, False)
        LOGGER.info("Нажатие сквозь: %s", "вкл" if enabled else "выкл")

    def toggle_click_through(self) -> None:
        self.enable_click_through(not self._click_through)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("OVERLAY_DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def run() -> int:
    _configure_logging()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)

    window = OverlayWindow()
    window.apply_available_geometry()
    window.show()
    winapi.set_click_through(window.hwnd, True)

    registered: list[int] = []
    hotkey_filter = None
    if winapi.IS_WINDOWS:
        callbacks = {
            winapi.HOTKEY_ID_QUIT: app.quit,
            winapi.HOTKEY_ID_CLICK_THROUGH: window.toggle_click_through,
        }
        hotkey_filter = winapi.HotkeyFilter(callbacks)
        app.installNativeEventFilter(hotkey_filter)
        if winapi.register_hotkey(window.hwnd, winapi.HOTKEY_ID_QUIT, winapi.MOD_CONTROL, winapi.VK_Q):
            registered.append(winapi.HOTKEY_ID_QUIT)
        if winapi.register_hotkey(
            window.hwnd,
            winapi.HOTKEY_ID_CLICK_THROUGH,
            winapi.MOD_CONTROL | winapi.MOD_SHIFT,
            winapi.VK_X,
        ):
            registered.append(winapi.HOTKEY_ID_CLICK_THROUGH)
    LOGGER.info("Overlay started. Ctrl+Q — выход, Ctrl+Shift+X — нажатие сквозь.")

    try:
        return app.exec()
    finally:
        for hotkey_id in registered:
            winapi.unregister_hotkey(window.hwnd, hotkey_id)
        if hotkey_filter is not None:
            app.removeNativeEventFilter(hotkey_filter)
