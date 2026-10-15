# biomegen — architecture & code-map

This document is the **map of the codebase, written for both humans and AI assistants**. Read it
first: it explains where everything lives, how data flows, and the rules that keep generation
reproducible. Each module also carries a docstring describing its own role in more detail.

---

## Mental model

`biomegen.cli` (`uv run biomegen`) parses CLI args, loads config, resolves a seed, and calls `biomegen.pipeline.generate`,
which runs a fixed sequence of stages that fill an immutable `World` (parallel numpy arrays per
tile). Runtime/gameplay changes never touch that base — they go into a separate `Overlay` that is
composited on read. The `render` layer draws the composited world through one layer stack and does no
terminal I/O; the `explorer` runs it interactively. Every interchangeable
algorithm is looked up from a `Registry` by a string key read from config, so swapping algorithms is
normally a config change, not a code change. A subset of algorithm families is also exposed as
direct CLI flags (`--noise-backend`) for single-run overrides without touching any
file. The same layers produce static maps, zoomed views and colour SVG/PNG images, from the UI
(`e` / `E`) or headlessly (`--view`, `--scale`, `--save`).

---

## Directory map

```
src/biomegen/
  __main__.py           `python -m biomegen` entry
  cli.py                CLI entry (argparse → config → generate → explorer | static map | headless)
  registry.py           Generic name→implementation registry (the swappability mechanism)
  config/
    defaults/           Authoritative defaults, one module per section — every tunable key lives here
                        (tables.py loads data/*.toml as the `tables` section)
    loader.py           TOML deep-merge onto defaults
    model.py            Frozen Config, dotted-path get(), section() sub-view
    validate.py         Coerce/clamp values on load
    tables.py           Row schemas and validation for the `tables` section
  data/                 User-overridable attribute tables, keyed by name (see data/CLAUDE.md)
    biomes.toml         One row per Biome member + one per Relief member (relief has min_elevation_m)
    tiers.toml          Settlement tiers: marker, population, spacing and density in km
    polity.toml         Realm kinds, name and ruler forms, relation weights, realm colours
    reasons.toml        Reason templates for wars, rivalries, alliances and trade; fallback place words
    terrain.toml        Terrain styles (continents, pangaea, archipelago, islands)
    geography.toml      Name patterns per geographic feature kind
  util/
    rng.py              DETERMINISM ANCHOR — blake2b sub-stream derivation; never builtin hash()
    noise.py            Noise backends (Perlin, Value, OpenSimplex, noise_lib) + fBm + domain warp
    geometry.py         Neighbours, connected-components, distance transforms, A* (aspect-aware options)
    units.py            Km-true scale model: GridScale (cell km size, aspect, km/cell, lat/lon)
  world/
    tile.py             Biome / Relief / WaterType / Cell enums + TileView accessor
    world.py            Immutable World (parallel numpy arrays) + fingerprint()
    overlay.py          Mutable Overlay (runtime edits, composited at read time)
    entities.py         POI / Realm / Relation / River / Lake / GeoFeature dataclasses
  sites/                Lazy, deterministic, cached site plans: what you see zooming into a POI
    geometry.py         Extent, window and plan resolution of a POI's site, in world tiles
    patch.py            The terrain under a site (read through the render sampler) and the road gates
    plan.py             site_plan(): the per-floor plan, memoised; SitePlan
    layout.py           SiteContext and the layout registry
    building.py         Thin-walled building model: footprint, subdivided rooms, doors, roles, furniture
    settlement.py structure.py camp.py boat.py   The layouts (structure = dungeon, tower, ruin)
    carve.py partition.py shapes.py furnish.py circulation.py streets.py   the layout toolkit
    cells.py            Cell groups, outside priority, wall autotile index
    coverage.py blit.py Which tiles and cells a site covers; scaling a plan into a grid (priority-aware)
  pipeline/             Ordered generation stages (see Pipeline section below)
    __init__.py         generate() orchestrator + stats()
    physical/
      terrain.py        Stage 1 — style, mountain belts, rank sea level, elevation_m, ocean, dist_to_ocean
      climate.py        Stage 2 — °C (latitude, lapse), wind moisture + rain shadow, rain_mm
      hydrology.py      Stage 3 — rivers, lakes, flow accumulation
      biomes.py         Stage 4 — biome from °C / mm / m, relief, volcanoes
      geography.py      Stage 5 — landmass_id; landmass, range, peak, lake, sea, river features
    pois.py             Stage 8 — wild POI placement (interim until phase 8)
    civilization/
      settlements.py    Stage 7 — habitability, capital / city / town / village placement
      roads.py          Stage 9 — road network (a road over water is a bridge)
      realms.py         Stage 9b — realm seeds, strength-weighted claiming, tribes, realm_id
      diplomacy.py      Stage 9c — vassal tree, colours, relations, war fronts
    story/
    naming.py           Stage 10 — names for all entities, realms and relation reasons
  naming/
    cultures.py         Culture profiles + biome-biased culture assignment
    syllables.py        Syllable-assembly name generator
    markov.py           Order-N character Markov name generator
    forge.py            Name-generation facade (root → dressed name)
    polity.py           Realm names, ruler styles and the wording of relation reasons
  sampling/             How a grid cell reads the world, shared by render and the site plans
    sampler.py          Sampler: one cell per tile, or a strided viewport
    detail.py           DetailSampler: magnified scales, warped continuous lookup; camera helpers
  render/               Pure frame building (no terminal I/O); layer stack shared by every output
    grid.py             CellGrid IR (glyph, fg, bg, bold arrays) and the Document / Span form for static text
    fit.py              FitSampler: fit-to-screen map, each cell shows its block's most salient tile
    views.py            View: layer lists per scale family + tint (a ramp or the realm tint), from render.views
    colors.py           Colour maths and per-biome / relief / detail / interior lookup arrays from the tables
    scatter.py          Stable per-cell decoration keyed on tile and sub-cell
    static.py           render_static (framed map + legend) and render_detail (zoom/local grid)
    colortest.py        --color-test swatches
    layers/             terrain relief tint water clutter borders roads sites markers names(labels) compass
    furniture/          frame, graticule, scale bar, legend for static maps
    backends/           ansi plain html svg png (a grid or document -> text or image)
  explorer/             Interactive terminal app (the only place that reads keys or writes the screen)
    state.py            ViewState, edge-pan camera, cursor start, floor sync and cycling, scale and mode steps
    input.py            Key readers (termios / msvcrt), key tokens, rebindable key -> action table
    writer.py           ANSI diff writer: alternate screen, writes only changed runs of cells
    panel.py            Info panel (tile, realm, POI, legend, controls) and the ? help overlay
    exports.py          e / E: SVG (and PNG) of the screen's map or the whole world
    app.py              compose_frame (map + cursor + panel) and the event-driven loop
tests/                  pytest suite mirroring src/: golden-world hash, RNG determinism, config, overlay, renderer, explorer …
config.example.toml     Sparse-overlay example (every key with its default value)
```

