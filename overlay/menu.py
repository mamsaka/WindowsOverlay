"""Right-hand slide-out menu with all snow controls and a click-through toggle."""

from __future__ import annotations

from typing import Callable, Tuple

from PyQt6.QtCore import QLocale, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QDoubleValidator, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from . import config, settings

BLOCK_HEIGHT = 46
ROW_HEIGHT = 28
INPUT_WIDTH = 54


def _fmt_number(value: float) -> str:
    return f"{value:g}"


def _accent(alpha: float = 1.0) -> QColor:
    color = QColor(config.ACCENT_COLOR)
    color.setAlphaF(alpha)
    return color


def _as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _as_int(value: object, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class ToggleSwitch(QAbstractButton):
    """Small iOS-style pill switch."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(46, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        radius = rect.height() / 2

        if self.isChecked():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_accent(0.85))
            p.drawRoundedRect(rect, radius, radius)
        else:
            p.setPen(_accent(0.45))
            p.setBrush(QColor(20, 25, 40, 180))
            p.drawRoundedRect(rect, radius, radius)

        knob = rect.height() - 6
        margin = 3.0
        x = rect.right() - margin - knob if self.isChecked() else rect.left() + margin
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255) if self.isChecked() else QColor(200, 210, 240))
        p.drawEllipse(
            QPointF(x + knob / 2, rect.top() + margin + knob / 2), knob / 2, knob / 2
        )


class CenterSlider(QSlider):
    """Slider that marks its middle as the neutral position."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setFixedHeight(18)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setPen(QPen(QColor(255, 255, 255, 150), 1))
        mid = self.width() // 2
        center = self.height() / 2
        p.drawLine(QPointF(mid, center - 6), QPointF(mid, center + 6))


class NumberField(QLineEdit):
    """Numeric-only input; emits the parsed value as it is typed."""

    valueChanged = pyqtSignal(float)

    def __init__(self, value: float, minimum: float, maximum: float,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("number")
        self.setFixedSize(INPUT_WIDTH, 22)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        validator = QDoubleValidator(minimum, maximum, 3, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        validator.setLocale(QLocale.c())
        self.setValidator(validator)
        self.setText(_fmt_number(value))
        self.textChanged.connect(self._on_text)

    def _on_text(self, text: str) -> None:
        try:
            value = float(text.replace(",", "."))
        except ValueError:
            return
        self.valueChanged.emit(value)

    def value(self) -> float:
        try:
            return float(self.text().replace(",", "."))
        except ValueError:
            return 1.0


class SlideMenu(QFrame):
    """Full-height menu: snow parameters, a click-through switch and scrolling."""

    snowToggled = pyqtSignal(bool)
    interactiveToggled = pyqtSignal(bool)
    clickThroughToggled = pyqtSignal(bool)
    leavesToggled = pyqtSignal(bool)
    densityChanged = pyqtSignal(float)     # 0 .. 1
    windChanged = pyqtSignal(float)        # -1 .. 1
    fallChanged = pyqtSignal(float)        # fall speed multiplier
    swayChanged = pyqtSignal(float)        # sway multiplier
    sizeChanged = pyqtSignal(float)        # flake size multiplier
    grabChanged = pyqtSignal(float)        # grab radius in px
    clumpChanged = pyqtSignal(int)         # flakes stuck to the cursor
    pileChanged = pyqtSignal(int)          # max pile height in flakes
    slopeChanged = pyqtSignal(int)         # crumble slope threshold
    releasedWindChanged = pyqtSignal(float)
    releasedSpeedChanged = pyqtSignal(float)
    releasedSwayChanged = pyqtSignal(float)
    slipToggled = pyqtSignal(bool)
    slipLeashChanged = pyqtSignal(float)
    slipFollowChanged = pyqtSignal(float)
    windowsToggled = pyqtSignal(bool)
    windowPileChanged = pyqtSignal(int)
    windowSlopeChanged = pyqtSignal(int)
    leafDensityChanged = pyqtSignal(float)  # 0 .. 1
    leafWindChanged = pyqtSignal(float)     # -1 .. 1
    leafSpeedChanged = pyqtSignal(float)    # fall speed multiplier
    leafSizeChanged = pyqtSignal(float)     # leaf size multiplier
    leafSwirlChanged = pyqtSignal(float)    # flutter intensity multiplier
    leafInteractiveToggled = pyqtSignal(bool)
    leafWindowChanceChanged = pyqtSignal(float)  # 0 .. 1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("slide_menu")
        self.setFixedWidth(config.MENU_WIDTH)
        self.setStyleSheet(
            """
            #slide_menu {
                background: rgba(14, 18, 32, 236);
                border: 1px solid rgba(130, 150, 255, 0.35);
                border-radius: 12px;
            }
            #slide_menu QScrollArea { background: transparent; border: none; }
            #slide_menu QScrollArea > QWidget > QWidget { background: transparent; }
            #content { background: transparent; }
            QLabel { color: %(text)s; background: transparent; }
            QLabel#title { font-size: 15px; font-weight: 600; }
            QLabel#caption { font-size: 11px; color: rgba(223, 228, 255, 0.55); }
            QLabel#mult { color: rgba(223, 228, 255, 0.40); font-size: 14px; }
            QLineEdit#number {
                background: rgba(130, 150, 255, 0.10);
                border: 1px solid rgba(130, 150, 255, 0.30);
                border-radius: 6px;
                color: #dfe4ff;
                padding: 1px 4px;
                selection-background-color: rgba(159, 176, 255, 0.45);
            }
            QLineEdit#number:focus { border: 1px solid rgba(159, 176, 255, 0.85); }
            QFrame#separator { background: rgba(130, 150, 255, 0.25); border: none; }
            QLabel#section { font-size: 12px; font-weight: 600; color: rgba(223, 228, 255, 0.75); }
            QPushButton#reset {
                background: rgba(130, 150, 255, 0.12);
                border: 1px solid rgba(130, 150, 255, 0.30);
                border-radius: 8px;
                color: #dfe4ff;
                padding: 6px;
            }
            QPushButton#reset:hover { background: rgba(130, 150, 255, 0.22); }
            QSlider::groove:horizontal {
                height: 4px; border-radius: 2px;
                background: rgba(130, 150, 255, 0.18);
            }
            QSlider::sub-page:horizontal { background: rgba(159, 176, 255, 0.75); border-radius: 2px; }
            QSlider#wind::sub-page:horizontal { background: transparent; }
            QSlider::add-page:horizontal { background: rgba(130, 150, 255, 0.18); border-radius: 2px; }
            QSlider::handle:horizontal {
                width: 12px; height: 12px; margin: -5px 0;
                border-radius: 6px;
                background: #dfe4ff;
                border: 1px solid #9fb0ff;
            }
            QScrollBar:vertical {
                background: transparent; width: 6px; margin: 4px 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(130, 150, 255, 0.40); border-radius: 3px; min-height: 24px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
            """
            % {"text": config.TEXT_COLOR}
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)

        content = QWidget()
        content.setObjectName("content")
        self.scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(12)

        snow_toggle = self._make_toggle("", "snow")
        self.toggle = snow_toggle
        root.addWidget(self._make_title("Снег", snow_toggle))

        self.density_block, self.density_slider, _ = self._make_block(
            "Плотность", "реже … чаще", 0, 100, 50, lambda v: f"{v}%"
        )
        self.wind_block, self.wind_slider, _ = self._make_block(
            "Ветер", "влево … вправо", -100, 100, 0, lambda v: f"{v}%", center=True
        )
        self.fall_block, self.fall_slider, _ = self._make_block(
            "Скорость", "скорость падения", 10, 300, 100, lambda v: f"{v}%"
        )
        self.sway_block, self.sway_slider, _ = self._make_block(
            "Качание", "амплитуда", 0, 200, 100, lambda v: f"{v}%"
        )
        self.size_block, self.size_slider, _ = self._make_block(
            "Размер", "величина снежинок", 50, 200, 100, lambda v: f"{v}%"
        )
        self.interactive_block, self.interactive_toggle = self._make_toggle_row(
            "Интерактивный снег"
        )
        self.grab_block, self.grab_slider, _ = self._make_block(
            "Радиус захвата", "мышью", 2, 80, config.SNOW_GRAB_RADIUS, lambda v: f"{v} px"
        )
        self.clump_block, self.clump_slider, _ = self._make_block(
            "Ком", "снежинок у курсора", 1, 60, config.SNOW_CLUMP_MAX, lambda v: f"{v}"
        )
        self.pile_block, self.pile_slider, _ = self._make_block(
            "Высота вала", "снежинок в столбике", 1, 40, config.SNOW_PILE_MAX, lambda v: f"{v}"
        )
        self.slope_block, self.slope_slider, _ = self._make_block(
            "Осыпание", "перепад для обвала", 1, 10, config.SNOW_PILE_SLOPE, lambda v: f"{v}"
        )

        self.released_block, self.released_wind, self.released_speed, self.released_sway = (
            self._make_released_block()
        )

        self.slip_block, self.slip_toggle = self._make_toggle_row("Выпадение из хватки")
        self.slip_toggle.setChecked(True)  # on by default
        self.leash_block, self.leash_slider, _ = self._make_block(
            "Поводок", "насколько может отстать снежинка", 10, 200,
            int(config.SNOW_CLUMP_LEASH), lambda v: f"{v} px",
        )
        self.follow_block, self.follow_slider, _ = self._make_block(
            "Следование", "скорость догона курсора", 10, 100,
            int(round(config.SNOW_FOLLOW_LERP * 100)), lambda v: f"{v}%",
        )

        self.windows_block, self.windows_toggle = self._make_toggle_row("Сбор на окнах")
        self.window_pile_block, self.window_pile_slider, _ = self._make_block(
            "Вал на окнах", "снежинок в столбике", 1, 10,
            config.SNOW_WINDOW_PILE_MAX, lambda v: f"{v}",
        )
        self.window_slope_block, self.window_slope_slider, _ = self._make_block(
            "Осыпание на окнах", "перепад для обвала с края", 1, 10,
            config.SNOW_WINDOW_PILE_SLOPE, lambda v: f"{v}",
        )

        self.leaves_toggle = self._make_toggle("", "leaves")
        self.leaves_title_block = self._make_title("Осенние листья", self.leaves_toggle)
        self.leaf_density_block, self.leaf_density_slider, _ = self._make_block(
            "Плотность листвы", "реже … чаще", 0, 100, 50, lambda v: f"{v}%"
        )
        self.leaf_wind_block, self.leaf_wind_slider, _ = self._make_block(
            "Ветер листвы", "влево … вправо", -100, 100, 20, lambda v: f"{v}%",
            center=True,
        )
        self.leaf_speed_block, self.leaf_speed_slider, _ = self._make_block(
            "Скорость листвы", "скорость падения", 10, 300, 100, lambda v: f"{v}%"
        )
        self.leaf_size_block, self.leaf_size_slider, _ = self._make_block(
            "Размер листвы", "величина листьев", 50, 250, 100, lambda v: f"{v}%"
        )
        self.leaf_swirl_block, self.leaf_swirl_slider, _ = self._make_block(
            "Кружение", "качание и кувыркание", 0, 200, 100, lambda v: f"{v}%"
        )
        self.leaf_interactive_block, self.leaf_interactive_toggle = self._make_toggle_row(
            "Интерактивные листья"
        )
        self.leaf_interactive_toggle.setChecked(True)  # breeze and landings on
        self.leaf_window_block, self.leaf_window_slider, _ = self._make_block(
            "Приземление на окна", "шанс лечь на верхнюю кромку окна", 0, 100,
            config.LEAF_WINDOW_CHANCE, lambda v: f"{v}%",
        )

        self._snow_blocks = (
            self.density_block,
            self.wind_block,
            self.fall_block,
            self.sway_block,
            self.size_block,
        )
        self._pile_blocks = (
            self.grab_block,
            self.clump_block,
            self.pile_block,
            self.slope_block,
            self.released_block,
            self.slip_block,
        )
        self._slip_blocks = (
            self.leash_block,
            self.follow_block,
        )
        self._window_blocks = (
            self.window_pile_block,
            self.window_slope_block,
        )
        self._leaf_blocks = (
            self.leaf_density_block,
            self.leaf_wind_block,
            self.leaf_speed_block,
            self.leaf_size_block,
            self.leaf_swirl_block,
        )

        for block in self._snow_blocks:
            root.addWidget(block)
        root.addWidget(self.interactive_block)
        for block in self._pile_blocks:
            root.addWidget(block)
        for block in self._slip_blocks:
            root.addWidget(block)
        root.addWidget(self.windows_block)
        for block in self._window_blocks:
            root.addWidget(block)

        root.addWidget(self._make_separator())
        root.addWidget(self.leaves_title_block)
        for block in self._leaf_blocks:
            root.addWidget(block)
        root.addWidget(self.leaf_interactive_block)
        root.addWidget(self.leaf_window_block)

        root.addWidget(self._make_separator())
        self.functional_title = QLabel("Функциональные настройки")
        self.functional_title.setObjectName("section")
        root.addWidget(self.functional_title)
        self.click_through_block, self.click_through_toggle = self._make_toggle_row(
            "Нажатие сквозь"
        )
        self.click_through_toggle.setChecked(True)  # on by default
        root.addWidget(self.click_through_block)

        self.reset_button = QPushButton("Восстановить по умолчанию")
        self.reset_button.setObjectName("reset")
        self.reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_button.clicked.connect(self.reset_defaults)
        root.addWidget(self.reset_button)
        root.addStretch(1)

        self.toggle.toggled.connect(self._on_snow_toggled)
        self.interactive_toggle.toggled.connect(self._on_interactive_toggled)
        self.click_through_toggle.toggled.connect(self.clickThroughToggled.emit)
        self.density_slider.valueChanged.connect(lambda v: self.densityChanged.emit(v / 100.0))
        self.wind_slider.valueChanged.connect(lambda v: self.windChanged.emit(v / 100.0))
        self.fall_slider.valueChanged.connect(lambda v: self.fallChanged.emit(v / 100.0))
        self.sway_slider.valueChanged.connect(lambda v: self.swayChanged.emit(v / 100.0))
        self.size_slider.valueChanged.connect(lambda v: self.sizeChanged.emit(v / 100.0))
        self.grab_slider.valueChanged.connect(lambda v: self.grabChanged.emit(float(v)))
        self.clump_slider.valueChanged.connect(self.clumpChanged.emit)
        self.pile_slider.valueChanged.connect(self.pileChanged.emit)
        self.slope_slider.valueChanged.connect(self.slopeChanged.emit)
        self.released_wind.valueChanged.connect(self.releasedWindChanged.emit)
        self.released_speed.valueChanged.connect(self.releasedSpeedChanged.emit)
        self.released_sway.valueChanged.connect(self.releasedSwayChanged.emit)
        self.slip_toggle.toggled.connect(self._on_slip_toggled)
        self.leash_slider.valueChanged.connect(lambda v: self.slipLeashChanged.emit(float(v)))
        self.follow_slider.valueChanged.connect(lambda v: self.slipFollowChanged.emit(v / 100.0))
        self.windows_toggle.toggled.connect(self._on_windows_toggled)
        self.window_pile_slider.valueChanged.connect(self.windowPileChanged.emit)
        self.window_slope_slider.valueChanged.connect(self.windowSlopeChanged.emit)
        self.leaves_toggle.toggled.connect(self._on_leaves_toggled)
        self.leaf_density_slider.valueChanged.connect(
            lambda v: self.leafDensityChanged.emit(v / 100.0)
        )
        self.leaf_wind_slider.valueChanged.connect(
            lambda v: self.leafWindChanged.emit(v / 100.0)
        )
        self.leaf_speed_slider.valueChanged.connect(
            lambda v: self.leafSpeedChanged.emit(v / 100.0)
        )
        self.leaf_size_slider.valueChanged.connect(
            lambda v: self.leafSizeChanged.emit(v / 100.0)
        )
        self.leaf_swirl_slider.valueChanged.connect(
            lambda v: self.leafSwirlChanged.emit(v / 100.0)
        )
        self.leaf_interactive_toggle.toggled.connect(self._on_leaf_interactive_toggled)
        self.leaf_window_slider.valueChanged.connect(
            lambda v: self.leafWindowChanceChanged.emit(v / 100.0)
        )

        self._loading = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._save_settings)
        for signal in (
            self.toggle.toggled,
            self.interactive_toggle.toggled,
            self.density_slider.valueChanged,
            self.wind_slider.valueChanged,
            self.fall_slider.valueChanged,
            self.sway_slider.valueChanged,
            self.size_slider.valueChanged,
            self.grab_slider.valueChanged,
            self.clump_slider.valueChanged,
            self.pile_slider.valueChanged,
            self.slope_slider.valueChanged,
            self.released_wind.valueChanged,
            self.released_speed.valueChanged,
            self.released_sway.valueChanged,
            self.slip_toggle.toggled,
            self.leash_slider.valueChanged,
            self.follow_slider.valueChanged,
            self.windows_toggle.toggled,
            self.window_pile_slider.valueChanged,
            self.window_slope_slider.valueChanged,
            self.leaves_toggle.toggled,
            self.leaf_density_slider.valueChanged,
            self.leaf_wind_slider.valueChanged,
            self.leaf_speed_slider.valueChanged,
            self.leaf_size_slider.valueChanged,
            self.leaf_swirl_slider.valueChanged,
            self.leaf_interactive_toggle.toggled,
            self.leaf_window_slider.valueChanged,
        ):
            signal.connect(self._schedule_save)

        self._apply_visibility()

    # -- builders --------------------------------------------------------
    def _make_title(self, text: str, toggle: ToggleSwitch) -> QWidget:
        block = QWidget()
        block.setFixedHeight(ROW_HEIGHT)
        row = QHBoxLayout(block)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        label = QLabel(text)
        label.setObjectName("title")
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(toggle)
        return block

    def _make_toggle(self, text: str, name: str) -> ToggleSwitch:
        toggle = ToggleSwitch()
        toggle.setObjectName(name)
        return toggle

    def _make_toggle_row(self, text: str) -> Tuple[QWidget, ToggleSwitch]:
        block = QWidget()
        block.setFixedHeight(ROW_HEIGHT)
        row = QHBoxLayout(block)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        label = QLabel(text)
        toggle = ToggleSwitch()
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(toggle)
        return block, toggle

    def _make_separator(self) -> QFrame:
        line = QFrame()
        line.setObjectName("separator")
        line.setFixedHeight(1)
        return line

    def _make_block(
        self,
        title: str,
        caption: str,
        minimum: int,
        maximum: int,
        value: int,
        fmt: Callable[[int], str],
        center: bool = False,
    ) -> Tuple[QWidget, QSlider, QLabel]:
        block = QWidget()
        block.setFixedHeight(BLOCK_HEIGHT)
        box = QVBoxLayout(block)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel(title)
        label.setToolTip(caption)
        value_label = QLabel(fmt(value))
        value_label.setObjectName("caption")
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(value_label)
        box.addLayout(row)

        slider = CenterSlider() if center else QSlider(Qt.Orientation.Horizontal)
        slider.setFixedHeight(18)
        if center:
            slider.setObjectName("wind")
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.setCursor(Qt.CursorShape.PointingHandCursor)
        slider.valueChanged.connect(lambda v, lbl=value_label, f=fmt: lbl.setText(f(v)))
        box.addWidget(slider)
        return block, slider, value_label

    def _make_released_block(self) -> Tuple[QWidget, NumberField, NumberField, NumberField]:
        block = QWidget()
        box = QVBoxLayout(block)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)

        header = QLabel("Отпущенный снег")
        header.setObjectName("caption")
        box.addWidget(header)

        wind = self._make_mult_row(box, "Ветер", config.SNOW_RELEASED_WIND)
        speed = self._make_mult_row(box, "Скорость", config.SNOW_RELEASED_SPEED)
        sway = self._make_mult_row(box, "Качание", config.SNOW_RELEASED_SWAY)
        return block, wind, speed, sway

    @staticmethod
    def _make_mult_row(box: QVBoxLayout, title: str, value: float) -> NumberField:
        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel(title)
        field = NumberField(value, 0.0, 99.0)
        times = QLabel("×")
        times.setObjectName("mult")
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(field)
        row.addWidget(times)
        box.addLayout(row)
        return field

    # -- visibility ------------------------------------------------------
    def _apply_visibility(self) -> None:
        snow_on = self.toggle.isChecked()
        interactive_on = snow_on and self.interactive_toggle.isChecked()
        windows_on = interactive_on and self.windows_toggle.isChecked()
        slip_on = interactive_on and self.slip_toggle.isChecked()

        self.interactive_block.setVisible(snow_on)
        for block in self._snow_blocks:
            block.setVisible(snow_on)
        for block in self._pile_blocks:
            block.setVisible(interactive_on)
        for block in self._slip_blocks:
            block.setVisible(slip_on)
        self.windows_block.setVisible(interactive_on)
        for block in self._window_blocks:
            block.setVisible(windows_on)

        leaves_on = self.leaves_toggle.isChecked()
        for block in self._leaf_blocks:
            block.setVisible(leaves_on)
        self.leaf_interactive_block.setVisible(leaves_on)
        self.leaf_window_block.setVisible(
            leaves_on and self.leaf_interactive_toggle.isChecked()
        )

    def _on_snow_toggled(self, checked: bool) -> None:
        self._apply_visibility()
        self.snowToggled.emit(checked)

    def _on_interactive_toggled(self, checked: bool) -> None:
        self._apply_visibility()
        self.interactiveToggled.emit(checked)

    def _on_windows_toggled(self, checked: bool) -> None:
        self._apply_visibility()
        self.windowsToggled.emit(checked)

    def _on_slip_toggled(self, checked: bool) -> None:
        self._apply_visibility()
        self.slipToggled.emit(checked)

    def _on_leaves_toggled(self, checked: bool) -> None:
        self._apply_visibility()
        self.leavesToggled.emit(checked)

    def _on_leaf_interactive_toggled(self, checked: bool) -> None:
        self._apply_visibility()
        self.leafInteractiveToggled.emit(checked)

    # -- persistence -----------------------------------------------------
    def _schedule_save(self, *_args) -> None:
        if not self._loading:
            self._save_timer.start()

    def _save_settings(self) -> None:
        if self._loading:
            return
        settings.save(
            {
                "snow_enabled": "1" if self.toggle.isChecked() else "0",
                "interactive": "1" if self.interactive_toggle.isChecked() else "0",
                "density": self.density_slider.value(),
                "wind": self.wind_slider.value(),
                "fall": self.fall_slider.value(),
                "sway": self.sway_slider.value(),
                "size": self.size_slider.value(),
                "grab": self.grab_slider.value(),
                "clump": self.clump_slider.value(),
                "pile": self.pile_slider.value(),
                "slope": self.slope_slider.value(),
                "released_wind": _fmt_number(self.released_wind.value()),
                "released_speed": _fmt_number(self.released_speed.value()),
                "released_sway": _fmt_number(self.released_sway.value()),
                "slip": "1" if self.slip_toggle.isChecked() else "0",
                "leash": self.leash_slider.value(),
                "follow": self.follow_slider.value(),
                "windows": "1" if self.windows_toggle.isChecked() else "0",
                "window_pile": self.window_pile_slider.value(),
                "window_slope": self.window_slope_slider.value(),
                "leaves": "1" if self.leaves_toggle.isChecked() else "0",
                "leaf_density": self.leaf_density_slider.value(),
                "leaf_wind": self.leaf_wind_slider.value(),
                "leaf_speed": self.leaf_speed_slider.value(),
                "leaf_size": self.leaf_size_slider.value(),
                "leaf_swirl": self.leaf_swirl_slider.value(),
                "leaf_interactive": "1" if self.leaf_interactive_toggle.isChecked() else "0",
                "leaf_window": self.leaf_window_slider.value(),
            }
        )

    def load_settings(self) -> None:
        data = settings.load()
        if not data:
            return
        self._loading = True
        try:
            self.toggle.setChecked(_as_bool(data.get("snow_enabled"), self.toggle.isChecked()))
            self.interactive_toggle.setChecked(
                _as_bool(data.get("interactive"), self.interactive_toggle.isChecked())
            )
            self.density_slider.setValue(_as_int(data.get("density"), self.density_slider.value()))
            self.wind_slider.setValue(_as_int(data.get("wind"), self.wind_slider.value()))
            self.fall_slider.setValue(_as_int(data.get("fall"), self.fall_slider.value()))
            self.sway_slider.setValue(_as_int(data.get("sway"), self.sway_slider.value()))
            self.size_slider.setValue(_as_int(data.get("size"), self.size_slider.value()))
            self.grab_slider.setValue(_as_int(data.get("grab"), self.grab_slider.value()))
            self.clump_slider.setValue(_as_int(data.get("clump"), self.clump_slider.value()))
            self.pile_slider.setValue(_as_int(data.get("pile"), self.pile_slider.value()))
            self.slope_slider.setValue(_as_int(data.get("slope"), self.slope_slider.value()))
            self.released_wind.setText(
                _fmt_number(_as_float(data.get("released_wind"), self.released_wind.value()))
            )
            self.released_speed.setText(
                _fmt_number(_as_float(data.get("released_speed"), self.released_speed.value()))
            )
            self.released_sway.setText(
                _fmt_number(_as_float(data.get("released_sway"), self.released_sway.value()))
            )
            self.slip_toggle.setChecked(_as_bool(data.get("slip"), self.slip_toggle.isChecked()))
            self.leash_slider.setValue(_as_int(data.get("leash"), self.leash_slider.value()))
            self.follow_slider.setValue(_as_int(data.get("follow"), self.follow_slider.value()))
            self.windows_toggle.setChecked(
                _as_bool(data.get("windows"), self.windows_toggle.isChecked())
            )
            self.window_pile_slider.setValue(
                _as_int(data.get("window_pile"), self.window_pile_slider.value())
            )
            self.window_slope_slider.setValue(
                _as_int(data.get("window_slope"), self.window_slope_slider.value())
            )
            self.leaves_toggle.setChecked(
                _as_bool(data.get("leaves"), self.leaves_toggle.isChecked())
            )
            self.leaf_density_slider.setValue(
                _as_int(data.get("leaf_density"), self.leaf_density_slider.value())
            )
            self.leaf_wind_slider.setValue(
                _as_int(data.get("leaf_wind"), self.leaf_wind_slider.value())
            )
            self.leaf_speed_slider.setValue(
                _as_int(data.get("leaf_speed"), self.leaf_speed_slider.value())
            )
            self.leaf_size_slider.setValue(
                _as_int(data.get("leaf_size"), self.leaf_size_slider.value())
            )
            self.leaf_swirl_slider.setValue(
                _as_int(data.get("leaf_swirl"), self.leaf_swirl_slider.value())
            )
            self.leaf_interactive_toggle.setChecked(
                _as_bool(
                    data.get("leaf_interactive"),
                    self.leaf_interactive_toggle.isChecked(),
                )
            )
            self.leaf_window_slider.setValue(
                _as_int(data.get("leaf_window"), self.leaf_window_slider.value())
            )
        finally:
            self._loading = False
            self._apply_visibility()

    def reset_defaults(self) -> None:
        self._loading = True
        try:
            self.toggle.setChecked(False)
            self.interactive_toggle.setChecked(False)
            self.density_slider.setValue(50)
            self.wind_slider.setValue(0)
            self.fall_slider.setValue(100)
            self.sway_slider.setValue(100)
            self.size_slider.setValue(100)
            self.grab_slider.setValue(int(config.SNOW_GRAB_RADIUS))
            self.clump_slider.setValue(config.SNOW_CLUMP_MAX)
            self.pile_slider.setValue(config.SNOW_PILE_MAX)
            self.slope_slider.setValue(config.SNOW_PILE_SLOPE)
            self.released_wind.setText(_fmt_number(config.SNOW_RELEASED_WIND))
            self.released_speed.setText(_fmt_number(config.SNOW_RELEASED_SPEED))
            self.released_sway.setText(_fmt_number(config.SNOW_RELEASED_SWAY))
            self.slip_toggle.setChecked(True)
            self.leash_slider.setValue(int(config.SNOW_CLUMP_LEASH))
            self.follow_slider.setValue(int(round(config.SNOW_FOLLOW_LERP * 100)))
            self.windows_toggle.setChecked(False)
            self.window_pile_slider.setValue(config.SNOW_WINDOW_PILE_MAX)
            self.window_slope_slider.setValue(config.SNOW_WINDOW_PILE_SLOPE)
            self.leaves_toggle.setChecked(False)
            self.leaf_density_slider.setValue(50)
            self.leaf_wind_slider.setValue(20)
            self.leaf_speed_slider.setValue(100)
            self.leaf_size_slider.setValue(100)
            self.leaf_swirl_slider.setValue(100)
            self.leaf_interactive_toggle.setChecked(True)
            self.leaf_window_slider.setValue(config.LEAF_WINDOW_CHANCE)
            self.click_through_toggle.setChecked(True)
        finally:
            self._loading = False
            self._apply_visibility()
        self._save_settings()

    # -- state -----------------------------------------------------------
    @property
    def snow_enabled(self) -> bool:
        return self.toggle.isChecked()

    def set_click_through(self, enabled: bool) -> None:
        if self.click_through_toggle.isChecked() != enabled:
            self.click_through_toggle.setChecked(enabled)
