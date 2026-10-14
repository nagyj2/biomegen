# sites/

Lazy views built from a POI: the plan you see when you zoom into it. Sites are never stored in the `World`.

## Contract

- `site_plan(poi, floor, config, world)` is a pure function of the POI, the floor, the config and the terrain around the
  anchor, memoised per world and config in a bounded cache. Same inputs, same plan. The cached array is read-only;
  runtime edits go through `Overlay.apply_interior` (copy-on-write).
- A site is measured in **world tiles** (`geometry.site_geometry`): an extent centred on the anchor (below one tile for a
  tower or camp, several for a capital) and a window of whole tiles round it. Plan cells are terminal cells, so a
  plan is `rows_per_tile` rows and `render.cell_aspect` times as many columns per tile.
- The terrain comes from the renderer's own sampler (`patch.read_patch`; `sampling/terrain.py` defines land and river
  once), so a layout never disagrees with the water drawn beside it. A layout builds only on `patch.dry`; the only
  cells it puts over water are bridge decks and railings, and a boat's hull.
- Roads are read from the world arrays as **gates** on the extent's edge. Nothing in the pipeline records anything for a
  site, so a site can change without moving the world fingerprint.
- Floor 0 is the ground and entry level: dungeons descend, towers rise. Everything random comes from the site seed
  (`rng.derive*` with the `site.*` labels); no wall-clock or global state.

## Adding a kind

1. Add a row to `data/sites.toml` (layout, furniture set, extent, resolution) and, for a settlement, a tier row.
2. If it needs a new pattern, add a `@layout("name")` function in `sites/` (built on `carve`, `partition`, `furnish`,
   `circulation`, `streets`) and import it in `plan.py` so the registration runs.
3. Add its furniture set to `data/furniture.toml` if it has one of its own.
4. Add tests in `tests/sites/` covering determinism and what the kind does on water.