---

## Data model

### World (`world/world.py`)

Immutable once generation completes. Per-tile data stored as parallel 2-D numpy arrays indexed
`[y, x]` (row-major):

| Field | dtype | Range | Set by |
|-------|-------|-------|--------|
| `elevation_m` | float64 | metres, < 0 = sea depth | terrain; hydrology flattens lake surfaces |
| `temperature_c` | float64 | °C | climate |
| `rain_mm` | float64 | mm / year | climate; recomputed by hydrology after its moisture bonus |
| `moisture` | float64 | [0, 1] | climate + hydrology |
| `biome` | uint8 | `Biome` enum int | terrain, hydrology, biomes |
| `relief` | uint8 | `Relief` enum int | biomes |
| `landmass_id` | int32 | 0..L-1 largest first, -1=water | geography |
| `water_type` | uint8 | `WaterType` enum int | terrain, hydrology |
| `realm_id` | int16 | 0..R-1, -1=wild / water | realms |
| `front` | bool | war border cells of two warring powers | diplomacy |
| `poi_index` | int32 | 0..P-1, -1=none | settlements, pois |
| `road` | uint8 | 0 / 1 | roads |
| `road_tier` | uint8 | 0=none, 1=trunk, 2=spur | roads |
| `dist_to_ocean` | float32 | ≥ 0 km (aspect-aware) | terrain |
| `flow_accum` | float64 | km², wetness-weighted catchment | hydrology |

Sparse entity lists: `pois`, `realms` (`Realm`), `relations` (`Relation`), `rivers`, `lakes`, `features` (`GeoFeature`), `island_name`.

Scale metadata: `World.scale` is a `util.units.GridScale` built by `generate()` from `world.size_km`
and `world.center_lat` / `center_lon` (`center_lat = "seed"` draws it per generation attempt from the
`terrain.latitude` stream, `pipeline.center_lat`); `km_per_col`, `km_per_row`, `lat_top` and `lon_left` read
through to it. Cells are anisotropic: 25 x 50 km at the default 240x60, the 2:1 shape of a terminal cell.
The physical stages sample noise and measure distances in km through it.

`World.fingerprint()` hashes all per-tile fields via blake2b for the golden-world test (scale metadata
is not hashed).

### Overlay (`world/overlay.py`)

The **only** mutable runtime state. Two layers composited over the immutable base at read time:

