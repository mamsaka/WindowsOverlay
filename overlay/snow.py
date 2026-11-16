"""Snowfall, an optional interactive mode, and a crumbling snow pile.

Falling flakes land on top of a column-based pile along the bottom edge (the
taskbar boundary). Piled flakes are real particles too: they can be picked up
with a held mouse button, and a column that is too much taller than a
neighbour topples into it until the pile is stable.

Most numeric behaviour is adjustable at runtime through the ``set_*`` methods
(defaults live in ``overlay/config.py`` and are exposed in the menu).
"""

from __future__ import annotations

import math
import random
from typing import List, Optional

from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QPainter, QPixmap
from PyQt6.QtWidgets import QWidget

from . import config, winapi


class _Flake:
    __slots__ = (
        "x", "y", "radius", "fall", "phase", "sway_speed", "sway_amp",
        "slot", "through", "released", "blocked",
    )

    def __init__(
        self,
        x: float,
        y: float,
        fall_scale: float = 1.0,
        radius_scale: float = 1.0,
        sway_scale: float = 1.0,
    ) -> None:
        self.x = x
        self.y = y
        self.radius = random.uniform(config.SNOW_RADIUS_MIN, config.SNOW_RADIUS_MAX) * radius_scale
        self.fall = random.uniform(config.SNOW_FALL_MIN, config.SNOW_FALL_MAX) * fall_scale
        self.phase = random.uniform(0.0, math.tau)
        self.sway_speed = (
            random.uniform(config.SNOW_SWAY_SPEED_MIN, config.SNOW_SWAY_SPEED_MAX) * sway_scale
        )
        self.sway_amp = random.uniform(0.35, 1.0) * config.SNOW_SWAY_AMPLITUDE * sway_scale
        self.slot = -1
        self.through = False
        self.released = False
        self.blocked = False

    def fall_speed(self) -> float:
        return self.fall * (config.SNOW_RELEASED_SPEED if self.released else 1.0)

    def wind_scale(self) -> float:
        return config.SNOW_RELEASED_WIND if self.released else 1.0

    def sway_scale(self) -> float:
        return config.SNOW_RELEASED_SWAY if self.released else 1.0


