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
  boats (`port` tag, open water by the town) and a mill's water wheel and axle (`river` tag, a river in the extent: a multi-cell wheel set a cell into the river,
  joined by an axle to the house): the plan
  context carries the POI's `tags` and `SitePatch.still` / `.river` say where each goes.
- The road is the world's: `patch.road` is the bed from `sampling/roads.py` (what the renderer draws) and a **gate** is
  a run of it meeting the extent's edge. A layout calls `streets.lay_roads` to build round and onto it; `site_plan`
  clears those cells again (`clear_roads`), so a plan never draws the road itself, only lanes, buildings and walls.
  Nothing in the pipeline records anything for a site, so a site can change without moving the world fingerprint.
- A POI's row is `site_row_name(config, kind, variant)`: `<kind>_<variant>` when that row exists (a camp's purpose, a homestead's
  style), else the kind. A layout also gets `age_years` (years since the POI fell, None when undated or standing) and `purpose`.
- Floor 0 is the ground and entry level: dungeons descend, towers rise. Everything random comes from the site seed
  (`rng.derive*` with the `site.*` labels); no wall-clock or global state.

## Plans

- A `SitePlan` has `cells` (inside, drawn at the site scale) and `outside` (the sky view for map, zoom and local:
  `ROOF`, `STONE`, streets). A layout returns both as `(cells, outside)`.
- Walls are one cell thick (`WALL`); the renderer joins them into line glyphs, so never draw a wall twice as thick.
  A door is a `DOOR` cell in a wall line. Buildings come from `building.build_building`.
- Use `cells.OUTSIDE_PRIORITY` when scaling down, so thin walls survive.
- A settlement is at least its centre building and, room permitting, a house: when its lots find no room (a small footprint on a
  shore) `_ensure_house` builds the smallest building of a kind on any free dry ground nearest the plaza, its door joined to a street.
- Streets meet the road without bare ground between: `_join_roads` runs a street that passes within
  `sites.settlement.road_join_rows` of the road into it, and `_close_slivers` paves a one-cell strip between two streets.
- An upper floor of a settlement or tower is the ground view with the buildings replaced, the current floor laid over
  all the lower ones: the storey of each building that reaches that floor, `ROOF` over each that does not (and over the
  outline of a lower, wider tower floor). Streets, trees, the wall and its gates stay as on the ground floor, undimmed.
- A settlement's storeys are cut back as they rise (`_storey_rects`, drawn on `site.layout` `cut`, tunable in
  `sites.settlement.upper`): an L or T keeps its whole outline on the first upper storey (chance `whole`) and then one wing,
  the large or the small, so a tall building reads as a tower; a rectangle is shortened along its longer side. The cut part
  shows the roof of the storey below. The floor above the top storey (`geometry.site_roof_floor`) is the roof level: every
  building as its kind roof, so a roof hidden by a taller neighbour can be seen. Layouts in `sites.roof_layouts` (settlement,
  homestead, dungeon, tower, ruin) have one; the others build it on floor 0 and show `outside` (`site_plan`'s `roof_view`).

## Archetypes

- **Tower** and **watchtower** share one layout (tapering single-room floors, aligned stairs, a lookout); the watchtower has
  its own furniture family. **Dungeon**, **ruin**, **camp**, **boat** and **settlement** as above.
- **Ruin** erosion grows with `age_years` from `sites.ruin_erosion_young` to `sites.ruin_erosion` over
  `sites.ruin_erosion_years`; an undated ruin (placed by location) is fully eroded. A ruin with a `ruin_of` is drawn from that
  tier's site row (`site_row_for`), scaled by its `ruin_extent_share`: the tier's settlement plan, then a fall pass
  (`SiteContext.fall`, `settlement._fall`) on its own `site.erode` streams, so streets and lots are the settlement's. Each
  building *survives* with a chance (`ruin_standing`, falling with age; the centre building always does) or is *destroyed*: a
  survivor is damaged (`_damage`: breaches, stripped furniture, cracked floor, a roof over few rooms, trees growing in; the
  amounts are `sites.ruin_damage` times the ruin's wear, its erosion over `sites.ruin_erosion`), a non-survivor becomes rubble
  and bare ground with no roof or upper storey (`_destroy`, `sites.ruin_rubble`). The dressings are worn (`dress.wear_dress`),
  the wall falls in stretches (`ruin_wall_fall`) and every gate is rubble. With no room for buildings the single fallen
  building is drawn instead (as for a ruin with no origin).
- **Homestead**: one building of its style's kind (`tables.poi_styles.<style>.building`) in a yard (`homestead.py`): a short track,
  the building on free ground nearest the middle with its door joined to the track or the world's road, then the dressing the
  site row's `dress` names (`sites.homestead.dress`, laid by `dress.lay_dress` with the `standing` condition): a farm's field of
  full and harvested rows and a wagon, a mill's water wheel (`settlement._mill`, so it needs the `river` tag and a river in the
  extent), a mine's spoil, a lodge's clearing, a fishery's pier and boats (`settlement._harbour`, `port` tag). A mill's and a
  fishery's extent is wide so it reaches the neighbouring river or sea tile. Every draw is `rng.derive(seed, "site.homestead")`,
  so a later phase can rebuild the same building as the first lot of the hamlet it grows into.
- **Shrine**: one small walled room, a street door, an altar (`hearth`) at its middle, a roof from outside.
- **Battlefield**: open ground, an ellipse of floor (`sites.battlefield.clearing`) strewn with debris and a few wrecked
  wagons; nothing is built.
- **Camp** purposes override keys of `sites.camp` with `sites.camp_<purpose>` (builders: few tents; army: a field of tents).

## Building kinds, the centre, specialized buildings and dressings

- **Kinds** are rows of `data/buildings.toml` (`kinds.py`): a lot is a `Lot` with a `kind`. Size is the row's `rows` and
  `width`, rooms and furniture its `roles` and `furniture` family (`kinds.kind_spec`), the look from outside its `roof`. A kind's
  roof is a plan cell in a reserved block (`KIND_ROOF_BASE + rank`, constants in `world/tile.py`; `OUTSIDE_PRIORITY` treats it as a
  roof, the higher id wins a tie so civic kinds rank last); `Cell.ROOF` stays for towers and the old ruin layout.
- **The centre** is the tier's `centre` kind, stamped first in the reserved plot: a paved square sized by the tier's `reserve`
  kind (default its own centre) plus the kind's `apron` (`_plot`, `_centre`). It is drawn on its own streams (`site.layout`
  `centre`), counted out of the `fill` ground, kept clear of trees, street anchors and lots, so swapping the centre kind
  changes nothing outside the plot (tested); a promotion later rebuilds only the centre. Keep it that way: anything new that
  draws on the settlement's main stream must not read what lies inside the plot.