- `surface`: sparse `(x, y) → attrs dict` for gameplay edits on the map surface.
- `interior`: sparse `(interior_seed, floor) → {(x, y): Cell}` edits to a POI's site plan.

JSON-serialisable. The base biome arrays are never mutated after generation.

---

## Generation pipeline

Order is load-bearing: each stage only consumes fields produced by earlier stages, eliminating
backtracking. A **land-exists gate** wraps the cheap terrain stage: if a seed yields less than
`world.min_land_fraction` land, the seed is deterministically perturbed and terrain re-runs (up to
`world.regen_attempts` times) before the expensive downstream stages run. Terrain sets its sea level by
rank, so the gate only trips when a style's land fraction is configured below the minimum.

```
terrain → climate → hydrology → biomes → geography → settlements → pois → roads
         → realms → diplomacy → naming
```

Roads end at every POI's anchor. A POI's site plan (`sites/`) is built lazily and finds the roads that reach
it from the world arrays, so no stage records anything for it.

### Stage 1 — Terrain (`pipeline/physical/terrain.py`)

Produces `elevation_m`, the salt ocean (`water_type`) and `dist_to_ocean` (km, for settlement and POI
scoring). Ported from the reference `_elevation`:

1. **Style**: a `tables.styles` row (`data/terrain.toml`) sets the land fraction, base feature size and
   the blend of base fBm, coarse continent fBm, a centre pull (pangaea) and island blobs (islands).
   `terrain.style = "seed"` draws a row per seed, weighted.
2. **Raw height**: domain-warped fBm sampled in km (`noise.km_grid`), plus **mountain belts** (ridged
   uplift along the zero-crossings of a coarse fBm, `noise.belt_lines`, masked on and off).
3. **Ocean frame**: height drops within `edge_margin` of the map edges.
4. **Rank-based sea level**: the quantile that leaves exactly the style's land fraction above water.
5. **Metres**: a hypsometric curve over land height rank; sea depth scales with sea-floor height.

### Stage 2 — Climate (`pipeline/physical/climate.py`)

Produces `temperature_c`, `moisture` (0..1) and `rain_mm`.
Ported from the reference `_climate`:

- **Temperature**: `equator_c - lat_coefficient × lat² + offset_c` per row (latitude from
  `World.scale`), regional noise, minus `lapse_c_per_km` per km of height.
- **Wind moisture**: per row a prevailing wind (westerlies inside `westerly_band_deg`, easterlies
  elsewhere) carries moisture: recharged over sea, rained out over land (more on rising ground), drying
  with distance and losing extra behind every rise, so ranges cast rain shadows.
- **Moisture**: wind rain + regional noise + coastal nearness, rank-normalised over land.
- **Rainfall**: `climate.rainfall_mm` maps moisture to mm, reduced in cold air. Hydrology recomputes it
  after its fresh-water moisture bonus.

### Stage 3 — Hydrology (`pipeline/physical/hydrology.py`)

Standard GIS surface-hydrology pipeline (RichDEM / GRASS GIS family), in metres and km:

1. **Priority-flood** (Barnes, Lehman & Soille 2014) on `elevation_m`: flood inward from the ocean,
   raising each pit to its spill level. A monotonic counter breaks ties deterministically. O(n log n).
   Yields the depression-free `filled` surface and an `order` array (a tie-breaker on flats).
2. **D8 flow directions**: each cell drains to its lowest 8-connected neighbour on the filled surface
   (key = `filled + order × 1e-9`). Vectorised via padded array shifts.
3. **Flow accumulation**: cells high-to-low push their drainage downstream. Each land cell adds its
   area × (`runoff_base` + moisture), so `flow_accum` is a wetness-weighted catchment in km².
4. **Lakes**: connected cells under at least `lake_min_depth_m` of standing water, at least
   `min_lake_area_km2` in area, become `Lake` entities; their surface in `elevation_m` is flattened to
   the spill level.
5. **Rivers**: land cells in the top `river_land_share` of catchments (and above
   `river_min_drainage_km2`) become fresh-water channels over their land biome, traced source -> mouth
   into `River` paths with `length_km`.
6. **River widening**: a display effect in tiles (`river_width_scale`, `river_max_width`) until the
   phase-4 renderer: great rivers near the sea span several tiles.
7. **Fresh-water moisture bonus**: `moisture_strength × exp(-km / moisture_radius_km)`, then `rain_mm` is
   recomputed from the new moisture.

### Stage 4 — Biomes (`pipeline/physical/biomes.py`)

Writes `biome` (the reference biome set: deep, shallow, seaice, lake, beach, desert, savanna, grass,
forest, jungle, swamp, taiga, tundra, snow) and `relief`. Ported from the reference `_biomes`:

