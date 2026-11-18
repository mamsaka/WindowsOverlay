"""Autumn leaves with their own physics and a hand-drawn look.

The leaves deliberately do not reuse the snow particles. A leaf is light: it
accelerates slowly under gravity and is quickly slowed down by air drag, so it
drifts down instead of falling. Sideways it flutters on its own phase, slowly
turns around its axis (``flip``) and is pushed by a gust of air that follows the
mouse cursor. A leaf that reaches a surface -- the bottom edge or, with the
configured chance, the top edge of a desktop window -- lies down and squashes
against it, staying there as part of a loose drift; a passing gust sweeps it
back into the air. All of that is optional: without "interactive leaves" the
leaves just fly through and leave the screen.

Each leaf is drawn as a vector shape with a colour gradient, a dark outline,
a midrib and side veins. The flip phase scales the shape horizontally, so a
tumbling leaf narrows to an edge and then opens up again mirrored -- the same
trick a real leaf uses when it turns over.

Colours and shapes are defined by the ``_PALETTE`` table below; the numeric
tuning lives in ``overlay/config.py``.
"""

from __future__ import annotations

import logging
import math
import random
from typing import Dict, List, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import QWidget

from . import config, surfaces

LOGGER = logging.getLogger(__name__)

# Warm autumn colours: red, crimson, orange, amber, yellow, gold, brown,
# olive and rust. The first value is the lit side of the leaf, the second the
# shaded side (also used for the outline and veins).
_PALETTE: Tuple[Tuple[str, str], ...] = (
    ("#d24a32", "#7d1f14"),   # red
    ("#b3352c", "#691510"),   # crimson
    ("#e07f28", "#8c3f0e"),   # orange
    ("#e8a82a", "#8a5a0a"),   # amber
    ("#e6c93e", "#8d7413"),   # yellow
    ("#c9a227", "#6d5308"),   # gold
    ("#9c6b32", "#543411"),   # brown
    ("#7f8b33", "#454d18"),   # olive
    ("#b5552c", "#5f2a11"),   # rust
    ("#8c3b25", "#4d180d"),   # maroon
)

_SHAPE_NAMES = ("oval", "round", "maple")

_shape_cache: Dict[str, QPainterPath] = {}
_vein_cache: Dict[str, QPainterPath] = {}
_brush_cache: Dict[int, QBrush] = {}
_edge_cache: Dict[int, QPen] = {}
_vein_pen_cache: Dict[int, QPen] = {}


# -- cached artwork ------------------------------------------------------
def _shape(name: str) -> QPainterPath:
    path = _shape_cache.get(name)
    if path is not None:
        return path

    path = QPainterPath()
    if name == "maple":
        # A five-lobed silhouette sampled from a polar radius and closed as a
        # polygon; at leaf size the many small segments read as a smooth edge.
        segments = 72
        for index in range(segments):
            angle = math.tau * index / segments
            lobe = abs(math.cos(2.5 * angle)) ** 0.65
            radius = 0.58 + 0.48 * lobe
            x = math.sin(angle) * radius * 0.95
            y = -math.cos(angle) * radius
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
    elif name == "round":
        path.moveTo(0.0, -0.92)
        path.cubicTo(0.95, -0.45, 0.88, 0.55, 0.0, 1.0)
        path.cubicTo(-0.88, 0.55, -0.95, -0.45, 0.0, -0.92)
        path.closeSubpath()
    else:  # "oval" -- a pointed leaf, the most common shape
        path.moveTo(0.0, -1.0)
        path.cubicTo(0.62, -0.55, 0.55, 0.5, 0.0, 1.0)
        path.cubicTo(-0.55, 0.5, -0.62, -0.55, 0.0, -1.0)
        path.closeSubpath()

    _shape_cache[name] = path
    return path