- **Specialized buildings** come from `surroundings.settlement_kinds` (also read by a later simulation): a pure, memoised rule
  over small `World` windows, never `pipeline/`. `ctx.kinds` holds the list; `_place_kinds` preplaces the `edge`, `any` and
  `shore` kinds (outermost first, or nearest the pier; the row's `tries` bound the search; one nearest-street transform for all),
  `_mill` the river kind, and a kind with no room is left to housing. A hamlet always has its style's building.
- **Dressings** are `dress.py`: `lay_dress` lays a site row's `dress` set (field, clearing, spoil, wagons, supplies, woods)
  with a `condition` (`standing` or `ruin`) that picks field variants from `tables.dress`; a ruin passes a `Dressing` record
  and `wear_dress` wears what was laid. New variants and wear are data (`data/dress.toml`); a variant with a look of its own
  gets a cell in the dress block (`DRESS_BASE + rank`).
- Performance: a cold plan build is bounded by data (`tries`, `sites.settlement.kind_reach_rows`); use `_spots` (numpy) rather
  than sorting every fitting cell in Python. `scripts/bench_sites.sh` is the gate (mean calls per kind; times are noisy) and
  `scripts/plan_digest.sh` proves a refactor leaves plans unchanged.

## Adding a kind

1. Add a row to `data/sites.toml` (layout, furniture set, extent, resolution) and, for a settlement, a tier row.
2. If it needs a new pattern, add a `@layout("name")` function in `sites/` (built on `building`, `carve`, `furnish`,
   `streets`, ...) and import it in `plan.py` so the registration runs.
3. Add its furniture family (`[<family>.<role>]` weights) to `data/furniture.toml` if it has one of its own.
4. Add tests in `tests/sites/` covering determinism and what the kind does on water.

## Adding a building kind

1. Add a row to `data/buildings.toml`: a unique `rank` below 64 (civic kinds last, so they win a roof tie), its `function`, `rows`,
   `width`, `shapes`, `roles`, `furniture` family (add it to `data/furniture.toml`), `roof` look and the keys of its function.
2. A production kind names its `suits`, `min_score`, `max_per_kind`, `siting` and `tries`; a style's `building` or a tier's
   `centre` / `reserve` then names it. `validate_tables` checks the references.
3. A new siting needs a placement function beside `_place_edge` and `_mill`; test it, and run `scripts/bench_sites.sh`.