1. **Sea**: sea ice below `sea_ice_c` (with noise), shallows within `shallow_km` of land, else deep.
   Lakes (marked by hydrology) freeze to sea ice below `lake_ice_c`.
2. **Land**: the first `biomes.bands` row whose `max_temp_c` is above the cell's °C applies; its
   `[biome, max_rain_mm]` rules pick by rainfall, very wet lowland in `swamp` bands becomes swamp, and
   warm low land touching the sea becomes beach. Rivers are not a biome: a river cell keeps its land
   biome and is fresh water in `water_type`.
3. **Relief**: the highest relief row whose `min_elevation_m` the cell reaches (hills 800 m, mountains
   1700 m, peaks 3200 m); peaks are snow.
4. **Volcanoes**: `volcano_counts` (one drawn per seed) mountain or peak cells near the coast.

The renderer draws rivers with its `water` layer over the land biome.

### Stage 5 — Geography (`pipeline/physical/geography.py`)

Writes `landmass_id` (every 8-connected component of solid land, largest first) and `World.features`, a
list of `GeoFeature` (`landmass`, `range`, `peak`, `lake`, `sea`, `river`), ported from the reference
`_regions` with km / km² thresholds (`geography.*`). Peaks are the distinct summits of ranges and
landmasses; rivers record the lake or nearest sea they flow `into`. Names are filled by the naming stage.

### Stage 7 — Settlements (`pipeline/civilization/settlements.py`)

Places the four settlement tiers (`capital`, `city`, `town`, `village`; rows in `data/tiers.toml`):

1. **Habitability** per land cell: `tables.biomes.<biome>.habitability` × the relief's `habitability_mul`, plus
   bonuses for a river, the coast or a lake within reach (`settlements.*_reach_km`, aspect-aware), × a seeded
   per-cell jitter. Water and cells at or below `settlements.min_habitability` are never settled.
2. **Placement** in tier `rank` order. A tier's count is land km² ÷ its `land_per_settlement_km2` × `settlements.density`
   (capitals are capped by `settlements.max_capitals`). Candidates are tried best-scoring first and kept when
   every earlier settlement is at least the tier's `spacing_km` away. Capitals need a landmass of at least
   `settlements.capital_min_landmass_km2` (or the biggest); cities and towns need a named-feature landmass.
3. **Record**: a `POI` of the tier's kind with a population from the tier's range and `port` / `river` / `lake` tags.

### Stage 8 — Wild POI placement (`pipeline/pois.py`)

Places towers, dungeons, ruins, camps and boats (interim; phase 8 makes POI kinds data-driven). Settlements come
from Stage 7 and count for spacing and remoteness:

1. **Count**: land km² (sea km² for boats) ÷ the kind's `km2_per_poi`, times `poi.density`.
2. **Eligibility**: allowed biomes, elevation bounds, land or water, a free tile, and for land kinds at least
   `poi.min_footprint_land` dry land under the tiles its site may cover (`footprint_land_fraction_mask`, a summed-area
   table), so a structure can sit on a coast but never mostly over water.
3. **Score**: 1 + freshwater and coastal closeness (km falloff) + remoteness from settlements + seeded jitter.
4. **Blue-noise pick**: kinds in `priority` order, best score first, kept when no placed POI is closer than
   `min_spacing_km` (aspect-aware km).
5. **Interior seed**: each POI mints a deterministic `interior_seed = blake2b(master_seed, "poi_interior", x, y)` used by the lazy site plan (see Sites and the Render layer).

### Stage 9 — Roads (`pipeline/civilization/roads.py`)

Connects POIs with meandering least-cost roads:

1. **Landmass grouping**: `water_type != SALT` (land + rivers + lakes, but not ocean) is labelled
   with 8-connected components. Roads are only routed within one component — they cannot cross open
   ocean, and a river slicing an island does not split it for routing purposes.
2. **Connection graph**: k-nearest-neighbour candidate edges (km) → Kruskal MST over the backbone tiers
   (`tables.tiers.<tier>.backbone`: capital, city, town; falls back to all POIs if none exist) → probabilistic attachment of
   remaining POIs (villages and other civilized POIs at `civilized_connect_prob`, uncivilized at `uncivilized_connect_prob`)
   → extra loop edges at `extra_edge_prob`. All random draws consume a per-component RNG in a fixed
   sorted edge order. Roads route to each POI's anchor.
