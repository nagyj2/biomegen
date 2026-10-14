"""The renderer: pure frame building from a generated world, with no terminal I/O.

This layer is a read-only consumer of a :class:`~biomegen.world.world.World` (composited with any
:class:`~biomegen.world.overlay.Overlay`). One layer stack draws every output (the explorer, ANSI, plain, HTML,
SVG and PNG), so what the explorer shows is what a static render and an export show.

- ``grid``      : the cell grid IR (:class:`CellGrid`) and the document form used for static output.
- ``sampler``, ``fit``, ``detail`` : how a grid cell reads the world: one cell per tile, the fit-to-screen
                  block reduction, and the warped zoom and local scales.
- ``layers/``   : the layers (terrain, relief, tint, water, roads, bridges, clutter, interiors, markers, labels,
                  compass), each a function that paints onto the grid; ``views`` lists them per view.
- ``colors``, ``scatter`` : colour maths and lookups from the data tables; stable per-cell decoration.
- ``furniture/``: frame, graticule, scale bar and legend for static maps.
- ``backends/`` : ``ansi``, ``plain``, ``html``, ``svg``, ``png``.
- ``static``    : ``render_static`` and ``render_detail``, the entry points for whole-map and zoomed output.

Terminal input and output live in :mod:`biomegen.explorer`; nothing here imports it.
"""
