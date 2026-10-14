"""biomegen - a seed-reproducible procedural island generator and curses explorer.

This package holds all reusable components of the application. The application is launched with
``uv run biomegen`` (or ``uv run python -m biomegen``); the entry point is :mod:`biomegen.cli`.

High-level package map (see docs/ARCHITECTURE.md for the full code-map):

    config/    - TOML + in-code defaults, deep-merged into a frozen Config object.
    util/      - cross-cutting utilities: rng (determinism anchor), noise, geometry.
    world/     - the data model: immutable World (numpy fields) + mutable Overlay + entities.
    sampling/  - how a grid cell reads the world.
    sites/     - lazy, deterministic site plans for POIs (built on demand from a POI).
    pipeline/  - the ordered procedural generation stages (terrain -> ... -> naming).
    naming/    - procedural name + lore generation (Markov + Tracery-style grammar).
    render/    - curses rendering: palette, glyphs, map/zoom views, HUD, input, app loop.
    export/    - SVG (and PNG) export of the current view.

Everything downstream of ``pipeline.generate`` treats the ``World`` as read-only; runtime/gameplay
mutations live in a separate ``Overlay`` that is composited at read time.
"""

__version__ = "0.1.0"