class SnowCanvas(QWidget):
    """Transparent, click-through widget that draws falling snow.

    ``wind`` is -1 (full left) .. 0 (calm) .. 1 (full right) and ``density``
    is 0 (none) .. 1 (heaviest). Both default to the middle in the menu.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._flakes: List[_Flake] = []
        self._attached: List[_Flake] = []
        self._columns: List[List[_Flake]] = [[]]

        self._enabled = False
        self._interactive = False
        self._wind = 0.0
        self._density = 0.5

        # Runtime-adjustable parameters (menu-controlled).
        self._fall_scale = 1.0
        self._sway_scale = 1.0
        self._size_scale = 1.0
        self._grab_radius = float(config.SNOW_GRAB_RADIUS)
        self._pile_max = config.SNOW_PILE_MAX
        self._pile_slope = config.SNOW_PILE_SLOPE
        self._clump_max = config.SNOW_CLUMP_MAX
        self._clump_radius = float(config.SNOW_CLUMP_RADIUS)
        self._slot_offsets: List[tuple[float, float]] = []
        self._slot_used: List[bool] = []
        self._spawn_accum = 0.0
        self._was_held = False
        self._build_clump_slots()

        self._pile_pixmap: Optional[QPixmap] = None
        self._pile_dirty = True

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(config.SNOW_TICK_MS)

    # -- controls -------------------------------------------------------
    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if not enabled:
            self._flakes.clear()
            self._attached.clear()
            self._clear_pile()
            self.update()
        else:
            self._fill_pool()

    def set_wind(self, wind: float) -> None:
        self._wind = max(-1.0, min(1.0, wind))

    def set_density(self, density: float) -> None:
        self._density = max(0.0, min(1.0, density))
        if self._enabled:
            self._fill_pool()

    def set_interactive(self, enabled: bool) -> None:
        self._interactive = enabled
        if not enabled:
            self._release_attached()
            self._clear_pile()
            self.update()

    def set_fall_scale(self, scale: float) -> None:
        scale = max(0.05, scale)
        ratio = scale / self._fall_scale if self._fall_scale else 1.0
        self._fall_scale = scale
        for flake in self._flakes:
            flake.fall = max(0.1, flake.fall * ratio)

    def set_sway_scale(self, scale: float) -> None:
        scale = max(0.0, scale)
        ratio = scale / self._sway_scale if self._sway_scale else 1.0
        self._sway_scale = scale
        for flake in self._flakes:
            flake.sway_amp *= ratio
            flake.sway_speed *= ratio

    def set_size_scale(self, scale: float) -> None:
        scale = max(0.1, scale)
        ratio = scale / self._size_scale if self._size_scale else 1.0
        self._size_scale = scale
        for flake in self._flakes:
            flake.radius = max(0.4, flake.radius * ratio)

    def set_grab_radius(self, radius: float) -> None:
        self._grab_radius = max(1.0, radius)

    def set_pile_max(self, maximum: int) -> None:
        self._pile_max = max(1, int(maximum))
        for column in range(len(self._columns)):
            while len(self._columns[column]) > self._pile_max:
                self._columns[column].pop()  # excess is discarded
        self._pile_dirty = True

    def set_pile_slope(self, slope: int) -> None:
        self._pile_slope = max(1, int(slope))

    def set_clump_max(self, maximum: int) -> None:
        self._clump_max = max(1, int(maximum))
        while len(self._attached) > self._clump_max:
            flake = self._attached.pop()
            flake.slot = -1
            self._flakes.append(flake)
        self._build_clump_slots()
        for index, flake in enumerate(self._attached):
            flake.slot = index
            self._slot_used[index] = True

    def set_clump_radius(self, radius: float) -> None:
        self._clump_radius = max(4.0, float(radius))
        self._build_clump_slots()
        for flake in self._attached:
            if 0 <= flake.slot < len(self._slot_used):
                self._slot_used[flake.slot] = True

    def set_released_wind(self, scale: float) -> None:
        config.SNOW_RELEASED_WIND = max(0.0, float(scale))

    def set_released_speed(self, scale: float) -> None:
        config.SNOW_RELEASED_SPEED = max(0.0, float(scale))

    def set_released_sway(self, scale: float) -> None:
        config.SNOW_RELEASED_SWAY = max(0.0, float(scale))

    # -- clump around the cursor -----------------------------------------
    def _build_clump_slots(self) -> None:
        count = max(1, self._clump_max)
        golden = math.pi * (3.0 - math.sqrt(5.0))
        self._slot_offsets = [(0.0, 0.0)]
        for i in range(1, count):
            radius = self._clump_radius * math.sqrt(i / max(1, count - 1))
            angle = i * golden
            self._slot_offsets.append((radius * math.cos(angle), radius * math.sin(angle)))
        self._slot_used = [False] * count

    def _claim_slot(self) -> int:
        for index, used in enumerate(self._slot_used):
            if not used:
                self._slot_used[index] = True
                return index
        return -1

    # -- geometry helpers -----------------------------------------------
    def _column_count(self) -> int:
        return max(1, int(self.width() // config.SNOW_PILE_CELL) + 2)

    def _column_for(self, x: float) -> int:
        column = int(x // config.SNOW_PILE_CELL)
        return max(0, min(len(self._columns) - 1, column))

    def _level_y(self, level: int) -> float:
        return self.height() - (level + 0.5) * config.SNOW_PILE_CELL

    def _place(self, column: int, level: int, flake: _Flake) -> None:
        flake.x = column * config.SNOW_PILE_CELL + config.SNOW_PILE_CELL / 2
        flake.y = self._level_y(level)
        flake.blocked = False

    def _reposition(self, column: int) -> None:
        for level, flake in enumerate(self._columns[column]):
            self._place(column, level, flake)

    def _clear_pile(self) -> None:
        self._columns = [[] for _ in range(self._column_count())]
        self._pile_dirty = True

    # -- pool ------------------------------------------------------------
    def _target_count(self) -> int:
        return int(round(self._density * config.SNOW_MAX_FLAKES))

    def _new_flake(self, at_top: bool = False) -> _Flake:
        w = max(1, self.width())
        h = max(1, self.height())
        y = random.uniform(-40.0, -4.0) if at_top else random.uniform(0, h)
        return _Flake(
            random.uniform(0, w),
            y,
            fall_scale=self._fall_scale,
            radius_scale=self._size_scale,
            sway_scale=self._sway_scale,
        )

    def _fill_pool(self) -> None:
        target = self._target_count()
        while len(self._flakes) > target:
            self._flakes.pop()
        while len(self._flakes) < target:
            self._flakes.append(self._new_flake())

    # -- interaction -----------------------------------------------------
    def _cursor_local(self) -> QPointF:
        point = self.mapFromGlobal(QCursor.pos())
        return QPointF(point.x(), point.y())

    def _release_attached(self) -> None:
        if self._attached:
            for flake in self._attached:
                if 0 <= flake.slot < len(self._slot_used):
                    self._slot_used[flake.slot] = False
                flake.slot = -1
                flake.released = True  # dropped by the cursor
            self._flakes.extend(self._attached)
            self._attached = []

    def _attach(self, flake: _Flake) -> bool:
        """Take a flake into the cursor clump. False when it cannot be taken."""
        if flake.blocked:
            return False  # just slipped out; wait for the next press
        slot = self._claim_slot()
        if slot < 0:
            return False
        flake.slot = slot
        flake.through = False
        self._attached.append(flake)
        return True

    def _capture_near_cursor(self) -> None:
        cursor = self._cursor_local()
        radius_sq = self._grab_radius ** 2
        kept: List[_Flake] = []
        for flake in self._flakes:
            x = flake.x + flake.sway_amp * math.sin(flake.phase)
            dx = x - cursor.x()
            dy = flake.y - cursor.y()
            if dx * dx + dy * dy <= radius_sq and self._attach(flake):
                flake.x = x  # snap to its drawn position, then follow the cursor
            else:
                kept.append(flake)  # clump full: keep falling, untouched
        self._flakes = kept

    def _grab_pile(self) -> None:
        """Pull piled flakes near the cursor and let unsupported ones fall."""
        cursor = self._cursor_local()
        radius_sq = self._grab_radius ** 2
        for column in range(len(self._columns)):
            stack = self._columns[column]
            if not stack:
                continue
            hit = [
                i for i, f in enumerate(stack)
                if (f.x - cursor.x()) ** 2 + (f.y - cursor.y()) ** 2 <= radius_sq
            ]
            if not hit:
                continue

            # Only remove flakes we can actually take; if the clump is full,
            # leave the pile untouched.
            grabbed = [i for i in hit if self._attach(stack[i])]
            if not grabbed:
                continue

            lowest = min(grabbed)
            kept: List[_Flake] = []
            for i, flake in enumerate(stack):
                if i in grabbed:
                    continue  # taken into the clump
                if i > lowest:
                    # Lost its support: let it fall and settle again.
                    self._flakes.append(flake)
                else:
                    kept.append(flake)
            self._columns[column] = kept
            self._reposition(column)
            self._pile_dirty = True

    def _move_attached(self) -> None:
        cursor = self._cursor_local()
        lerp = config.SNOW_FOLLOW_LERP
        leash_sq = config.SNOW_CLUMP_LEASH ** 2
        still: List[_Flake] = []
        for flake in self._attached:
            offset = self._slot_offsets[flake.slot]
            target_x = cursor.x() + offset[0]
            target_y = cursor.y() + offset[1]
            flake.x += (target_x - flake.x) * lerp
            flake.y += (target_y - flake.y) * lerp

            dx = flake.x - cursor.x()
            dy = flake.y - cursor.y()
            if dx * dx + dy * dy > leash_sq:
                # It could not keep up: it slips out and falls. It cannot be
                # grabbed again until the mouse is released.
                if 0 <= flake.slot < len(self._slot_used):
                    self._slot_used[flake.slot] = False
                flake.slot = -1
                flake.blocked = True
                self._flakes.append(flake)
            else:
                still.append(flake)
        self._attached = still

    def _unblock_all(self) -> None:
        """Allow slipped-out flakes to be grabbed again (on the next press)."""
        for flake in self._flakes:
            flake.blocked = False

    # -- pile physics ----------------------------------------------------
    def _land(self, flake: _Flake) -> bool:
        """Drop a flake onto a column; False when the column is already full."""
        column = self._column_for(flake.x)
        if len(self._columns[column]) >= self._pile_max:
            return False
        self._columns[column].append(flake)
        self._place(column, len(self._columns[column]) - 1, flake)
        self._pile_dirty = True
        return True

    def _stabilize(self) -> None:
        """Crumble columns that are too much taller than a neighbour."""
        slope = self._pile_slope
        for _ in range(len(self._columns) * self._pile_max):
            moved = False
            for column in range(len(self._columns)):
                height = len(self._columns[column])
                for step in (-1, 1):
                    neighbour = column + step
                    if not 0 <= neighbour < len(self._columns):
                        continue
                    if height - len(self._columns[neighbour]) >= slope:
                        flake = self._columns[column].pop()
                        flake.x = neighbour * config.SNOW_PILE_CELL + config.SNOW_PILE_CELL / 2
                        self._flakes.append(flake)  # falls into the gap
                        self._reposition(column)
                        self._pile_dirty = True
                        moved = True
                        break
                if moved:
                    break
            if not moved:
                break

    # -- loop ------------------------------------------------------------
    def _tick(self) -> None:
        if not self._enabled:
            return

        w = self.width()
        h = self.height()
        drift = self._wind * config.SNOW_WIND_DRIFT
        cell = config.SNOW_PILE_CELL
        had = bool(self._flakes) or bool(self._attached)

        held = self._interactive and winapi.left_button_down()
        if held:
            self._capture_near_cursor()
            self._grab_pile()
        elif self._attached:
            self._release_attached()
        if self._was_held and not held:
            self._unblock_all()  # slipped-out flakes become grabbable again
        self._was_held = held
        if held and self._attached:
            self._move_attached()

        landed = 0
        destroyed = 0
        alive: List[_Flake] = []
        for flake in self._flakes:
            flake.y += flake.fall_speed()
            flake.x += drift * flake.wind_scale()
            flake.phase += flake.sway_speed * flake.sway_scale()

            # A flake is destroyed only when it leaves the screen.
            if flake.y > h + 4 or flake.x < -40 or flake.x > w + 40:
                destroyed += 1
                continue

            if self._interactive and not flake.through:
                column = self._column_for(flake.x)
                landing_y = h - (len(self._columns[column]) + 0.5) * cell
                if flake.y >= landing_y:
                    if self._land(flake):
                        landed += 1
                        continue
                    # No room in the column: keep falling through the pile.
                    flake.through = True

            alive.append(flake)
        self._flakes = alive

        if self._interactive and landed:
            self._stabilize()

        # Constant spawner: new flakes keep entering from the top while the sky
        # is below the target count (set by density). This keeps snow falling
        # even as flakes land in the pile or get destroyed.
        spawned = 0
        target = self._target_count()
        if len(self._flakes) < target:
            per_second = self._density * config.SNOW_SPAWN_PER_SEC
            self._spawn_accum += per_second * (config.SNOW_TICK_MS / 1000.0)
            while self._spawn_accum >= 1.0 and len(self._flakes) < target:
                self._spawn_accum -= 1.0
                self._flakes.append(self._new_flake(at_top=True))
                spawned += 1

        if had or held or landed or destroyed or spawned:
            self.update()

    # -- painting --------------------------------------------------------
    def _rebuild_pile(self) -> None:
        if self._pile_pixmap is None or self._pile_pixmap.size() != self.size():
            self._pile_pixmap = QPixmap(self.size())
        self._pile_pixmap.fill(Qt.GlobalColor.transparent)

        p = QPainter(self._pile_pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 210))
        for stack in self._columns:
            for flake in stack:
                p.drawEllipse(QPointF(flake.x, flake.y), flake.radius, flake.radius)
        p.end()
        self._pile_dirty = False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._pile_pixmap = QPixmap(self.size())
        self._clear_pile()

    def paintEvent(self, _event) -> None:
        if self._pile_pixmap is None and not self._flakes and not self._attached:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._columns and any(self._columns):
            if self._pile_dirty:
                self._rebuild_pile()
            p.drawPixmap(0, 0, self._pile_pixmap)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 210))
        for flake in self._flakes:
            x = flake.x + flake.sway_amp * flake.sway_scale() * math.sin(flake.phase)
            p.drawEllipse(QPointF(x, flake.y), flake.radius, flake.radius)
        for flake in self._attached:
            p.drawEllipse(QPointF(flake.x, flake.y), flake.radius, flake.radius)