3. **Routing**: A* over a per-tile cost surface. Cost factors: `base_cost` × the biome's `move_cost` + the
   relief's `move_cost` (tables `biomes`, `relief`) + `slope_cost_per_km × |Δelevation_m| / 1000` +
   `uphill_surcharge_per_km` (uphill only) + `water_cost` (cross water). A step costs its km length, so on tall
   cells a north-south step costs more than an east-west one. Existing road tiles are discounted by `road_discount`.
   A low-frequency noise field (`meander_strength`) bends roads organically. A `turn_cost` penalty
   reduces zigzagging. Search is bounded to a padded bounding box + `max_expansions` cap; a
   Bresenham straight-line fallback fires if A* exhausts its budget.
   - **Trunk phase**: MST + loop edges are routed first.
   - **Spur phase**: isolated POIs connect to the nearest existing road tile (not to a distant POI),
     preventing parallel-road artefacts.
4. **Bridges are not recorded.** A road tile over water is a bridge; the renderer and the site plans draw it from the
   road alone (`sampling/roads.py`). A diagonal step between two land tiles that passes between two water corners
   records nothing on the water: the diagonal link itself is the bridge (no L of road tiles, no box with a cross).

### Stage 9b — Realms (`pipeline/civilization/realms.py`)

Partitions solid land (any cell whose biome is not water; a river keeps its land biome) into realms; `politics.*` and
`tables.realm_kinds` hold the numbers (km, km²).

1. **Seeds**: every capital founds a major realm; a city may found a city-state (more likely when far from every
   capital); each seed draws a claim strength from its kind's span.
2. **Claiming**: a multi-source Dijkstra over the move-cost surface (biome + relief `move_cost`, plus `river_cost`).
   A step costs its km length times the cell's cost over the realm's strength; a realm stops at `claim_budget_km`.
   Salt water within `coastal_hop_km` of land is a stepping stone at `coastal_hop_cost` and is never claimed. Ties break
   by cost, then row-major cell, then realm.
3. **Tribes**: the largest unclaimed solid areas (≥ `tribe_min_area_km2`, at most `tribe_max`) each found a tribe seated at
   the area's most populous settlement (or its most inland cell); claiming then runs again with every seed.
4. **Record**: `realm_id` (-1 wild), a `Realm` per seed (seat, area, population, dominant biome, highland) and each
   POI's `realm_id`. Names, rulers and culture come from naming; vassals, colours and relations from diplomacy.

### Stage 9c — Diplomacy (`pipeline/civilization/diplomacy.py`)

1. **Borders**: shared border length in km per realm pair, from the edges between 4-adjacent solid cells.
2. **Vassalage**: majors, smallest first, with no vassals of their own may swear fealty (`vassal_chance` of their kind) to
   the independent neighbouring major sharing the longest border that is at least `vassal_area_ratio` times their
   area; city-states and tribes may swear to any neighbouring major. Only leaves swear, so the tree has no cycles.
3. **Colours**: golden-ratio hues for majors, a paler shade (`tables.realm_colors.vassal`) of the top's hue for vassals,
   vivid city-states, muted tribes.
4. **Relations** between independent powers sharing a border (borders summed over their vassal trees): war, rivalry,
   alliance, trade or none by `tables.relation_weights`; at least one war when any border exists; one sea pact between
   far-apart majors. `Relation.why` is a raw template from `tables.reasons`; naming fills its tokens.
5. **Fronts**: a war marks the border cells of its two powers in `World.front`, picks an attacker by coin toss and
   claims the defender's non-capital settlement nearest `claim_samples` border cells.

### Stage 10 — Naming (`pipeline/naming.py`, `naming/`)

