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
  cells it puts over water are bridge decks and railings, a boat's hull, and for a settlement a harbour's pier and moored
  boats (`port` tag, open water by the town) and a mill's water wheel (`river` tag, a river in the extent): the plan
  context carries the POI's `tags` and `SitePatch.still` / `.river` say where each goes.
- The road is the world's: `patch.road` is the bed from `sampling/roads.py` (what the renderer draws) and a **gate** is
  a run of it meeting the extent's edge. A layout calls `streets.lay_roads` to build round and onto it; `site_plan`
  clears those cells again (`clear_roads`), so a plan never draws the road itself, only lanes, buildings and walls.
  Nothing in the pipeline records anything for a site, so a site can change without moving the world fingerprint.
- Floor 0 is the ground and entry level: dungeons descend, towers rise. Everything random comes from the site seed
  (`rng.derive*` with the `site.*` labels); no wall-clock or global state.

## Plans

- A `SitePlan` has `cells` (inside, drawn at the site scale) and `outside` (the sky view for map, zoom and local:
  `ROOF`, `STONE`, streets). A layout returns both as `(cells, outside)`.
- Walls are one cell thick (`WALL`); the renderer joins them into line glyphs, so never draw a wall twice as thick.
  A door is a `DOOR` cell in a wall line. Buildings come from `building.build_building`.
- Use `cells.OUTSIDE_PRIORITY` when scaling down, so thin walls survive.
- An upper floor of a settlement or tower is the ground view with the buildings replaced, the current floor laid over
  all the lower ones: the storey of each building that reaches that floor, `ROOF` over each that does not (and over the
  outline of a lower, wider tower floor). Streets, trees, the wall and its gates stay as on the ground floor, undimmed.

## Adding a kind

1. Add a row to `data/sites.toml` (layout, furniture set, extent, resolution) and, for a settlement, a tier row.
2. If it needs a new pattern, add a `@layout("name")` function in `sites/` (built on `building`, `carve`, `furnish`,
   `streets`, ...) and import it in `plan.py` so the registration runs.
3. Add its furniture family (`[<family>.<role>]` weights) to `data/furniture.toml` if it has one of its own.
4. Add tests in `tests/sites/` covering determinism and what the kind does on water.
