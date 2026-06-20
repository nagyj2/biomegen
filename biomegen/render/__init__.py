"""Curses rendering and the interactive application loop.

This layer is a strictly read-only consumer of a generated :class:`~biomegen.world.world.World`
(composited with any :class:`~biomegen.world.overlay.Overlay`). It is split so the *pure* layout/colour
logic is testable without a terminal, and the curses-specific drawing is thin:

- ``palette`` : the single colour authority - maps biome/region/marker to curses attributes via a
                capability ladder (truecolor/256 -> 8 -> mono), attempting per-region RGB.
- ``glyphs``  : biome / marker / interior glyph lookup (data-driven from config).
- ``state``   : the :class:`ViewState` (cursor, view mode, camera, floor, messages).
- ``map_view``: fit-to-screen down-sampling and 1:1 panning frame construction (pure).
- ``zoom_view``: the 5x5 magnified detail frame with biome-floor clutter (pure).
- ``status``  : the HUD / legend / message panel.
- ``input``   : key bindings -> actions.
- ``app``     : ``run(world, config)`` - curses bootstrap + main loop.
"""