Assigns names to all entities; region lore is gone (phase 7's chronicle replaces it):

- **Culture assignment**: each realm draws its culture from a biome-biased weighted distribution seeded on
  `(master_seed, "naming.culture", "realm", realm_id)`; a vassal keeps its own. POIs, rivers, lakes and features take the
  culture of the realm holding them, wild land and open water `common`. The island name uses the largest realm's culture.
- **Realms and relations** (`naming/polity.py`): a realm's form (name pattern and ruler styles) is a weighted draw among its
  kind's `tables.realm_forms` rows, favoured by the habitat of its land; its base word and ruler's name are made in its
  culture. A city-state is short-named after its seat. Last, each relation's reason template gets its tokens: the claimed
  or a nearby town, the longest river, the largest range and sea, and the realms' trade goods.
- **Root generation** (per-entity RNG keyed on `(category, *stable_key)`):
  - *Syllable assembly* (default): draws `onset + nucleus + coda` from the culture's phoneme sets
    with a vowel-collision guard and syllable-boundary length cap.
  - *Markov* (optional, per category): an order-N character Markov chain trained on a small
    per-culture seed corpus generates phonotactically consistent names. Selected by
    `naming.generators.<category> = "markov"`.
- **Dressing**: roots are dressed per entity category — settlements append a culture suffix
  (`-ton`, `-vik`, `-loth`, …), dungeons/ruin/towers get evocative patterns (`Ruins of X`,
  `X Catacombs`).

---

## Swappable algorithms (Registry pattern)

Each algorithm family has a `Registry` instance. To add a new algorithm: implement it, decorate
with `@REGISTRY.register("name")`, and reference `"name"` in the config. No call-site edits needed.

The **CLI flag** column lists flags accepted by `biomegen.cli` for single-run overrides (no config file
needed). All other families are changed via their config key.

| Family | Config key | CLI flag | Built-in choices |
|--------|-----------|----------|-----------------|
| Noise backend | `terrain.noise_backend` | `--noise-backend` | `perlin`\* · `value` · `opensimplex` · `noise_lib`† |
| Flow model | `hydrology.flow_model` | — | `d8` · `dinf` |
| Pathfinder | `roads.pathfinder` | — | `astar`\* · `tcod` · `dijkstra` |
| Site outline | `sites.shape` | — | `mixed`\* · `rectangle` · `blob` · `cellular` · `drunkard` · `diamond` · `cross` |
| Site layout | `tables.sites.<kind>.layout` | — | `settlement` · `dungeon` · `tower` · `ruin` · `camp` · `boat` |
| Spatial compute | `compute.backend` | — | `scipy`\* · `numpy` · `pure` |

\* default   † optional C-extension; unavailable if not installed (no C compiler needed for defaults)

CLI flags use the same selector strings as config. A flag takes precedence over both the TOML
overlay and the built-in default for that run only.

---

## Render layer

`render/` turns a world into a **cell grid** (`CellGrid`: glyph, foreground, background and bold arrays) and
does no terminal I/O. Everything that draws is a *layer*, a function that paints onto the grid; the
explorer, `--view`, `--scale` and the SVG/PNG exports all run the same stack, so they always agree.

- **Samplers** decide what a cell reads. A layer never indexes the world arrays directly; it asks the
  sampler, which maps each cell to a world position. `Sampler.viewport` is one cell per tile (or a stride);
  `FitSampler` covers a block of tiles per cell and shows the block's most salient tile (priorities in the
  `priority` columns of `tables.biomes` / `tables.relief` and `render.fit_priority`, so a lone lake, a river
  or a road survives); `DetailSampler` is the zoom and local scales.
- **Views** (`render.views`) list the layers per scale family: `layers` for the map and `detail_layers` for
  zoom and local, plus an optional tint: a ramp (elevation, temperature, rainfall) or `realm`, the political view, which
  mixes realm colours into the land, draws a one-cell `borders` line (red on war fronts, fainter between a vassal and its
  overlord) through the biome-blend warp so borders match at every scale, names the big realms and lists them with their
  relations in the legend. `v` cycles terrain, political, elevation, temperature, rainfall.
- **Layers** (`render/layers/`): `terrain`, `relief`, `tint`, `water`, `clutter`, `borders`, `roads`, `bridges`,
  `sites`, `markers`, `labels`, `compass`. Colours and glyphs come from `tables.biomes`, `tables.relief`,
  `tables.detail` and `tables.detail_relief` (`data/*.toml`), and the `render.*` config; none are literals.
- **Back-ends** (`render/backends/`) turn a grid or document into ANSI, plain text, HTML, SVG or PNG.
- Hot paths are numpy; the only Python loops are over POIs and road links.

**Scales and the cursor.** Four scales; the first three share one tile cursor and one camera:

- **Map**: `fit` (the whole world scaled down) or `1:1` (one cell per tile, panned). Toggle with `f`.
- **Zoom**: each tile is a `zoom_scale x (zoom_scale * cell_aspect)` block of cells.
- **Local**: the screen shows `local_rows` tiles vertically, each magnified further; furnished plans appear here.
- **Site**: the highest zoom of a point of interest, and only there (elsewhere it stays local). One plan cell per
  terminal cell, with a single-cell cursor and its own camera; see Sites.

**Detail scales.** A `DetailSampler` maps each cell of a tile's `cell_w x cell_h` block to a continuous world
position (tile centres on the integers) and reads the biome, relief and river coverage through the
biome-blend warp. `terrain` draws the biome's floor glyph on every cell (a rocky floor on mountain relief),
`relief` only recolours, `clutter` scatters the `tables.detail` glyphs (denser where wetter or higher),
`water` draws river coverage, `roads` the thin bed, `bridges` the decks, `markers` one cell per tile and
`sites` the zoom shell or local furniture. Hillshade is bilinear elevation, the same at every scale.

**Biome blending** at detail scales: each cell looks up its biome at a domain-warped world
position (`blend_strength`, `blend_scale`). The warp is a pure function of world position + seed, so
zoom and local are consistent samplings of the same blend — they look like zooms of each other.
Setting `blend_strength = 0` gives a crisp grid. Water is blended by bilinear coverage
(`water_blend_threshold`) so diagonal rivers and lakes join.

