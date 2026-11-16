"""Shared runtime state.

Read values through the module (``from overlay import state; state.hover_flag``),
not via ``from overlay.state import hover_flag`` — that copies the old bool.
"""

hover_flag = False