def _veins(name: str) -> QPainterPath:
    path = _vein_cache.get(name)
    if path is not None:
        return path

    path = QPainterPath()
    # Stem, then the midrib, then three pairs of side veins. Maple leaves get
    # slightly longer veins because their lobes reach further out.
    reach_scale = 0.85 if name == "maple" else 1.0
    path.moveTo(0.0, 1.26)
    path.lineTo(0.0, 0.95)
    path.moveTo(0.0, 0.95)
    path.lineTo(0.0, -0.88)
    for base_y, reach in ((-0.30, 0.34), (0.14, 0.40), (0.55, 0.30)):
        reach *= reach_scale
        path.moveTo(0.0, base_y)
        path.quadTo(reach * 0.5, base_y + 0.02, reach, base_y - 0.28)
        path.moveTo(0.0, base_y)
        path.quadTo(-reach * 0.5, base_y + 0.02, -reach, base_y - 0.28)
    _vein_cache[name] = path
    return path


def _brush(index: int) -> QBrush:
    brush = _brush_cache.get(index)
    if brush is None:
        light, dark = _PALETTE[index]
        top = QColor(light)
        bottom = QColor(dark)
        top.setAlpha(238)
        bottom.setAlpha(238)
        gradient = QLinearGradient(0.0, -1.0, 0.0, 1.0)
        gradient.setColorAt(0.0, top.lighter(110))
        gradient.setColorAt(0.55, top)
        gradient.setColorAt(1.0, bottom)
        brush = QBrush(gradient)
        _brush_cache[index] = brush
    return brush


def _edge_pen(index: int) -> QPen:
    pen = _edge_cache.get(index)
    if pen is None:
        color = QColor(_PALETTE[index][1])
        color.setAlpha(215)
        pen = QPen(color, 0.055)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        _edge_cache[index] = pen
    return pen


def _vein_pen(index: int) -> QPen:
    pen = _vein_pen_cache.get(index)
    if pen is None:
        color = QColor(_PALETTE[index][1])
        color.setAlpha(180)
        pen = QPen(color, 0.042)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        _vein_pen_cache[index] = pen
    return pen


class _WindowTop:
    """A horizontal strip (a window's top edge) a leaf can land on."""

    __slots__ = ("hwnd", "key", "left", "right", "top", "above")

    def __init__(
        self,
        hwnd: int,
        key: Tuple[int, int, int],
        left: float,
        right: float,
        top: float,
        above: Tuple[Tuple[float, float, float, float], ...],
    ) -> None:
        self.hwnd = hwnd
        self.key = key
        self.left = left
        self.right = right
        self.top = top
        self.above = above


class _Leaf:
    __slots__ = (
        "x", "y", "vx", "vy", "size", "gravity", "angle", "spin", "flip",
        "flip_speed", "phase", "flutter_speed", "sway", "palette", "shape",
        "settled", "cell", "level", "window", "window_key", "land", "surface_y",
        "boost",
    )

    def __init__(
        self,
        x: float,
        y: float,
        wind: float,
        size_scale: float = 1.0,
        fall_scale: float = 1.0,
    ) -> None:
        self.x = x
        self.y = y
        self.size = random.uniform(config.LEAF_SIZE_MIN, config.LEAF_SIZE_MAX) * size_scale
        self.gravity = config.LEAF_GRAVITY * fall_scale * random.uniform(0.8, 1.2)
        self.vx = wind * config.LEAF_WIND_DRIFT * 0.25 + random.uniform(-0.25, 0.25)
        self.vy = random.uniform(0.0, 0.35)
        self.angle = random.uniform(-math.pi, math.pi)
        spin = random.uniform(config.LEAF_SPIN_MIN, config.LEAF_SPIN_MAX)
        self.spin = spin if random.random() < 0.5 else -spin
        self.flip = random.uniform(0.0, math.tau)
        flip = random.uniform(config.LEAF_FLIP_MIN, config.LEAF_FLIP_MAX)
        self.flip_speed = flip if random.random() < 0.5 else -flip
        self.phase = random.uniform(0.0, math.tau)
        self.flutter_speed = random.uniform(
            config.LEAF_SWAY_SPEED_MIN, config.LEAF_SWAY_SPEED_MAX
        )
        self.sway = random.uniform(0.6, 1.4)
        self.palette = random.randrange(len(_PALETTE))
        self.shape = random.choice(_SHAPE_NAMES)
        self.settled = False
        self.cell = -1
        self.level = 0
        self.window = 0
        self.window_key: tuple = ()
        self.land = 1.0
        self.surface_y = 0.0
        self.boost = 1.0