**Roads & bridges** at detail scales (the `roads` layer, drawn over terrain but under POI
markers and sites): the map keeps its single-cell road glyphs, but at zoom/local roads are not
markers — they render like the rivers do.

- *Roads* are a thin meandering **bed**: a detail cell is road when its (road-warped) world position
  lies within `road_half_width` tiles of the straight line joining two 8-adjacent land-road tile
  centres. That distance test is a pure function of world position, so every scale draws the same
  shape. The width is a fixed fraction of a tile (0.14 by default), so it grows with the magnification (about one
  row at zoom, two or three at the site view), but never under `road_min_rows` rows. The bed glyph follows the direction of the link (`road_bed`: `─ │ ╱ ╲`) in the `detail_colors.road_*` colours with small
  clutter scattered along it (`road_clutter`, plus `road_clutter_local` fine detail at the close scale). A
  small `road_warp` gives it an organic wobble and `road_smooth` rounds its corners (a tile with exactly two links
  is first pulled toward its neighbours (`road_relax`), then becomes a quadratic curve between the middles of its links,
  so staircases read as curves; junctions and ends stay straight) and `road_meander` drifts position slowly (features
  `road_meander_scale` tiles across, from the `roadmeander.*` streams) so a long straight road wanders; water and river cells are never drawn over (bridges carry those).
- *Bridges* are the same bed over water: where a bed cell lies over water it is a **deck**, and the band as wide
  again beside it is the railing (`detail_colors.deck_*` / `wall_*`). They are not POIs: the road model
  (`sampling/roads.py: road_bed`) is the one rasterisation, shared by the renderer and the site plans.

### Sites (`sites/`, drawn by the `sites` layer)

A POI's **site** is what you see when you zoom into it: a plan drawn on the terrain around its anchor. Nothing is
stored in the `World`; a site is a pure function of the POI, the config and the terrain (`sites.site_plan`).

- **Extent and window** (`geometry.py`). Each kind has a row in `tables.sites` (`data/sites.toml`): an `extent_tiles`
  `[w, h]` in world tiles, centred on the anchor (a tower or camp is under one tile, a village about one, a capital
  several), and `rows_per_tile`, the plan resolution (columns follow `render.cell_aspect`, so a tile stays square).
  The extent is scaled by a seeded jitter and, for settlements, by population. The **window** is the whole tiles that
  hold the extent plus `sites.margin_tiles`: a detail grid whose cells are plan cells.
- **Terrain patch** (`patch.py`). The terrain under the extent is read through the same `DetailSampler` the renderer
  uses (`sampling/terrain.py` defines land and river once), so a plan agrees exactly with the water drawn around it.
  Roads are not stored: the road bed over the extent (`sampling/roads.py`, the raster the renderer draws) is read
  into the patch, and each run of road cells meeting the extent's edge makes a **gate** (at most `sites.max_gates`).
  A layout lays the road into its grid (`streets.lay_roads`) to build round it and join doors to it, then hands it back
  (`streets.clear_roads`): the plan leaves the road's own cells void, so the one road is drawn the same inside and outside.
- **Plan faces.** `SitePlan.cells` is the **inside** (one cell per terminal cell, drawn at the site scale);
  `SitePlan.outside` is the **sky view** (map, zoom, local): roofs (`ROOF`), solid walls (`STONE`), streets, trees.
  Outside views ignore floor and overlay. Walls in the inside are one cell thick (`WALL`) and joined into box-drawing
  lines at draw time by the 4-neighbour mask (`cells.wall_index`, `render.interior_walls`); doors are gaps.
- **Layouts** (`layout.py`, one per `layout` key; each returns `(cells, outside)`). `building.py` makes a rect, L or T
  footprint, subdivides it recursively with shared one-cell walls, joins rooms by a door spanning tree plus loops, adds a
  street door, assigns roles by size and furnishes them from `tables.furniture.<family>.<role>`. `settlement.py` grows an irregular town: a
  wobbling outline (stretched towards each road), a plaza, spokes from it to the outline, partial rings, lanes into any
  ground still too far from a street, then lots fitted to the free ground beside the streets (each a building whose door
  faces its street), and for walled tiers a wall along the outline with gates where spokes and the road meet it. `structure.py` builds dungeon (a surface gatehouse plus underground rock floors of rooms and
  corridors or caves), tower (tapering single-room floors, aligned stairs, a lookout) and ruin (a building with breaches,
  rubble, trees and partial roofs); the entrance faces a gate. `camp.py` and `boat.py` are open-air (tents, hull).
