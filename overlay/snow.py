"""Snowfall, an optional interactive mode, and crumbling snow piles.

Falling flakes settle on column-based piles. By default that is a single pile
along the bottom edge (the taskbar boundary); with "Сбор на окнах" enabled they
also settle on the top edges of ordinary desktop windows, each window with its
own pile height and crumble threshold. Piled flakes are real particles: they can
be picked up with a held mouse button, and a column that is too much taller than
a neighbour topples into it until the pile is stable.

Most numeric behaviour is adjustable at runtime through the ``set_*`` methods
(defaults live in ``overlay/config.py`` and are exposed in the menu).
"""

from __future__ import annotations

import logging
import math
import random
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QPainter, QPixmap
from PyQt6.QtWidgets import QWidget

from . import config, surfaces, winapi

LOGGER = logging.getLogger(__name__)


class _Flake:
    __slots__ = (
        "x", "y", "radius", "fall", "phase", "sway_speed", "sway_amp",
        "slot", "released", "blocked",
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
        self.released = False
        self.blocked = False

    def fall_speed(self) -> float:
        return self.fall * (config.SNOW_RELEASED_SPEED if self.released else 1.0)

    def wind_scale(self) -> float:
        return config.SNOW_RELEASED_WIND if self.released else 1.0

    def sway_scale(self) -> float:
        return config.SNOW_RELEASED_SWAY if self.released else 1.0


class _Surface:
    """A horizontal line flakes settle on: the ground or a window's top edge."""

    __slots__ = (
        "hwnd", "left", "right", "base_y", "pile_max", "slope",
        "columns", "blocked", "ground", "key", "top",
    )

    def __init__(
        self,
        left: float,
        right: float,
        base_y: float,
        pile_max: int,
        slope: int,
        *,
        hwnd: int = 0,
        ground: bool = False,
    ) -> None:
        self.hwnd = hwnd
        self.left = float(left)
        self.right = float(right)
        self.base_y = float(base_y)
        self.pile_max = max(1, int(pile_max))
        self.slope = max(1, int(slope))
        self.ground = ground
        self.key: Tuple[int, int, int] = (0, 0, 0)
        self.columns: List[List[_Flake]] = [[] for _ in range(self._count())]
        self.blocked: List[bool] = [False] * len(self.columns)
        # Highest occupied level per column; refreshed lazily on writes.
        self.top: List[int] = [-1] * len(self.columns)

    # -- geometry -------------------------------------------------------
    def _count(self) -> int:
        cell = config.SNOW_PILE_CELL
        span = self.right - self.left
        if self.ground:
            # Two spare columns keep the old edge behaviour (snow may land
            # slightly outside the canvas and is clamped back in).
            return max(1, int(span // cell) + 2)
        return max(1, int(span // cell))

    def column_for(self, x: float) -> Optional[int]:
        index = int((x - self.left) // config.SNOW_PILE_CELL)
        if self.ground:
            return max(0, min(len(self.columns) - 1, index))
        if 0 <= index < len(self.columns):
            return index
        return None

    def is_edge(self, column: int) -> bool:
        return column == 0 or column == len(self.columns) - 1

    def column_center(self, column: int) -> float:
        return self.left + (column + 0.5) * config.SNOW_PILE_CELL

    def level_y(self, level: int) -> float:
        return self.base_y - (level + 0.5) * config.SNOW_PILE_CELL

    def landing_y(self, column: int) -> float:
        return self.level_y(len(self.columns[column]))

    # -- pile -----------------------------------------------------------
    def place(self, column: int, level: int, flake: _Flake) -> None:
        flake.x = self.column_center(column)
        flake.y = self.level_y(level)
        flake.blocked = False

    def refresh_top(self, column: int) -> None:
        """Update the cached top level after a direct change to a column."""
        stack = self.columns[column]
        self.top[column] = len(stack) - 1 if stack else -1

    def reposition(self, column: int) -> None:
        for level, flake in enumerate(self.columns[column]):
            self.place(column, level, flake)
        self.refresh_top(column)

    def has_snow(self) -> bool:
        return any(level >= 0 for level in self.top)

    def crumbles(self, height: int, neighbour: int) -> bool:
        """Whether a column is too steep next to a neighbour of given height.

        The ground keeps the original "gap >= slope" rule. Window tops use a
        strict "gap > slope": with the menu default of 1 this still lets a
        single flake rest (a gap of one is tolerated) while any taller stack
        slides off, instead of every flake endlessly rolling back and forth.
        """
        gap = height - neighbour
        return gap >= self.slope if self.ground else gap > self.slope


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
        # Slipping is the interactive "выпадение из хватки" behaviour: when on,
        # a flake that lags too far behind the cursor leaves the clump.
        self._slip_enabled = bool(config.SNOW_SLIP_ENABLED)
        self._follow_lerp = float(config.SNOW_FOLLOW_LERP)
        self._clump_leash = float(config.SNOW_CLUMP_LEASH)
        self._slot_offsets: List[tuple[float, float]] = []
        self._slot_used: List[bool] = []
        self._spawn_accum = 0.0
        self._was_held = False
        self._build_clump_slots()

        self._ground = self._make_ground()
        self._windows: Dict[int, _Surface] = {}
        self._surface_cache: Optional[Tuple[List[_Surface], int]] = None
        self._windows_enabled = False
        self._window_pile_max = config.SNOW_WINDOW_PILE_MAX
        self._window_slope = config.SNOW_WINDOW_PILE_SLOPE
        self._window_wait = 0

        self._pile_pixmap: Optional[QPixmap] = None
        self._pile_dirty = True
        self._pile_present = False

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
            # Natural spawning only: the sky starts empty and fills from the top.
            self._spawn_accum = 0.0

    def set_wind(self, wind: float) -> None:
        self._wind = max(-1.0, min(1.0, wind))

    def set_density(self, density: float) -> None:
        self._density = max(0.0, min(1.0, density))

    def set_interactive(self, enabled: bool) -> None:
        self._interactive = enabled
        if not enabled:
            self._release_attached()
            self._drop_windows()
            self._clear_pile()
            self.update()
        else:
            self._window_wait = 0

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
        self._ground.pile_max = self._pile_max
        self._trim(self._ground)
        self._pile_dirty = True
        self._pile_present = True

    def set_pile_slope(self, slope: int) -> None:
        self._pile_slope = max(1, int(slope))
        self._ground.slope = self._pile_slope

    def set_windows_enabled(self, enabled: bool) -> None:
        self._windows_enabled = enabled
        self._window_wait = 0
        if not enabled:
            self._drop_windows()

    def set_window_pile_max(self, maximum: int) -> None:
        self._window_pile_max = max(1, int(maximum))
        for surface in self._windows.values():
            surface.pile_max = self._window_pile_max
            self._trim(surface)
        self._pile_dirty = True

    def set_window_slope(self, slope: int) -> None:
        self._window_slope = max(1, int(slope))
        for surface in self._windows.values():
            surface.slope = self._window_slope

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

    def set_slip_enabled(self, enabled: bool) -> None:
        self._slip_enabled = bool(enabled)
        if not self._slip_enabled:
            # Nothing may slip now, so previously slipped flakes are grabbable.
            self._unblock_all()

    def set_clump_leash(self, leash: float) -> None:
        self._clump_leash = max(8.0, float(leash))

    def set_follow_lerp(self, lerp: float) -> None:
        self._follow_lerp = max(0.05, min(1.0, float(lerp)))

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

    # -- surfaces --------------------------------------------------------
    def _make_ground(self) -> _Surface:
        return _Surface(
            0.0,
            float(max(1, self.width())),
            float(max(1, self.height())),
            self._pile_max,
            self._pile_slope,
            ground=True,
        )

    def _surfaces(self) -> List[_Surface]:
        """Ground plus window tops, rebuilt only when the window set changes."""
        cached = self._surface_cache
        if cached is None or cached[0] != len(self._windows):
            cached = ([self._ground, *self._windows.values()], len(self._windows))
            self._surface_cache = cached
        return cached[0]

    def _trim(self, surface: _Surface) -> None:
        for column, stack in enumerate(surface.columns):
            while len(stack) > surface.pile_max:
                stack.pop()  # excess is discarded
            surface.reposition(column)

    def _clear_pile(self) -> None:
        self._ground = self._make_ground()
        self._surface_cache = None
        for surface in self._windows.values():
            for stack in surface.columns:
                stack.clear()
            surface.top = [-1] * len(surface.columns)
        self._pile_dirty = True

    def _drop_column(self, surface: _Surface, column: int) -> None:
        stack = surface.columns[column]
        if not stack:
            return
        self._flakes.extend(stack)
        stack.clear()
        surface.top[column] = -1
        self._pile_dirty = True

    def _drop_surface(self, surface: _Surface) -> None:
        for column in range(len(surface.columns)):
            self._drop_column(surface, column)

    def _drop_windows(self) -> None:
        for surface in self._windows.values():
            self._drop_surface(surface)
        self._windows.clear()
        self._surface_cache = None
        self._pile_dirty = True

    # -- desktop windows -------------------------------------------------
    def _poll_windows(self) -> None:
        if not (self._windows_enabled and self._interactive):
            return
        self._window_wait -= config.SNOW_TICK_MS
        if self._window_wait > 0:
            return
        self._window_wait = config.SNOW_WINDOW_POLL_MS
        self._sync_windows()

    def _sync_windows(self) -> None:
        """Re-read the desktop windows and rebuild the surfaces on their tops."""
        top_level = self.window()
        exclude = int(top_level.winId()) if top_level is not None else 0
        try:
            found = surfaces.list_windows((exclude,))
        except Exception:  # pragma: no cover - defensive
            LOGGER.exception("Не удалось перечислить окна для снега")
            return

        dpr = self.devicePixelRatioF() or 1.0
        width = float(self.width())
        height = float(self.height())
        limit = max(1, int(config.SNOW_WINDOW_MAX_SURFACES))
        min_width = float(config.SNOW_WINDOW_MIN_WIDTH)

        previous = self._windows
        current: Dict[int, _Surface] = {}
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
                old = previous.get(win.hwnd)
                key = (round(left), round(top), round(right))
                if old is not None and old.key == key:
                    surface = old
                else:
                    if old is not None:
                        self._drop_surface(old)  # moved/resized: let it fall
                    surface = _Surface(
                        left,
                        right,
                        top,
                        self._window_pile_max,
                        self._window_slope,
                        hwnd=win.hwnd,
                    )
                    surface.key = key

                blocked = self._blocked_columns(surface, above)
                if blocked != surface.blocked:
                    for column, hidden in enumerate(blocked):
                        if hidden and not surface.blocked[column]:
                            self._drop_column(surface, column)  # now hidden
                    surface.blocked = blocked
                current[win.hwnd] = surface

            above.append((left, top, right, bottom))

        for hwnd, surface in previous.items():
            if current.get(hwnd) is not surface:
                self._drop_surface(surface)

        self._windows = current
        self._surface_cache = None

    @staticmethod
    def _blocked_columns(
        surface: _Surface,
        above: List[Tuple[float, float, float, float]],
    ) -> List[bool]:
        """Columns whose top edge is hidden behind a window that is higher up."""
        blocked = [False] * len(surface.columns)
        cover = [
            rect for rect in above
            if rect[0] < surface.right and rect[2] > surface.left
        ]
        if not cover:
            return blocked

        reach = max(12.0, 2.0 * config.SNOW_PILE_CELL)
        for column in range(len(surface.columns)):
            x = surface.column_center(column)
            edge = surface.base_y
            pile_top = edge - reach
            for left, top, right, bottom in cover:
                if left <= x < right and (
                    top <= edge <= bottom or top <= pile_top <= bottom
                ):
                    blocked[column] = True
                    break
        return blocked

    # -- pool ------------------------------------------------------------
    def _target_count(self) -> int:
        return int(round(self._density * config.SNOW_MAX_FLAKES))

    def _new_flake(self) -> _Flake:
        w = max(1, self.width())
        h = max(1, self.height())
        x, y = self._spawn_point(w, h)
        return _Flake(
            x,
            y,
            fall_scale=self._fall_scale,
            radius_scale=self._size_scale,
            sway_scale=self._sway_scale,
        )

    def _spawn_point(self, w: float, h: float) -> tuple[float, float]:
        """Where a brand-new flake enters the scene.

        With no wind it drops in from the top. The stronger the wind, the more
        often it enters from the windward edge instead, so the snowfall looks
        like it is being carried across the screen.
        """
        wind = self._wind
        if wind and random.random() < min(1.0, abs(wind)):
            # Positive wind drifts rightwards, so snow blows in from the left.
            depth = random.uniform(4.0, config.SNOW_SIDE_SPAWN_DEPTH)
            x = -depth if wind > 0 else w + depth
            return x, random.uniform(-24.0, h * 0.9)
        return random.uniform(0.0, w), random.uniform(-40.0, -4.0)

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
        for surface in self._surfaces():
            for column in range(len(surface.columns)):
                stack = surface.columns[column]
                if not stack:
                    continue
                hit = [
                    i for i, f in enumerate(stack)
                    if (f.x - cursor.x()) ** 2 + (f.y - cursor.y()) ** 2 <= radius_sq
                ]
                if not hit:
                    continue

                # Only remove flakes we can actually take; if the clump is
                # full, leave the pile untouched.
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
                surface.columns[column] = kept
                surface.reposition(column)
                self._pile_dirty = True
                self._pile_present = True

    def _move_attached(self) -> None:
        cursor = self._cursor_local()
        lerp = self._follow_lerp
        leash_sq = self._clump_leash ** 2
        cx = cursor.x()
        cy = cursor.y()
        still: List[_Flake] = []
        # At most one flake slips per tick: a sharp jerk does not strip the
        # whole clump at once, it thins out over the next few frames.
        worst: Optional[_Flake] = None
        worst_lag = leash_sq
        for flake in self._attached:
            offset = self._slot_offsets[flake.slot]
            flake.x += (cx + offset[0] - flake.x) * lerp
            flake.y += (cy + offset[1] - flake.y) * lerp

            if not self._slip_enabled:
                still.append(flake)
                continue
            dx = flake.x - cx
            dy = flake.y - cy
            lag = dx * dx + dy * dy
            if lag > worst_lag:
                if worst is not None:
                    still.append(worst)  # a later flake lags even more
                worst = flake
                worst_lag = lag
            else:
                still.append(flake)

        if worst is not None:
            # It could not keep up: it slips out and falls. It cannot be
            # grabbed again until the mouse is released.
            if 0 <= worst.slot < len(self._slot_used):
                self._slot_used[worst.slot] = False
            worst.slot = -1
            worst.blocked = True
            self._flakes.append(worst)
        self._attached = still

    def _unblock_all(self) -> None:
        """Allow slipped-out flakes to be grabbed again (on the next press)."""
        for flake in self._flakes:
            flake.blocked = False

    # -- pile physics ----------------------------------------------------
    def _try_land(
        self,
        flake: _Flake,
        prev_y: float,
        surfaces_now: List[_Surface],
    ) -> bool:
        """Settle a flake on the first surface below it that has room."""
        cell = config.SNOW_PILE_CELL
        best: Optional[Tuple[float, int, _Surface]] = None
        for surface in surfaces_now:
            column = surface.column_for(flake.x)
            if column is None or surface.blocked[column]:
                continue
            landing_y = surface.landing_y(column)
            if surface.ground:
                reached = flake.y >= landing_y
            else:
                # Windows are only hit when crossed from above: a flake in
                # front of a window keeps falling past it.
                reached = prev_y < landing_y <= flake.y
            if reached and (best is None or landing_y < best[0]):
                best = (landing_y, column, surface)

        if best is None:
            return False
        _landing_y, column, surface = best
        stack = surface.columns[column]
        if len(stack) >= surface.pile_max:
            return False  # no room here: keep falling to the surface below
        if (
            not surface.ground
            and surface.is_edge(column)
            and len(stack) >= surface.slope
        ):
            # The brim is loaded: the flake slides over the window edge.
            flake.x = surface.left - cell if column == 0 else surface.right + cell
            return False
        stack.append(flake)
        surface.place(column, len(stack) - 1, flake)
        surface.top[column] = len(stack) - 1
        self._pile_dirty = True
        self._pile_present = True
        return True

    def _stabilize(self) -> None:
        for surface in self._surfaces():
            if surface.has_snow():
                self._stabilize_surface(surface)

    def _stabilize_surface(self, surface: _Surface) -> None:
        """Crumble columns that are too much taller than a neighbour."""
        columns = surface.columns
        tops = surface.top
        count = len(columns)
        pile_max = surface.pile_max
        for _ in range(count * max(1, pile_max)):
            moved = False
            for column in range(count):
                height = tops[column] + 1
                if height == 0:
                    continue
                if (
                    not surface.ground
                    and surface.is_edge(column)
                    and height > surface.slope
                ):
                    # The brim is overloaded: snow spills off the window edge.
                    flake = columns[column].pop()
                    flake.x = (
                        surface.left - config.SNOW_PILE_CELL
                        if column == 0
                        else surface.right + config.SNOW_PILE_CELL
                    )
                    self._flakes.append(flake)
                    surface.reposition(column)
                    self._pile_dirty = True
                    moved = True
                    break
                for step in (-1, 1):
                    neighbour = column + step
                    if not 0 <= neighbour < count:
                        continue
                    if tops[neighbour] + 1 >= pile_max:
                        continue  # no room to crumble into
                    if not surface.crumbles(height, tops[neighbour] + 1):
                        continue
                    # Move the flake straight into the neighbour's stack. Sending
                    # it back into the air could drop it below a stack that grew
                    # in the same pass, making it fall through the pile.
                    flake = columns[column].pop()
                    columns[neighbour].append(flake)
                    # Only the moved flake and the one it landed on change
                    # position: refresh those two levels instead of the whole
                    # stack.
                    surface.place(neighbour, len(columns[neighbour]) - 1, flake)
                    surface.top[neighbour] = len(columns[neighbour]) - 1
                    surface.refresh_top(column)
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
        had = bool(self._flakes) or bool(self._attached)

        self._poll_windows()

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

        surfaces_now = self._surfaces()
        landed = 0
        destroyed = 0
        alive: List[_Flake] = []
        for flake in self._flakes:
            prev_y = flake.y
            flake.y += flake.fall_speed()
            flake.x += drift * flake.wind_scale()
            flake.phase += flake.sway_speed * flake.sway_scale()

            # A flake is destroyed only when it leaves the screen.
            if flake.y > h + 4 or flake.x < -40 or flake.x > w + 40:
                destroyed += 1
                continue

            if self._interactive and self._try_land(flake, prev_y, surfaces_now):
                landed += 1
                continue

            alive.append(flake)
        self._flakes = alive
        # A flake that leaves the screen or lands in a pile is simply gone; new
        # ones arrive only through the natural spawner below.

        if self._interactive:
            # Keep every pile at its resting shape, even when nothing happened
            # to land this tick (menu changes can leave a column too steep).
            self._stabilize()

        # The only spawner in every mode: flakes keep entering from the sky
        # (top or windward edge) while the falling count is below the target.
        # No refill happens because a flake was destroyed or landed.
        spawned = 0
        target = self._target_count()
        if len(self._flakes) < target:
            per_second = self._density * config.SNOW_SPAWN_PER_SEC
            self._spawn_accum += per_second * (config.SNOW_TICK_MS / 1000.0)
            while self._spawn_accum >= 1.0 and len(self._flakes) < target:
                self._spawn_accum -= 1.0
                self._flakes.append(self._new_flake())
                spawned += 1
        else:
            self._spawn_accum = 0.0

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
        for surface in self._surfaces():
            for stack in surface.columns:
                for flake in stack:
                    p.drawEllipse(QPointF(flake.x, flake.y), flake.radius, flake.radius)
        p.end()
        self._pile_dirty = False
        self._pile_present = True

    def _pile_has_snow(self) -> bool:
        if not self._pile_present:
            return False
        for surface in self._surfaces():
            if surface.has_snow():
                return True
        self._pile_present = False
        return False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._pile_pixmap = QPixmap(self.size())
        self._ground = self._make_ground()
        self._surface_cache = None
        for surface in self._windows.values():
            for stack in surface.columns:
                stack.clear()
            surface.top = [-1] * len(surface.columns)
        self._pile_dirty = True
        self._pile_present = False

    def paintEvent(self, _event) -> None:
        if self._pile_pixmap is None and not self._flakes and not self._attached:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._pile_has_snow():
            if self._pile_dirty:
                self._rebuild_pile()
            p.drawPixmap(0, 0, self._pile_pixmap)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 210))
        w = self.width()
        h = self.height()
        for flake in self._flakes:
            x = flake.x + flake.sway_amp * flake.sway_scale() * math.sin(flake.phase)
            # Skip flakes still outside the canvas (they wait above the top or
            # just beyond the windward edge).
            if -flake.radius <= x <= w + flake.radius and -flake.radius <= flake.y <= h + flake.radius:
                p.drawEllipse(QPointF(x, flake.y), flake.radius, flake.radius)
        for flake in self._attached:
            p.drawEllipse(QPointF(flake.x, flake.y), flake.radius, flake.radius)
