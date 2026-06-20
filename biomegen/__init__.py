"""biomegen - a seed-reproducible procedural island generator and curses explorer.

This package holds all reusable components of the application. The application itself is launched
from the repository-root ``main.py`` (``python main.py``); this package is importable for reuse but
is intentionally *not* meant to be run with ``python -m biomegen``.

High-level package map (see ARCHITECTURE.md for the full code-map):

    config/    - TOML + in-code defaults, deep-merged into a frozen Config object.
    util/      - cross-cutting utilities: rng (determinism anchor), noise, geometry.
    world/     - the data model: immutable World (numpy fields) + mutable Overlay + entities.
    pipeline/  - the ordered procedural generation stages (heightmap -> ... -> naming).
    naming/    - procedural name + lore generation (Markov + Tracery-style grammar).
    render/    - curses rendering: palette, glyphs, map/zoom views, HUD, input, app loop.
    export/    - SVG (and PNG) export of the current view.

Everything downstream of ``pipeline.generate`` treats the ``World`` as read-only; runtime/gameplay
mutations live in a separate ``Overlay`` that is composited at read time.
"""

__version__ = "0.1.0"