class LeavesCanvas(QWidget):
    """Transparent canvas with tumbling leaves and a cursor breeze."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._enabled = False
        self._leaves: List[_Leaf] = []
        self._settled: List[_Leaf] = []

        self._density = 0.5
        self._wind = 0.2
        self._fall_scale = 1.0
        self._size_scale = 1.0
        self._swirl_scale = 1.0

        # Interactivity: the cursor breeze, the ground drift and window tops.
        # With it off leaves simply fly through and leave the screen.
        self._interactive = True
        self._window_chance = config.LEAF_WINDOW_CHANCE / 100.0
        self._windows: List[_WindowTop] = []
        self._window_wait = 0

        self._spawn_accum = 0.0
        self._cursor = QPointF(0.0, 0.0)
        self._gust = [0.0, 0.0]

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(config.LEAVES_TICK_MS)

    # -- controls -------------------------------------------------------
    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self._leaves.clear()
        self._settled.clear()
        self._windows.clear()
        self._window_wait = 0
        self._spawn_accum = 0.0
        self._gust = [0.0, 0.0]
        if enabled:
            self._cursor = self._cursor_local()
        self.update()

    def set_interactive(self, enabled: bool) -> None:
        """Enable or disable the breeze, the drift and window landings."""
        if enabled == self._interactive:
            return
        self._interactive = enabled
        self._gust = [0.0, 0.0]
        if enabled:
            self._cursor = self._cursor_local()
            self._window_wait = 0
        else:
            self._windows.clear()
            # Leaves that were resting are let go: with interactions off they
            # simply fly down through the bottom edge.
            self._release_settled()

    def set_window_chance(self, chance: float) -> None:
        """0..1 chance that a falling leaf will land on a window's top edge."""
        chance = max(0.0, min(1.0, float(chance)))
        if chance == self._window_chance:
            return
        self._window_chance = chance
        self._window_wait = 0
        if chance <= 0.0:
            self._windows.clear()
            self._release_settled(windows_only=True)
        self.update()

    def set_density(self, density: float) -> None:
        self._density = max(0.0, min(1.0, float(density)))

    def set_wind(self, wind: float) -> None:
        self._wind = max(-1.0, min(1.0, float(wind)))

    def set_fall_scale(self, scale: float) -> None:
        scale = max(0.05, float(scale))
        ratio = scale / self._fall_scale if self._fall_scale else 1.0
        self._fall_scale = scale
        for leaf in self._leaves:
            leaf.gravity = max(0.005, leaf.gravity * ratio)

    def set_size_scale(self, scale: float) -> None:
        scale = max(0.1, float(scale))
        ratio = scale / self._size_scale if self._size_scale else 1.0
        self._size_scale = scale
        for leaf in [*self._leaves, *self._settled]:
            leaf.size = max(1.5, leaf.size * ratio)

    def set_swirl_scale(self, scale: float) -> None:
        self._swirl_scale = max(0.0, float(scale))

    # -- spawn ----------------------------------------------------------
    def _spawn_point(self, w: float, h: float) -> Tuple[float, float]:
        """Leaves enter from the sky, or from the windward edge in strong wind."""
        wind = self._wind
        if wind and random.random() < min(1.0, abs(wind)):
            depth = random.uniform(6.0, config.LEAF_SIDE_SPAWN_DEPTH)
            x = -depth if wind > 0 else w + depth
            return x, random.uniform(-30.0, h * 0.92)
        return random.uniform(0.0, w), random.uniform(-40.0, -6.0)

    def _new_leaf(self) -> _Leaf:
        w = max(1, self.width())
        h = max(1, self.height())
        x, y = self._spawn_point(w, h)
        return _Leaf(x, y, self._wind, self._size_scale, self._fall_scale)

    # -- cursor breeze ---------------------------------------------------
    def _cursor_local(self) -> QPointF:
        point = self.mapFromGlobal(QCursor.pos())
        return QPointF(point.x(), point.y())

    def _update_gust(self) -> None:
        """Turn cursor movement into a short-lived gust of air."""
        position = self._cursor_local()
        dx = position.x() - self._cursor.x()
        dy = position.y() - self._cursor.y()
        self._cursor = position
        distance = math.hypot(dx, dy)
        if distance <= 1.0:
            self._gust[0] *= 0.55
            self._gust[1] *= 0.55
            if abs(self._gust[0]) < 0.05 and abs(self._gust[1]) < 0.05:
                self._gust[0] = 0.0
                self._gust[1] = 0.0
            return
        limit = 13.0
        self._gust[0] = max(-limit, min(limit, dx))
        self._gust[1] = max(-limit, min(limit, dy))

    def _push(self, leaf: _Leaf, cx: float, cy: float) -> float:
        """Apply the gust to a leaf; returns how hard it hit (0..1)."""
        gx, gy = self._gust
        if gx == 0.0 and gy == 0.0:
            return 0.0
        dx = leaf.x - cx
        dy = leaf.y - cy
        distance_sq = dx * dx + dy * dy
        radius = float(config.LEAF_GUST_RADIUS)
        if distance_sq > radius * radius:
            return 0.0
        falloff = 1.0 - math.sqrt(distance_sq) / radius
        force = config.LEAF_GUST_FORCE * falloff
        leaf.vx += gx * force
        leaf.vy += gy * force - falloff * config.LEAF_GUST_LIFT
        direction = 1.0 if leaf.spin >= 0.0 else -1.0
        leaf.spin += direction * falloff * 0.012
        leaf.spin = max(-0.12, min(0.12, leaf.spin))
        return falloff

    def _detach(self, leaf: _Leaf) -> None:
        """Forget the resting place of a leaf (it becomes airborne again)."""
        leaf.settled = False
        leaf.window = 0
        leaf.window_key = ()
        leaf.cell = -1
        leaf.level = 0
        leaf.surface_y = 0.0
        leaf.boost = 1.0

    def _drop_from_surface(self, leaf: _Leaf) -> None:
        """Let go of a leaf whose surface vanished, so it visibly falls.

        Snow keeps its falling speed when a window goes away; a leaf is much
        lighter, so it gets a downward kick and a temporary heavier fall,
        otherwise it would hang in the air for half a minute.
        """
        self._detach(leaf)
        leaf.land = 1.0
        leaf.flip = random.uniform(0.0, math.tau)
        leaf.vy = max(leaf.vy, config.LEAF_DROP_SPEED)
        leaf.boost = config.LEAF_DROP_GRAVITY

    def _release_settled(self, windows_only: bool = False) -> None:
        """Lift resting leaves back into the air, optionally only window ones."""
        if not self._settled:
            return
        released: List[_Leaf] = []
        kept: List[_Leaf] = []
        for leaf in self._settled:
            if windows_only and leaf.window == 0:
                kept.append(leaf)
                continue
            if leaf.window != 0:
                self._drop_from_surface(leaf)
            else:
                self._detach(leaf)
                leaf.land = 1.0
                leaf.flip = random.uniform(0.0, math.tau)
                leaf.vy = max(leaf.vy, 0.25)
            released.append(leaf)
        self._settled = kept
        self._leaves.extend(released)

    def _sweep_settled(self, cx: float, cy: float) -> None:
        if not self._settled:
            return
        # A gentle drift of the cursor only nudges flying leaves; lifting a
        # leaf that already lies somewhere takes a real gust.
        if math.hypot(self._gust[0], self._gust[1]) < 3.0:
            return
        lifted: List[_Leaf] = []
        kept: List[_Leaf] = []
        for leaf in self._settled:
            if self._push(leaf, cx, cy) > 0.0:
                self._detach(leaf)
                leaf.land = 1.0
                leaf.flip = random.uniform(0.0, math.tau)
                leaf.vy = min(leaf.vy, -0.9) - random.uniform(0.0, 0.8)
                lifted.append(leaf)
            else:
                kept.append(leaf)
        if lifted:
            self._settled = kept
            self._leaves.extend(lifted)

    # -- desktop windows -------------------------------------------------
    def _poll_windows(self) -> None:
        if not (self._interactive and self._window_chance > 0.0):
            return
        self._window_wait -= config.LEAVES_TICK_MS
        if self._window_wait > 0:
            return
        self._window_wait = config.SNOW_WINDOW_POLL_MS
        self._sync_windows()

    def _sync_windows(self) -> None:
        """Read the visible window tops and let go of leaves on moved windows."""
        top_level = self.window()
        exclude = int(top_level.winId()) if top_level is not None else 0
        try:
            found = surfaces.list_windows((exclude,))
        except Exception:  # pragma: no cover - defensive
            LOGGER.exception("Не удалось перечислить окна для листьев")
            return

        dpr = self.devicePixelRatioF() or 1.0
        width = float(self.width())
        height = float(self.height())
        limit = max(1, int(config.SNOW_WINDOW_MAX_SURFACES))
        min_width = float(config.SNOW_WINDOW_MIN_WIDTH)

        current: List[_WindowTop] = []
        above: List[Tuple[float, float, float, float]] = []
        for win in found:
            left = win.left / dpr
            top = win.top / dpr
            right = win.right / dpr
            bottom = win.bottom / dpr
            usable = (
                not win.maximized
                and right - left >= min_width
                and bottom - top > 0.0
                and 8.0 <= top <= height - 24.0
                and right > 0.0
                and left < width
                and len(current) < limit
            )
            if usable:
                current.append(
                    _WindowTop(
                        win.hwnd,
                        (round(left), round(top), round(right)),
                        left,
                        right,
                        top,
                        tuple(above),
                    )
                )
            above.append((left, top, right, bottom))

        self._windows = current
        self._prune_window_leaves()

    @staticmethod
    def _edge_hidden(surface: _WindowTop, x: float) -> bool:
        """Whether a higher window covers this point of the top edge."""
        for left, top, right, bottom in surface.above:
            if left <= x < right and top <= surface.top <= bottom:
                return True
        return False

    def _prune_window_leaves(self) -> None:
        if not self._settled:
            return
        current = {surface.hwnd: surface for surface in self._windows}
        kept: List[_Leaf] = []
        released: List[_Leaf] = []
        for leaf in self._settled:
            if leaf.window == 0:
                kept.append(leaf)
                continue
            surface = current.get(leaf.window)
            # Drop the leaf when its window is gone (a Win+D-style desktop
            # peek), was moved/resized, or is now covered by a window above it.
            if (
                surface is None
                or surface.key != leaf.window_key
                or self._edge_hidden(surface, leaf.x)
            ):
                self._drop_from_surface(leaf)
                released.append(leaf)
            else:
                kept.append(leaf)
        if released:
            self._settled = kept
            self._leaves.extend(released)

    def _try_land_on_window(self, leaf: _Leaf, prev_y: float) -> bool:
        if not self._windows or self._window_chance <= 0.0:
            return False
        for surface in self._windows:
            if not (prev_y < surface.top <= leaf.y):
                continue
            if leaf.x <= surface.left + 4.0 or leaf.x >= surface.right - 4.0:
                continue
            if self._edge_hidden(surface, leaf.x):
                continue
            if random.random() >= self._window_chance:
                return False  # this leaf slips past the window
            self._settle_on_window(leaf, surface)
            return True
        return False

    def _settle_on_window(self, leaf: _Leaf, surface: _WindowTop) -> None:
        cell = int(leaf.x // config.LEAF_GROUND_CELL)
        level = sum(
            1
            for other in self._settled
            if other.window == surface.hwnd and other.cell == cell
        )
        leaf.settled = True
        leaf.window = surface.hwnd
        leaf.window_key = surface.key
        leaf.cell = cell
        leaf.level = min(level, config.LEAF_WINDOW_LEVELS - 1)
        leaf.surface_y = surface.top
        leaf.land = 0.0
        leaf.angle = random.uniform(-0.7, 0.7)
        leaf.flip = 0.0
        leaf.vx = 0.0
        leaf.vy = 0.0
        leaf.boost = 1.0
        # Sit a little into the top edge so the leaf looks pressed onto the
        # window rather than hovering above it.
        leaf.y = (
            surface.top
            - leaf.size * 0.38
            - leaf.level * config.LEAF_GROUND_STEP
        )
        self._settled.append(leaf)
        if len(self._settled) > config.LEAF_GROUND_MAX:
            del self._settled[0]

    # -- settling --------------------------------------------------------
    def _settle(self, leaf: _Leaf, ground: float) -> None:
        cell = int(leaf.x // config.LEAF_GROUND_CELL)
        level = 0
        for other in self._settled:
            if other.window == 0 and other.cell == cell:
                level += 1
        leaf.settled = True
        leaf.window = 0
        leaf.window_key = ()
        leaf.cell = cell
        leaf.level = min(level, config.LEAF_GROUND_LEVELS - 1)
        leaf.surface_y = ground
        leaf.x += random.uniform(-2.0, 2.0)
        # Sink a hair into the bottom edge: the overlay ends at the work area,
        # so the lower part is clipped away by the taskbar and the leaf reads
        # as lying on the edge instead of floating over it.
        leaf.y = (
            ground
            - leaf.size * 0.38
            - leaf.level * config.LEAF_GROUND_STEP
        )
        leaf.land = 0.0
        leaf.angle = random.uniform(-0.7, 0.7)
        leaf.flip = 0.0
        leaf.vx = 0.0
        leaf.vy = 0.0
        leaf.boost = 1.0
        self._settled.append(leaf)
        if len(self._settled) > config.LEAF_GROUND_MAX:
            del self._settled[0]

    # -- loop ------------------------------------------------------------
    def _tick(self) -> None:
        if not self._enabled:
            self._gust = [0.0, 0.0]
            return

        width = max(1, self.width())
        height = max(1, self.height())
        self._poll_windows()
        if self._interactive:
            self._update_gust()
            cursor = self._cursor
            self._sweep_settled(cursor.x(), cursor.y())
        else:
            self._gust = [0.0, 0.0]
            cursor = self._cursor

        # Freshly landed leaves squash against their surface for a few frames.
        landing_step = 1.0 / max(1, config.LEAF_LAND_TICKS)
        for leaf in self._settled:
            if leaf.land < 1.0:
                leaf.land = min(1.0, leaf.land + landing_step)

        ground = height - 2.0
        drift = self._wind * config.LEAF_WIND_DRIFT
        swirl = self._swirl_scale

        alive: List[_Leaf] = []
        for leaf in self._leaves:
            leaf.phase += leaf.flutter_speed * swirl
            leaf.vy += leaf.gravity * leaf.boost
            leaf.vy *= config.LEAF_DRAG
            target_vx = drift + math.sin(leaf.phase) * 1.1
            leaf.vx += (target_vx - leaf.vx) * 0.045
            leaf.vx += (
                math.cos(leaf.phase * 0.7) * config.LEAF_SWAY_ACCEL * leaf.sway * swirl
            )
            leaf.vy += math.sin(leaf.phase * 1.6) * 0.004 * leaf.sway
            if self._interactive:
                self._push(leaf, cursor.x(), cursor.y())

            leaf.vx = max(-9.0, min(9.0, leaf.vx))
            leaf.vy = max(-6.0, min(5.0, leaf.vy))
            prev_y = leaf.y
            leaf.x += leaf.vx
            leaf.y += leaf.vy

            # Spin slows slightly while the leaf is edge-on, which reads as air
            # resistance and keeps the tumble from looking mechanical.
            leaf.angle += leaf.spin * (0.6 + 0.4 * abs(math.cos(leaf.flip)))
            leaf.flip += leaf.flip_speed

            if self._interactive:
                if self._try_land_on_window(leaf, prev_y):
                    continue
                if leaf.y >= ground - leaf.size * 0.25:
                    self._settle(leaf, ground)
                    continue
            margin = float(config.LEAF_SIDE_CULL)
            if leaf.x < -margin or leaf.x > width + margin or leaf.y > height + 30.0:
                continue  # gone off the screen for good, the sky sends another one
            alive.append(leaf)
        self._leaves = alive

        # Natural spawner only: the canopy keeps shedding leaves at a
        # density-driven rate. No population cap: leaves that fly away or
        # settle do not hold up the next batch.
        self._spawn_accum += self._density * config.LEAVES_SPAWN_PER_SEC * (
            config.LEAVES_TICK_MS / 1000.0
        )
        while self._spawn_accum >= 1.0:
            self._spawn_accum -= 1.0
            self._leaves.append(self._new_leaf())

        if self._leaves or self._settled:
            self.update()

    # -- painting --------------------------------------------------------
    def _paint_leaf(self, painter: QPainter, leaf: _Leaf) -> None:
        width = self.width()
        height = self.height()
        if leaf.x < -30 or leaf.x > width + 30 or leaf.y < -40 or leaf.y > height + 20:
            return

        shape = _shape(leaf.shape)
        if leaf.settled:
            # A leaf that lies on a surface is seen almost edge-on: squash it
            # vertically. The first frames after landing are flatter still, so
            # the leaf visibly presses ("clips") into the surface and relaxes.
            ease = 1.0 if leaf.land >= 1.0 else 1.0 - (1.0 - leaf.land) ** 3
            flatten = 0.34 + 0.28 * ease
            scale_x = leaf.size * (1.0 + 0.09 * (1.0 - ease))
            scale_y = leaf.size * flatten
        else:
            flip = math.cos(leaf.flip)
            if abs(flip) < 0.08:
                flip = 0.08 if flip >= 0.0 else -0.08
            scale_x = leaf.size * flip
            scale_y = leaf.size

        painter.save()
        if leaf.settled and leaf.window != 0:
            # The part of a window-settled leaf that would hang below the top
            # edge is cut away, so the leaf looks pressed into the frame.
            painter.setClipRect(QRectF(0.0, 0.0, float(width), leaf.surface_y))
        painter.translate(leaf.x, leaf.y)
        painter.rotate(math.degrees(leaf.angle))
        painter.scale(scale_x, scale_y)
        painter.setBrush(_brush(leaf.palette))
        painter.setPen(_edge_pen(leaf.palette))
        painter.drawPath(shape)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(_vein_pen(leaf.palette))
        painter.drawPath(_veins(leaf.shape))
        painter.restore()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # The ground line moved: settled leaves would hang in the air, so the
        # drift starts over on the new bottom edge.
        self._settled.clear()

    def paintEvent(self, _event) -> None:
        if not self._leaves and not self._settled:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for leaf in self._settled:
            self._paint_leaf(painter, leaf)
        for leaf in self._leaves:
            self._paint_leaf(painter, leaf)
