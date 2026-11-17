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
SNOW_MAX_FLAKES = 400
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
SNOW_SPAWN_PER_SEC = 150       # flakes entering from the top per second (full density)
SNOW_SIDE_SPAWN_DEPTH = 24     # how far outside the edge wind-blown flakes appear

# "Released" flakes (dropped by the cursor): same rules as normal snow, but
# with these multipliers applied to wind, fall speed and sway.
SNOW_RELEASED_WIND = 1.0
SNOW_RELEASED_SPEED = 1.2
SNOW_RELEASED_SWAY = 0.95

HOVER_POLL_MS = 30
