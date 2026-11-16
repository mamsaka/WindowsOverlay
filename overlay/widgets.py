"""Overlay widgets: the clickable arrow and HTML panels."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QWidget

from . import config


def _accent(alpha: float) -> QColor:
    color = QColor(config.ACCENT_COLOR)
    color.setAlphaF(alpha)
    return color


class ArrowButton(QWidget):
    """Round handle whose chevron points at the slide-out menu."""

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(config.ARROW_SIZE, config.ARROW_SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False
        self._open = False

    def set_open(self, is_open: bool) -> None:
        self._open = is_open
        self.update()

    def enterEvent(self, _event) -> None:
        self._hovered = True
        self.update()

    def leaveEvent(self, _event) -> None:
        self._hovered = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        active = self._hovered or self._open
        p.setPen(QPen(_accent(0.9 if active else 0.5), 1))
        p.setBrush(QColor(20, 25, 40, 220 if active else 153))
        p.drawEllipse(rect)

        # Closed: chevron points left; open: points right (towards the menu).
        direction = 1 if self._open else -1
        c = rect.center()
        p.setPen(
            QPen(
                QColor(config.ACCENT_COLOR),
                2,
                cap=Qt.PenCapStyle.RoundCap,
                join=Qt.PenJoinStyle.RoundJoin,
            )
        )
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(
            [
                QPointF(c.x() - 3 * direction, c.y() - 6),
                QPointF(c.x() + 3 * direction, c.y()),
                QPointF(c.x() - 3 * direction, c.y() + 6),
            ]
        )


class HtmlPanel(QFrame):
    """Bordered panel hosting a QWebEngineView."""

    def __init__(self, panel_id: str, cfg: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(panel_id)

        width, height = cfg.get("size", (300, 200))
        self.setFixedSize(width, height)

        bg = QColor(cfg.get("bg", "#2b2b2b"))
        if not bg.isValid():
            bg = QColor("#2b2b2b")
        border = QColor(cfg.get("border", "#555555"))
        if not border.isValid():
            border = QColor("#555555")

        self.setStyleSheet(
            f"#{panel_id} {{ background: {bg.name()}; border: 1px solid {border.name()};"
            " border-radius: 8px; }"
        )

        self.view = QWebEngineView(self)
        self.view.page().setBackgroundColor(Qt.GlobalColor.transparent)
        self.view.setHtml(cfg.get("html", config.EMPTY_HTML), QUrl("about:blank"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.view)