- **Scales.** One plan per face, scaled into the cells its extent covers by `blit.sample_rect`. Where a view is coarser
  than the plan, the cell of highest `OUTSIDE_PRIORITY` wins, so a one-cell wall survives. Void is transparent. The
  world's road is drawn everywhere (roads layer, under the plans); a plan leaves its cells void and adds only lanes.
- **The site view** (explorer). Zooming in on a POI opens its site: the window drawn one plan cell per terminal cell,
  only the visible cells (a `DetailSampler` with `origin` and `shape`). The cursor is one cell `(px, py)`; the tile
  cursor follows the tile under it. Moving past the window leaves for local. Zoom steps out.
- **Floors.** Floor 0 is the ground and entry level: dungeons descend (`lowest_floor … 0`), towers rise (`0 … top`), and
  settlements rise too: each tier row has a `floors` range, the buildings nearest the plaza are the tallest, every storey
  has its ground floor's outline with its own rooms, and the stairs stand on a free floor cell of both floors.
  `<` / `>` cycle floors inside a site or on its tiles; entering starts at floor 0.
- **Cache and overlay.** Plans are memoised per world and config in a bounded cache (`sites.cache_size`), read-only.
  Runtime edits compose on top via `Overlay.apply_interior` (copy-on-write), keyed by the site seed and floor.
- **Colour.** Plan cells take glyphs from `render.interior_glyphs` (`interior_glyphs_ascii` for ASCII) and colours from
  `render.interior_palette`; bridge cells use the deck and wall colours of `render.detail_colors`.

A new kind is a row in `data/sites.toml` and, if it needs a new pattern, a `@layout("name")` function registered in
`sites/` (render and explorer iterate the sites generically).

---

## Explorer (`explorer/`)

The only place that reads keys or writes the screen. `explorer.app.run` is **event driven**: it composes a
frame, diff-writes it, blocks on a key, and repeats, so an idle explorer uses no CPU.

- **Frame.** `compose_frame` builds the map for the current scale and mode (the sampler, with the camera
  edge-panned so it scrolls only when the cursor reaches a viewport edge), reverses the cursor's cell (its
  whole tile block at zoom and local), and pastes the info panel under it into one terminal-sized grid.
  `e` exports the map grid *without* the cursor.
- **Writer.** `DiffWriter` compares the grid with the last frame (numpy) and sends a cursor move and the
  new cells for each run of changed cells, with a style sequence only where the style changes; an
  unchanged frame writes nothing. It owns the alternate screen, the hidden cursor and line wrap, and
  restores them on exit even after an error. Colour is truecolor, 256 or none.
- **Keys.** A reader yields tokens (`termios` cbreak on POSIX with a self-pipe for resize, `msvcrt` on
  Windows); `resolve_action` maps them through the rebindable `keys` table. Any key closes the `?` help.
- **Testing.** The loop takes an injected key source and output stream, so the tests drive it with a
  scripted keyboard, replay the written escape codes on a tiny virtual screen, and run the real program on a
  pseudo-terminal. The Windows paths cannot be exercised on Linux.
- **Not in 4c.** Regenerating the world (`r`) returns in phase 9 with the chronicle panel.

---

## Exports

`explorer/exports.py` writes SVG (always, dependency free) and PNG (when `export.png` is set and Pillow is
installed) from a cell grid, named by `export.filename_pattern` in `export.dir`. `e` writes the on-screen map
grid, `E` the whole world at one cell per tile through `render_static`; `--save FILE` writes the same images
headlessly by suffix. The back-ends are `render/backends/svg.py` and `png.py` (Pillow is imported lazily and a
missing Pillow just drops the PNG). Cells are emitted in fixed row-major order with fixed numeric formatting,
so a fixed seed yields byte-identical SVG, the export analogue of the golden-world fingerprint.

---

## Determinism rules (do not break these)

1. **`blake2b` only** — never `hash()`. Python's built-in `hash()` is salted per-process
   (`PYTHONHASHSEED`), making any world derived from it irreproducible across runs.
2. **Named sub-streams** — `util.rng.derive(seed, *labels)` with labels from `rng.LABELS`. Every
   stage uses its own independent stream; changing one stage cannot shift another stage's output.
   New labels must be added to `LABELS` rather than invented ad-hoc.
3. **Single authoritative numpy path** — no dual scalar/array path for the same field. Scalar and
   numpy arithmetic can disagree on rounding, silently breaking cross-platform reproducibility.
4. **Sorted iteration** — any Python-loop stage must iterate collections in a defined order (use
   `sorted()`). Dict and set ordering can vary across Python versions / implementations.
5. **Golden-world test** — `World.fingerprint()` is pinned for a fixed seed. Any determinism
   regression fails this test immediately.
