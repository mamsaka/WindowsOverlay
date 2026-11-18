"""User-editable overlay configuration."""

from __future__ import annotations

EMPTY_HTML = (
    '<!doctype html><html><head><meta charset="utf-8"><style>'
    "html,body{width:100%;height:100%;margin:0;padding:0;overflow:hidden;"
    "background:transparent;color:#dfe4ff;font-family:'Segoe UI',sans-serif;}"
    "</style></head><body></body></html>"
)

# Panels are stacked vertically in the centre of the screen.
# size: (width, height); bg / border: CSS-compatible colours; html: content.
# Example:
#     ACTIVE_PANELS = {
#         "example": {"size": (300, 200), "bg": "#2b2b2b",
#                     "border": "#555555", "html": EMPTY_HTML},
#     }
ACTIVE_PANELS: dict[str, dict] = {}

PANEL_SPACING = 20

ACCENT_COLOR = "#9fb0ff"
TEXT_COLOR = "#dfe4ff"

# Right-hand slide-out menu.
MENU_WIDTH = 260
MENU_MARGIN = 8
MENU_SLIDE_MS = 220

# Arrow / handle size.
ARROW_SIZE = 36
# Distance kept between the arrow and the menu, and between the arrow's right
# edge and the screen edge when the menu is closed.
ARROW_GAP = 18

# Snow effect.
SNOW_TICK_MS = 25
SNOW_FALL_MIN = 0.6
SNOW_FALL_MAX = 2.6
SNOW_RADIUS_MIN = 1.0
SNOW_RADIUS_MAX = 2.8
SNOW_WIND_DRIFT = 2.6          # px per tick at full wind
SNOW_SWAY_AMPLITUDE = 16.0     # px
SNOW_SWAY_SPEED_MIN = 0.02
SNOW_SWAY_SPEED_MAX = 0.07

# Interactive snow: flakes pile up at the work-area bottom (the taskbar edge)
# and can be picked up with a held mouse button.
SNOW_PILE_MAX = 10             # max flakes stacked per column
SNOW_PILE_CELL = 6             # column width in pixels
SNOW_PILE_SLOPE = 3            # height gap (in flakes) that makes a column crumble
SNOW_GRAB_RADIUS = 10          # cursor grab radius in pixels
SNOW_FOLLOW_LERP = 0.35        # how fast grabbed flakes chase the cursor
SNOW_CLUMP_MAX = 20            # how many flakes can stick to the cursor
SNOW_CLUMP_RADIUS = 18         # clump radius around the cursor in pixels
SNOW_CLUMP_LEASH = 48          # max distance an attached flake may lag behind (px)
SNOW_SLIP_ENABLED = True       # allow flakes to slip out of the clump when lagging
SNOW_SPAWN_PER_SEC = 150       # flakes per second at full density (no count cap)
SNOW_SIDE_SPAWN_DEPTH = 24     # how far outside the edge wind-blown flakes appear

# Optional snow collection on the top edges of ordinary desktop windows
# ("Сбор на окнах" in the menu). Each window edge gets its own pile height and
# crumble threshold; everything is re-read from the desktop every poll.
SNOW_WINDOW_PILE_MAX = 3       # max flakes stacked per column on a window top
SNOW_WINDOW_PILE_SLOPE = 1     # height gap that makes window snow crumble/slide off
SNOW_WINDOW_POLL_MS = 150      # how often window positions/z-order are re-read
SNOW_WINDOW_MIN_WIDTH = 80     # ignore tiny windows (px)
SNOW_WINDOW_MAX_SURFACES = 10  # track at most this many windows

# "Released" flakes (dropped by the cursor): same rules as normal snow, but
# with these multipliers applied to wind, fall speed and sway.
SNOW_RELEASED_WIND = 1.0
SNOW_RELEASED_SPEED = 1.2
SNOW_RELEASED_SWAY = 0.95

# Carried momentum: a flake released or slipped out of the cursor clump keeps
# the velocity it was dragged with, then this extra velocity fades back into
# the normal snowfall. Both values are in px per tick.
SNOW_THROW_DRAG = 0.93        # per-tick decay of the carried velocity
SNOW_THROW_MAX = 26.0         # clamp so a mouse jerk cannot teleport a flake

# Autumn leaves. They deliberately do not reuse the snow physics: a leaf is
# light, has a lot of air drag, flutters sideways and tumbles around its own
# axis (the flip makes it turn edge-on). Mouse movement over the overlay
# creates a gust that pushes flying leaves and sweeps up settled ones; settled
# leaves lie in loose drifts along the bottom edge.
LEAVES_TICK_MS = 25
LEAVES_SPAWN_PER_SEC = 14      # leaves per second at full density (no count cap)
LEAF_SIZE_MIN = 4.5            # half-length of a leaf, px
LEAF_SIZE_MAX = 9.5
LEAF_GRAVITY = 0.05            # downward acceleration, px per tick
LEAF_DRAG = 0.93               # vertical drag per tick (terminal velocity)
LEAF_DROP_GRAVITY = 3.0        # gravity multiplier once a leaf loses its surface
LEAF_DROP_SPEED = 1.6          # downward kick when a supporting surface vanishes
LEAF_WIND_DRIFT = 2.2          # px per tick at full wind
LEAF_SWAY_ACCEL = 0.06         # sideways flutter acceleration
LEAF_SWAY_SPEED_MIN = 0.015
LEAF_SWAY_SPEED_MAX = 0.045
LEAF_SPIN_MIN = 0.010          # rotation per tick, radians
LEAF_SPIN_MAX = 0.045
LEAF_FLIP_MIN = 0.020          # tumbling / foreshortening per tick
LEAF_FLIP_MAX = 0.055
LEAF_GUST_RADIUS = 90          # how far the cursor breeze reaches, px
LEAF_GUST_FORCE = 0.55         # how strongly it pushes leaves
LEAF_GUST_LIFT = 0.30          # extra lift that sweeps a leaf off the ground
LEAF_SIDE_SPAWN_DEPTH = 24     # how far beyond the edge wind-blown leaves appear
LEAF_SIDE_CULL = 40            # destroyed once this far beyond the left/right edge, px
LEAF_GROUND_CELL = 16          # width of one drift slot along the bottom, px
LEAF_GROUND_LEVELS = 5         # layers of settled leaves per slot
LEAF_GROUND_STEP = 2.0         # vertical offset per layer, px
LEAF_GROUND_MAX = 140          # total settled leaves kept on screen
LEAF_WINDOW_CHANCE = 35        # default chance (%) to land on a desktop window top
LEAF_WINDOW_LEVELS = 3         # layers of leaves per slot on a window top
LEAF_LAND_TICKS = 6            # frames the landing squash animation lasts

HOVER_POLL_MS = 30
