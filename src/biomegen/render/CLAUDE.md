# render/

Pure frame building: a world in, a `CellGrid` or `Document` out. No terminal I/O, no reads of keys, and nothing
here imports `explorer/`. The explorer, `--view`, `--scale` and the exports all run this one layer stack.

## Rules

- **Cell grid IR.** `CellGrid` is four numpy arrays (glyph `U1`, fg and bg `uint8 x3`, bold). Layers write into
  it; back-ends read it. Static text (frame, legend) is a `Document` of `Span` runs because margins have no
  background colour (`None` = the terminal default).
- **Read the world through the sampler.** A layer never indexes `world.*` arrays directly for per-cell data:
  it uses `ctx.sampler` (`nearest`, `blended`, `bilinear`, `coverage_mask`, `biome()`). That is what lets one
  layer run on the map, fit, zoom and local scales. A sampler is a pure function of world position.
- **Layer order** is data: `render.views.<name>.layers` (map) and `.detail_layers` (zoom, local). Default order:
  terrain, relief, [tint], water, [clutter], [borders], roads, [bridges], sites, markers, labels, compass. At the detail
  scales `markers` comes after `sites` and draws POI markers only at the scales in `render.detail_marker_scales` (zoom). A layer
  that only makes sense at one scale (`clutter`, `bridges`) returns early on the other.
- **Markers.** A tier row's `map_marker = false` hides its marker at the map scale (the hamlet); a POI kind row's `marker = false`
  hides it at every scale (the homestead: its plan still draws from the zoom scale down). Both are read per POI by the markers layer.
- **Political view.** `tint = "realm"` makes the tint layer mix each land cell toward its realm's colour (`render.realm_tint`)
  instead of replacing the fill with a ramp; the `borders` layer then lightens the line between realms and reddens war
  fronts. Both read realms through `ctx.realm`, which uses the sampler's warped tile like the biome blend, so a border is the
  same line at the zoom and local scales. A view's `tint` is a `render.ramps` entry or `"realm"` (`View.ramp`, `View.political`).
- **Political labels and legend.** In the political view the `labels` layer names the big realms (`render.labels.realm_*`)
  instead of landmasses and ranges; the legend appends REALMS (each independent realm, vassals nested, with ruler, seat, area,
  population, settlements) and DIPLOMACY (wars first, with front length and claimed town). Other views' legends have neither.
- **Tinted views at detail scales** draw the same ground as terrain (`clutter`, `roads`, `markers`, `sites`): clutter sits
  under the tint (a ramp's `keep_clutter` keeps its glyphs, dimmed; the floor glyph is blanked) and roads and sites are drawn
  over it, so inside a site the ground round the plan is tinted and the plan keeps its own colours.
- **Sites.** The `sites` layer draws each POI's plan (`biomegen.sites`) into the cells its extent covers: the plan's
  outside view (roofs, stone walls, streets) at the zoom and local scales (the map shows only the POI's marker tile), the inside (thin walls joined into
  line glyphs) at the site scale. The site scale is a
  `DetailSampler` over a site window (optionally just a region of it); the layer reads extents through the sampler's
  `col0` / `row0`, so a region draws exactly like the whole window. The roads layer draws the road
  everywhere, under the plans: a plan leaves the road's own cells void and adds only its lanes, buildings and walls.
- **Numpy-only hot paths.** No per-cell Python loops. Loops over POIs or road links are fine; inside them,
  paint a numpy window (`DetailSampler.cell_window`).
- **No literals.** Glyphs and colours come from `tables.biomes`, `tables.relief`, `tables.detail`,
  `tables.detail_relief` or `render.*`. ASCII output uses the `ascii` columns (`ctx.ascii_only`); without
  colour (`ctx.color` false) sparse glyphs show on every cell.
- **Deterministic decoration.** Use `ctx.scatter(*labels)` (blake2b-derived salt, keyed on tile and sub-cell),
  never builtin `hash()` or an unseeded RNG, so a world draws the same on any machine and holds still while panning.
- **Back-end parity.** ANSI, plain, HTML, SVG and PNG draw the same grid; a change to a layer needs no
  back-end change. Output stays byte-identical for a fixed seed.
- Rendering never changes the world: `scripts/fingerprint.sh` must not move.
- **Cacheable layers.** A layer in `layers.CACHEABLE` is drawn once into the explorer's render cache (`cache.py`) and
  reused while panning, so its cells may depend only on their world position, neighbours within one cell, the world, the
  config and the overlay; never on the grid's size or edges, the camera, or `ctx.labels`. A layer that breaks the rule
  (it places text or reads the screen) stays out of the set and runs every frame. `tests/render/test_cache.py` checks
  cached frames against fresh draws.

## Adding a layer

1. A module in `layers/` with a function `(ctx, grid) -> None` decorated `@LAYERS.register("name")`; import it
   at the bottom of `layers/__init__.py`.
2. Add its name to the `layers` and/or `detail_layers` of the views that use it in `config/defaults/render.py`.
3. Any tunable goes in `config/defaults/render.py` (or a `data/*.toml` row) and `config.example.toml` if a user
   would set it. A test in `tests/render/layers/` draws a small hand-made world and checks the cells.
