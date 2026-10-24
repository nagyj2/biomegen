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
    chronicle.toml      Wording of the chronicle's events: templates, and templates_near that name a nearby place
    rulers.toml         Ruling styles: label, draw weight, battle strength multiplier, temper and base personality traits
    secession.toml      Secession scoring: term weights, relation scores and wording tags, form weights
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
    overlay.py          Mutable Overlay (runtime edits, composited at read time; a revision counts edits)
    derived.py          derived(): values worked out once per world (road pieces), checked by a source digest
    entities.py         POI / Realm / Relation / River / Lake / GeoFeature / ChronicleEvent / FallenRealm dataclasses
    chronicle.py        chronicle_text() and chronicle_json(): the history as three-column text or JSON; ChronicleFilter / filter_events()
    territory.py        TerritoryChange deltas and OwnerTimeline: the owner map at any moment, owner ids (wild, fallen, predecessor)
    ledger.py           EventLog: the generated chronicle and a continuation (a simulation's events) read as one list, `id == index`
    manifest.py         SiteManifest: what stands in a settlement's plan (houses, specialized slots, the centre's tier, the wall)
    sim_state.py        SimState: the simulation's state (tick, continuation lists, manifests); empty and unused until phase 10
  sites/                Lazy, deterministic, cached site plans: what you see zooming into a POI
    geometry.py         Extent, window and plan resolution of a POI's site, in world tiles (a settlement's from its potential)
    potential.py        potential_tier(): the largest tier a site could grow into, from its land and room; assign_potentials(), the pass
    manifest.py         site_manifest(): today's manifest from a settlement's tier and population; manifest_buildings()
    patch.py            The terrain under a site (read through the render sampler) and the road gates
    plan.py             site_plan(poi, floor, config, world, manifest=None): the per-floor plan, memoised; SitePlan
    layout.py           SiteContext and the layout registry
    building.py         Thin-walled building model: footprint, subdivided rooms, doors, roles, furniture
    settlement.py structure.py camp.py boat.py homestead.py   The layouts (structure = dungeon, tower, ruin; homestead = one building of its style's kind in a yard, dressed; `homestead_lot` hands that building to the hamlet it grows into)
    kinds.py            Building kinds (`tables.buildings`): roof cells, sizes, specs, a tier's centre; the legend names of kind and dress cells
    surroundings.py     settlement_kinds(): the specialized buildings a settlement's potential is chosen to have, from the terrain round it (pure, memoised)
    dress.py            Dressings (`tables.dress`): variants by condition, laying a field, clearing, spoil, supplies; the Dressing record and a ruin's wear
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
    pois.py             Location placement of the POI kinds (score fields, blue-noise picks, `commit`); run by story/pois.py
    civilization/
      settlements.py    Stage 7 — habitability, capital / city / town / village placement
      roads.py          Stage 8 — settlement roads (a road over water is a bridge); Stage 9f — `spurs` for the POIs placed later
      realms.py         Stage 9b — realm seeds, strength-weighted claiming, tribes, realm_id
      diplomacy.py      Stage 9c — vassal tree, colours, relations, war fronts
    story/
      history.py        Stage 9d — the chronicle: dates realms and settlements, places fallen realms, founding/settling/conquest
      rulers.py         Ruling styles, the successions that change them and every realm's `Ruler` records (traits included)
      secession.py      Secession score (pure term functions shared with a later simulation) and the planning of splits, offshoots and defections
      founding.py       The founding and settling events a secession step may add or change
      conflicts.py      Wars, peace, pacts, battles and falls played through time with faction strengths
      ledger.py         Ledger: collects the events, then sorts and numbers them (and sets `tick` and `derived`); `merge_events` for the annals
      territory.py      The territory planner: walks the ledger back from today's map (expansions, foundings, falls, strips, secessions)
      territory_fields.py  Seat cells and km from the seat, computed once per world for the planner
      places.py         nearest_settlement() and nearest_feature(): the locality rule for a place named in text
      poi_rules.py      poi_for_event(): the pure event-to-POI rule table (what an event makes)
      poi_styles.py     style_score() / style_count(): the pure scorer of the homestead and hamlet styles; place_styles(), the last POI pass
      pois.py           Stage 9e — places the POIs the events make, then the location pass, then the styles pass
    naming.py           Stage 10 — names for all entities, realms and relation reasons
  naming/
    cultures.py         Culture profiles + biome-biased culture assignment
    syllables.py        Syllable-assembly name generator
    markov.py           Order-N character Markov name generator
    forge.py            Name-generation facade (root → dressed name)
    polity.py           Realm names, ruler styles and the wording of relation reasons
    chronicle.py        Fallen-realm names and cultures; renders every chronicle event's text
    hooks.py            POI.hook / hook_refs: an event's text or a row template, with its name spans
  sampling/             How a grid cell reads the world, shared by render and the site plans
    sampler.py          Sampler: one cell per tile, or a strided viewport
    detail.py           DetailSampler: magnified scales, warped continuous lookup; camera helpers
  render/               Pure frame building (no terminal I/O); layer stack shared by every output
    grid.py             CellGrid IR (glyph, fg, bg, bold arrays) and the Document / Span form for static text
    fit.py              FitSampler: fit-to-screen map, each cell shows its block's most salient tile
    cache.py            RenderCache: the explorer's terrain kept in chunks per scale, map frames kept whole
    views.py            View: layer lists per scale family + tint (a ramp or the realm tint), from render.views
    colors.py           Colour maths and per-biome / relief / detail / interior lookup arrays from the tables
    scatter.py          Stable per-cell decoration keyed on tile and sub-cell
    chronicle.py        chronicle_document(): the history as a coloured year / kind / text document; layout_events() wraps it and marks search matches
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
    app.py              compose_frame (map + cursor + panel) and the event-driven loop; restart and the history key
    chronicle_pager.py  --chronicle on a terminal: scroll, filter and search the chronicle
    history_viewer.py   --history and t: the political map at a moment, the powers then and the chronicle beside it
    events.py           EventReader / ChronicleReader: where the panel reads history from (through world.ledger.EventLog)
    ticks.py            TickSource, NoTicks and Clock: the time seam (speed, pause) a simulation plugs into
tests/                  pytest suite mirroring src/: golden-world hash, RNG determinism, config, overlay, renderer, explorer …
                        (test_layering.py checks the package layering; test_scripts.py smoke-tests the measuring scripts)
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

Sparse entity lists: `pois`, `realms` (`Realm`), `relations` (`Relation`), `rivers`, `lakes`, `features` (`GeoFeature`),
`island_name`. History: `year` (the present; 0 for a dawn start), `territory` (`TerritoryChange` deltas), `chronicle` (`ChronicleEvent`, sorted, `id` is the
index) and `fallen_realms` (`FallenRealm`), read through `events_until(year)`, `events_at(x, y)` and `events_of(realm_id)`.
`Realm.founded` and `POI.founded` are chronicle years; a `POI` also holds `fell`, `event_ids` (the events that made or mark
it), `hook` / `hook_refs`, `bandit_strength`, `purpose` (a camp's), `style` (a homestead's or a generated hamlet's, a
`tables.poi_styles` row) and `connect`. A ruin holds `ruin_of` (the settlement tier it
was, always set) and `pop` (its peak population); `POI.free` is derived (civilized, no realm) and never stored. `rulers`
(`Ruler`: realm, reign years, style, five traits, name) lists every realm's rulers, founder first, read through
`rulers_of(realm_id)` and `ruler_at(realm_id, year)`. A realm that began in a secession records `origin` (`offshoot` or `split`),
`parent` (an offshoot's parent realm) or `predecessor` (a split's index into `predecessors`: a `Predecessor`, the old realm that
ended in a clean split). A `ChronicleEvent` also has a `tick` (its absolute month, `year * history.months_per_year + month - 1`) and
`derived` (True for what the generation made, False for what a simulation emits). A `POI` holds `potential`, the largest settlement
tier its site could grow into (set by `sites.potential`; empty for a POI with no settlement plan). None of this is in the per-tile
arrays, so the fingerprint ignores it.

#### The simulation's seams (`world/ledger.py`, `manifest.py`, `sim_state.py`)

Phase 10's simulation reads three shapes that exist now and hold nothing yet. `EventLog(world, extra)` reads the chronicle and a
continuation as one list, so `id == index` holds across both and a reader (`explorer/events.py`) asks one object; `append` numbers
an event after the last and refuses to go back before its `(year, month)`. `SiteManifest` is what stands in a settlement's plan
(`houses`, `specialized`, the centre's `tier`, `walled`, `grown_from`). `SimState` is the simulation's own state: a `tick`, a
`revision`, continuation lists for events, rulers, predecessors and POIs (their ids continue after the generated ones:
`next_ruler_id`, `next_predecessor_id`, `next_poi_index`) and a manifest per changed settlement. `world/` imports only `util` and
`config`; `tests/test_layering.py` holds every package to the layer order.

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

JSON-serialisable. The base biome arrays are never mutated after generation. `revision` counts the edits, so a reader
that keeps what it drew (the render cache) knows when to redraw.

### Derived values (`world/derived.py`)

Because the base is immutable, anything worked out from its arrays is computed once: `derived(world, key, build,
*sources)` keeps a value per world (weakly) and rebuilds it only when a blake2b digest of its source arrays changes (a
hand-made test world edited in place). The road network's pieces (`sampling.roads.road_pieces`) live here; a later
simulation's per-tile lookups (movement costs, distances) belong here too.

---

## Generation pipeline

Order is load-bearing: each stage only consumes fields produced by earlier stages, eliminating
backtracking. A **land-exists gate** wraps the cheap terrain stage: if a seed yields less than
`world.min_land_fraction` land, the seed is deterministically perturbed and terrain re-runs (up to
`world.regen_attempts` times) before the expensive downstream stages run. Terrain sets its sea level by
rank, so the gate only trips when a style's land fraction is configured below the minimum.

```
terrain → climate → hydrology → biomes → geography → settlements → roads → realms → diplomacy
         → history → pois → spurs → naming
```

`history.start = "dawn"` (`--start dawn`) skips settlements through history and the spurs: a young world with the land,
rivers and features and a few ruins, towers and dungeons, but no settlements, roads, realms or chronicle, at year 0, for a
later simulation to settle.

The roads stage links the settlements; the `spurs` stage, after the pois stage, branches off the POIs that may be linked
(`POI.connect`). A POI's site plan A POI's site plan (`sites/`) is built lazily and finds the roads that reach
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

### Stage 8 — Roads (`pipeline/civilization/roads.py`)

Connects the settlements with meandering least-cost roads (the wild and history POIs come later, see Stage 9f):

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
   - **Spur phase**: isolated POIs (villages) connect to the nearest existing road tile (not to a distant POI),
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
3. **Colours**: every realm gets its own colour (`faction_color`, `util/palette.py`): of `politics.faction_hue_steps` hues at its
   role's saturation and value (`tables.realm_colors`: major, vassal, city_state, tribal, fallen) the one farthest in CIELAB from
   every colour already taken (and from the chronicle's neutral colours), bright enough to read (`faction_min_luma`).
   Fallen realms take theirs from the history stage the same way. The map and the chronicle show the same colour.
4. **Relations** between independent powers sharing a border (borders summed over their vassal trees): war, rivalry,
   alliance, trade or none by `tables.relation_weights`; at least one war when any border exists; one sea pact between
   far-apart majors. `Relation.why` is a raw template from `tables.reasons`, one whose river, range or sea lies within
   `politics.reason_near_km` of the border (`places.nearest_feature`; recorded in `Relation.places`); naming fills its tokens.
5. **Fronts**: a war marks the border cells of its two powers in `World.front`, picks an attacker by coin toss and
   claims the defender's non-capital settlement nearest `claim_samples` border cells.

### Stage 9d — History (`pipeline/story/history.py`, `conflicts.py`)

A chronicle derived from the finished political state; there is no tick simulation. Dates come from static quantities
and every draw is a `history` sub-stream keyed on the entity.

1. **Founding**: each realm is founded `age` years before the present (`history.span_years`), the age drawn from its
   kind's `history.age_range` and pulled older by a larger area (`age_area_weight`); all foundings are then shifted so the
   oldest is in `history.first_founding_year`. A seated realm's founding is its seat's too (tag `capital`). Every civilized
   POI gets `founded`. Each fallen realm has a founding event too.
2. **Settling** (`history.settle_kinds`), **conquest** (one per vassal tie, after both realms plus `min_gap_years`).
   **Ruling styles and rulers** (`rulers.py`): each realm is founded under a style from `tables.ruling_styles`; a succession falls
   every `history.succession_years` and changes the style with `succession_change_chance`. Only a change is a `succession` event
   (tags `from:` and `to:`), but every succession, silent ones included, starts a `Ruler` (the founder first) with the style's base
   `traits` plus a draw within `history.ruler_trait_spread`, on its own stream so the style draws never move. `Realm.ruling_style`
   is the present ruler's style, and a style's `strength_mul` tilts that realm's battles while it holds. Naming names the rulers;
   the texts name the founder in a founding, the overlord's ruler of that year in a conquest and both rulers in a succession.
   **Free settlements**: a free city or town (no realm holds it) gets a `settling` event tagged `free`; one within
   `history.remnant_km` of a fallen realm's site is a remnant: dated inside that realm's life (after the conflicts, so its fall
   year is final) with a `settling_remnant` event naming it, and also marked by the fall it outlived.
   **Secession** (`secession.py`, scored by the terms of `data/secession.toml`; `history.secession.chance` is the chance of the
   likeliest form and each form scales it by its `tables.secession_forms` weight, at most `max_per_world` in a world):
   a *clean split* (two touching realms of one old realm: they share the earlier founding year, the old realm is a
   `Predecessor` with its own founding event, and one `secession` event replaces the two foundings) is decided up front, before
   the rulers are drawn, because the younger realm's founding moves; an *offshoot* (a major or city-state left an older major
   realm; its founding is held back) and a *defection* (a non-seat city or town left an older independent realm for its holder;
   its settling is held back) are planned from the finished map and checked on the conflicts timeline in their year with the
   parent's or old owner's strength then, a failed check giving the ordinary founding or settling. No cell moves.
3. **Fallen realms**: `FallenRealm`s on wild, habitable land (`fall_min_habitability`) spaced `fall_spacing_km` from each
   other and from settlements, with a founding year and a natural fall year.
   The stage runs: founding years, settlement years, fallen realms, clean splits applied, rulers, offshoot and defection planning,
   the realm, settling and conquest events, the conflicts (with the secession checks), then the remnants.
4. **Conflicts** (`conflicts.py`): every faction has a strength (a realm's area over the mean; a draw for a fallen realm)
   that a won battle raises and a lost one lowers. The timeline is planned, then played in year order:
   - each relation of two powers sharing a border may have an older, ended war (`past_war_chance`, `past_war_years`) with
     battles and a `peace`; the relation itself (an ongoing `war`, `rivalry` or `treaty`) begins at any later year, so wars
     and pacts are not confined to one period;
   - a fallen realm fights up to `fallen_wars` wars against the nearest living realms that exist at the time, one
     battle each at its ruins (the one that conquers it is tagged `decisive`, as is the last battle of an older war); once a lost battle leaves it under `fall_strength` it is conquered a few years on (a `fall`
     tagged `conquered` naming the victor), otherwise it falls at its natural year;
   - battles along a front (`battles_per_100km_front`, on `diplomacy.front_cells`) are won with a chance proportional to
     strength; `realm_ids` of a battle or peace is `[winner, loser]`.

An event holds a raw template from `tables.chronicle` (`templates_near` only when `places.nearest_settlement` finds a
settlement on the same landmass within `history.near_km`); naming renders `text` and the `refs` (the span, kind and id of
every name in it). The ledger sorts events by `(year, kind order, creation order)` and numbers them, dealing each event a month, its `tick` and `derived = True`.
`--chronicle [--chronicle-format json]` prints them as three columns (year, event type, text), coloured by `--color` or
the terminal (`render/chronicle.py`): a realm, its ruler and its settlements are in the realm's map colour (`Realm.color`),
a fallen realm in its own (`FallenRealm.color`), the old realm of a split in its own (`Predecessor.color`); a settlement is in its realm's colour from its first mention (the neutral `history.colors.settlement` only when no realm holds it), a bandit tower or dungeon in `hideout`,
a river, range, sea or other named land in the neutral `place`; the kinds and the year
use `history.colors` too. The places a reason names are marked too (`Relation.why_refs`, moved into the event's `refs`).
`scripts/chronicle.sh` wraps it.

On a terminal `--chronicle` opens the **chronicle pager** (`explorer/chronicle_pager.py`, text format only; `--no-pager` or a pipe
prints instead). Filters narrow the events (`ChronicleFilter`, `world/chronicle.py`: `--kind` (repeatable, comma lists), `--from-year`,
`--to-year`, `--realm` (a substring of the name of a realm, fallen realm, old realm, ruler or settlement the event involves: its ids and the names in its text; `event_names`). `--realm` and `--search` (and the pager's `/` and `p`) are expressions: `|` is or, `&` is and (binding tighter), whitespace round a term is trimmed (`HI |Lo` and `HI|Lo` both mean `"hi"` or `"lo"`), empty terms are dropped, and each `&` term of a name filter may be found in any of the event's names (`parse_expression`); suggestions and Tab complete only the term being typed, `--search` (a substring of year,
kind or text)) and apply to the printed text and JSON as well (the JSON keeps every realm and settlement, so ids resolve). In the pager the
filters are the start state and `--search` also starts the highlight. Keys follow the explorer's `keys` table: arrows / WASD / HJKL scroll
(shift or capitals `controls.fast_step` lines), space / Page Down / Page Up page, `g` / `G` ends, `/` search (highlights, jumps), `n` / `N`
matches (the current match has its own colour, `history.colors.match_current`), `v` cycles the kind, `y` asks a year range, `p` a name (Up / Down pick from the names containing what is typed, Tab completes; each suggestion is tagged at the right edge with what it is, in the neutral `history.colors.type_*`), `c` clears, `?` help, `q` / Esc quits. `layout_events` wraps each event
to the width (continuations indented under the text) and marks the match in `history.colors.match`; a name is coloured as in the full
chronicle even when filtered.

#### Territory (`pipeline/story/territory.py`, `territory_fields.py`, `world/territory.py`)

History moves no cell: `World.realm_id` is today's map. Who held which land earlier is recorded as `TerritoryChange` deltas
(`World.territory`, oldest first: year, month, kind, sorted flat cell indices, from and to owner, event id) found by **walking
back** from the present, so the present map and the fingerprint never move. Owners are realm ids, `WILD` (-1), a fallen realm
(`fallen_owner`, -2 downward) or a predecessor (`predecessor_owner`, -1000 downward); `World.owners_at(year, month)` replays the
changes forward or backward from checkpoints (`OwnerTimeline`) and `World.top_realm_at` counts a vassal tie from its conquest.

- The planner runs after every other event is in the ledger and before it is numbered. It walks the events newest to oldest and
  undoes each: a realm's **expansions** (new `expansion` events, `history.territory.expansions` per realm kind, each a
  `expansion_share` of its area, the cells farthest from its seat first, never under `core_share` of it) and its **founding**
  (what is left was wild); a fallen realm's land (chosen at its fall: the wild cells nearest its ruins plus its conqueror's,
  split between fallen realms alive together by distance to their ruins); a **battle** or the **peace** of an older war moves a
  strip of the winner's land along the front to the loser (`strips`); a **secession** hands an offshoot's land to its parent and
  a split's to its predecessor. A conquest only recolours (a vassal tie).
- Terrain never changes, so the fields it reads are computed once (`TerritoryFields`: seat cell and km from the seat of every
  held cell). Draws are `history` / `territory` sub-streams keyed on the realm, fallen realm or battle.
- Events and changes carry a `month` (1 to `history.months_per_year`); a year's months are drawn sorted in event order, so
  causality within a year holds. A simulation can place several events a year and append its own changes in the same form.

#### The history viewer (`explorer/history_viewer.py`)

`--history [YEAR]` (also `t` in the explorer, which opens it on the cursor's tile) is view only. The map is the political map
at a moment (`build_grid(..., moment=)`): fallen realms and predecessors in their colours, a vassal tinted as its overlord only
after its conquest, the war fronts of the wars then (`world/wars.py`, read from the war, peace and conquest events), only the
points of interest that stood then (`world/lifespans.py`: a settlement from its founding, a ruin from its fall, a battlefield
from its battle, a watchtower from its war until it is dismantled, a tower bandits took as a watchtower until they did), and only
the roads laid by then (`World.road_links`). The chronicle sits beside it, scrolled to the moment's events (highlighted; later
ones dimmed), with recent events marked on the map by kind (`history.viewer.glyphs`).

- **Stops.** `[` `]` step through every listed event (one stop each, `(year, month, event id)`: two events of one month are two
  stops, and the map, points, roads, wars and powers are read just after that event) and every territory change; the start
  (before any event) is the first stop and the present is always the last
  (`change_moments`); `m` also lists the minor events (towers, roads, small settlements) and stops at them. From the explorer,
  `{` `}` step through the events and changes at the selected tile, ending at the present; `g` asks a year; `\` is the present.
- **Powers.** Tab moves to the powers list (up / down choose one, kept across the stops): the right pane then shows that power's
  profile at the stop (`world/powers.py`) in one fixed layout, so powers compare by flicking between them: a row per fact (status,
  ruler, rule, reign in years, seat, land, share, people, density, strength, liege) with a `-` where there is none, a row per
  settlement tier and homesteads, a vassals heading with three reserved rows (`+N more`), and the relations (wars, rivalries, pacts)
  last, the one list left to grow, under a heading that never moves. Space shows the power's land on the map and Space again hides it.
  A power exists from its opening event to its closing one (a split's old realm until the split event itself).

#### Annals and the life of places (`pipeline/story/annals.py`)

The history records what moves realms; the annals (after the pois and spurs) add **minor** events (`salience = "minor"`, hidden
by default) for what stands on the land: a tower raised or a dungeon delved (one that came of a fall is dated by it; one placed by
location is ancient, year 0, with chance `history.annals.ancient_share`, else made in a drawn year), the founding of villages and
hamlets, every road laid (`World.road_links`, dated after both ends stand), and a watchtower's life. A **watchtower** is raised
when its war is declared, behind the front that war had then (`pois._border_at_war`); at the peace it is dismantled (kept only in
`World.vanished`, so today's map has no trace of it), or abandoned (`watchtower.abandon_chance`), and an abandoned one is taken by
bandits `occupy_years` later and is a bandit `tower` from then on. The new events are merged into the finished chronicle
(`ledger.merge_events`, renumbering every id the world keeps: `POI.event_ids`, `RoadLink.event_id`, `TerritoryChange.event_id`).
A road is laid after both its ends stand and, for a spur, after the road it runs into (`RoadLink.joins`). A realm's people are the
people in its settlements, hamlets and homesteads plus an outside share and a rural term, each drawn per realm
(`realms.population`, recounted after the styles pass), so a realm follows its places and not its area.
A settlement is also dated no sooner than its land was taken from the wild (`territory.wild_since`), and every conquest is won in a
war (`history._conquest_events`: the war, a decisive battle on the shared border, then the conquest).

### Stage 9e — POIs (`pipeline/story/pois.py`, `poi_rules.py`, `pipeline/pois.py`)

Runs after history, so a POI can follow the chronicle and take its realm by grid lookup. One row per kind in
`tables.pois` (`data/pois.toml`): `source` (`location`, `history`, `both`), the placement numbers, the events that make it,
and the simulation seams (`owner`, `dynamic`, `connect`, `bandit_strength`, `bandit_radius_km`, `lifespan`).

1. **Rule table** (`poi_rules.poi_for_event`, pure): from one event, the world's present state, the config and the seed it
   returns a `PoiPlan` per kind that event makes: a `fall` makes ruins (the capital plus `holdings`, each with a fate from
   `tables.poi_fates`; the `sim_only` fates are returned only to a simulation) and, at `chance`, a tower or a dungeon (only a
   conquered fall); a `decisive` battle at least `min_age_years` old makes a battlefield at `chance`; an ongoing war makes
   a watchtower per `per_km_of_front` of its front, at most `max_per_event`; a succession into a devout style makes a shrine,
   whose site (`tables.poi_sites`) the previous ruler's `temper` (`tables.ruling_styles`) picks.
2. **History placement** (`story/pois.py`): events in ledger order, every draw keyed on `poi_rules.event_key` (the event's kind,
   year, realms, fallen realms, towns, location and tags), never its id, so adding or switching off other events leaves the POIs
   alone; a fall's capital ruin sits exactly on the fallen realm's
   site, holdings in the `holding_km` band; a battlefield, tower or dungeon on the nearest free cell round the event
   (`offset_km`); watchtowers on the front, on high ground; a shrine on the best cell of its site's band round the seat.
   Spacing is checked against the POIs placed so far (`min_spacing_km`, `event_spacing_km`, `kind_spacing_km`). Each POI
   carries `event_ids`, `founded` and, for a ruin, `fell`, `ruin_of` (a fall's capital ruin was a capital, its holdings a
   village, town or city by `holding_origins`, a location ruin by `origins`) and `pop` (its tier's range).
3. **Location pass** (`pipeline/pois.py`): per kind in `priority` order: count = land km² (sea for boats) over `km2_per_poi`
   times `poi.density`; eligibility (biomes, elevation, a free tile, `poi.min_footprint_land`); score = 1 + freshwater,
   coast, remoteness from settlements, wildness and remoteness from seats (the last two make towers and dungeons bandit
   country) + jitter; blue-noise pick with `min_spacing_km`. At a dawn start only `source = "both"` kinds are placed.
4. **Styles pass** (`story/poi_styles.place_styles`, last, so no earlier POI moves; none at a dawn start): the lone building
   (`homestead` kind, `source = "style"`) and the generated hamlet are placed by `tables.poi_styles` rows (farm, mill, mine,
   lodge, fishery). `style_score` (pure; `realm_id` and `road` can be overridden by a simulation) is `-inf` where the style may
   not stand (biome, height, `needs_freshwater_km` / `needs_coast_km`, the larger of its homestead plan and the tier it grows
   into, a taken tile, and for a homestead land no realm holds) and otherwise the weighted terms (fresh water, coast,
   remoteness, fertility, roughness, forest, closeness to a settlement and a road, every falloff in km) plus jitter. Count =
   suited land (score at least `min_score`) over `homestead_km2_per_poi` / `hamlet_km2_per_poi` times `poi.density`; hamlets
   only for a style that grows (`grows_into`), placed first, each keeping the tier's `spacing_km` from every settlement.
   A hamlet is `civilized` with a population from the tier range; both get `founded` from `poi.style_founded_years`.
5. **Interior seed**: each POI mints `interior_seed = blake2b(master_seed, "poi_interior", x, y)` for its lazy site plan.
6. **Potential** (`sites.potential.assign_potentials`, the stage's last step): once every POI exists, each POI with a settlement
   plan gets `potential`, the largest tier its land and room allow (never below what it is). Nothing moves, so the
   fingerprint is the same; the site plans are drawn for it.

### Stage 9f — Spurs (`roads.spurs`)

Every POI whose `connect` is true and that is not a settlement draws `roads.uncivilized_connect_prob`; a winner gets a spur
to the nearest road tile of its landmass. `connect` comes from the kind's row (a shrine's from its site row).

### Stage 10 — Naming (`pipeline/naming.py`, `naming/`)

Assigns names to all entities; region lore is gone, and the chronicle's text is rendered here:

- **Culture assignment**: each realm draws its culture from a biome-biased weighted distribution seeded on
  `(master_seed, "naming.culture", "realm", realm_id)`; a vassal keeps its own. POIs, rivers, lakes and features take the
  culture of the realm holding them, wild land and open water `common`. A POI's name is a pattern from its kind's `names`
  (`names_fallen` for a fallen realm's capital ruin, which takes the realm's name; a homestead's from its style's `names`). The island name uses the largest realm's culture.
- **Realms and relations** (`naming/polity.py`): a realm's form (name pattern and ruler styles) is a weighted draw among its
  kind's `tables.realm_forms` rows, favoured by the habitat of its land; its base word and ruler's name are made in its
  culture. A city-state is short-named after its seat. Last, each relation's reason template gets its tokens: the claimed
  or a nearby town, the river, range and sea diplomacy found near the border (`Relation.places`), and the realms' trade goods.
- **Rulers** (`name_ruler`, `name_rulers`): a title from the realm's form and a personal name in its culture, keyed on the
  realm and the reign; `Realm.ruler` is the present ruler's name.
- **Hooks** (`naming/hooks.py`): after the chronicle, each POI's `hook` and `hook_refs`: a free settlement takes its tier's
  `hooks_free` (`hooks_remnant`, naming the fallen realm, for a remnant), else the text of its first event, else a
  template from its style's `hooks_<kind>` or its row's `hooks` (`_near` too when `places.nearest_settlement` finds a
  settlement; a tier with `near_target = false`, the hamlet, is never that settlement).
- **Chronicle** (`naming/chronicle.py`): last, a fallen realm gets a culture from its ruins' biome and a name from a
  major realm's forms (a stand-in realm with a negative id keeps its streams apart; a predecessor is named the same way in its
  first child's culture), then every event's template has its
  tokens filled from the named realms, places and relations; the first letter is capitalised.
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
- **Render cache** (`render/cache.py`, explorer only). The layers in `layers.CACHEABLE` (terrain up to sites) paint a
  cell from its world position alone, so at the detail scales `RenderCache` keeps their output in chunks of
  `render.cache.chunk_cols x chunk_rows` cells of the scale's whole-world grid, drawn with a one-cell halo so neighbour
  tests (`borders`) are seamless. A pan reuses the chunks on screen and draws only the new ground in one pass; the
  remaining layers (markers, labels, compass, later anything that moves) run every frame on top. Map-scale frames are
  kept whole (`map_frames`). An overlay edit drops what was drawn; `invalidate(box)` drops the chunks near a box of
  tiles. At most `max_cells` cells are kept, least recently shown first out. Static output never uses it.

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
  The extent is scaled by a seeded jitter. A settlement, and a ruin that records what it was, is drawn from the row of its
  **potential** (`POI.potential`, see below), never of its tier or population, so growth never redraws its plan; a homestead
  that may grow is drawn on its potential's `rows_per_tile` (`geometry.resolution_row`), so it shares one cell grid with the
  hamlet it becomes. The **window** is the whole tiles that hold the extent plus `sites.margin_tiles`: a detail grid whose
  cells are plan cells.
- **Potential and the manifest** (`potential.py`, `manifest.py`, `world/manifest.py`). The largest tier a site could grow into is
  the best tier T whose `potential_land` the habitable share of land within `sites.potential.radius_km` reaches and whose
  `spacing_km` times `sites.potential.room_share` is no more than the distance to the nearest other settlement of note; it is
  never less than what the POI already is (a ruin: the tier it was; a growing homestead: the hamlet it grows into) and a tier
  without `potential_land` (the capital) is nobody's potential. `assign_potentials` stores it on every POI at the end of the
  pois stage (so room sees them all); a simulation calls `potential_tier` for a POI it mints. The plan reads that and a
  `SiteManifest` (which lots are built, the centre's tier, whether the wall stands), never the tier or population:
  `site_plan(..., manifest=None)` uses `site_manifest`, the one place that turns a settlement's tier and population into one.
- **Terrain patch** (`patch.py`). The terrain under the extent is read through the same `DetailSampler` the renderer
  uses (`sampling/terrain.py` defines land and river once), so a plan agrees exactly with the water drawn around it.
  Roads are not stored: the road bed over the extent (`sampling/roads.py`, the raster the renderer draws) is read
  into the patch, and each run of road cells meeting the extent's edge makes a **gate** (at most `sites.max_gates`).
  A layout lays the road into its grid (`streets.lay_roads`) to build round it and join doors to it, then hands it back
  (`streets.clear_roads`): the plan leaves the road's own cells void, so the one road is drawn the same inside and outside.
- **Plan faces.** `SitePlan.cells` is the **inside** (one cell per terminal cell, drawn at the site scale);
  `SitePlan.outside` is the **sky view** (map, zoom, local): each building's roof (a building kind's roof cell), solid walls (`STONE`), streets, trees.
  Outside views ignore floor and overlay. Walls in the inside are one cell thick (`WALL`) and joined into box-drawing
  lines at draw time by the 4-neighbour mask (`cells.wall_index`, `render.interior_walls`); doors are gaps.
- **Layouts** (`layout.py`, one per `layout` key; each returns `(cells, outside)` or `(cells, outside, buildings)`). `building.py` makes a rect, L or T
  footprint, subdivides it recursively with shared one-cell walls, joins rooms by a door spanning tree plus loops, adds a
  street door, assigns roles by size and furnishes them from `tables.furniture.<family>.<role>`. `settlement.py` grows an irregular town: a
  wobbling outline (stretched towards each road), a plaza, spokes from it to the outline, partial rings, lanes into any
  ground still too far from a street, then lots fitted to the free ground beside the streets (each a building whose door
  faces its street), and for walled tiers a wall along the outline with gates where spokes and the road meet it (the
  buildings of a settlement are kinds: see **Building kinds** below). **The lots are ordered**: houses are placed one by one,
  nearest the plaza first, until `manifest.houses` stand (or the `sites.settlement.fill` share of the ground is covered), and
  each lot depends only on the ones before it, so a plan with one more house is the same plan with one more lot. Every other
  per-lot draw (storeys, stairs) is keyed on the lot's position and trees are drawn per cell, so a new lot disturbs nothing
  but the ground beside it. The wall outline is fixed; it is stamped only when `manifest.walled`. `structure.py` builds dungeon (a surface gatehouse plus underground rock floors of rooms and
  corridors or caves), tower (tapering single-room floors, aligned stairs, a lookout; a watchtower is the same layout in its
  own furniture), ruin (a building with breaches, rubble, trees and partial roofs, eroded more the longer ago it fell; a ruin with a `ruin_of` is
  instead its tier's settlement plan with a fall pass: each building survives with a chance that falls with age (the
  centre building always does), a survivor is damaged (breaches, stripped furniture, cracked floor, few roofed rooms:
  `sites.ruin_damage`) and every other building is destroyed to rubble and bare ground (`sites.ruin_rubble`), the dressings
  wear back into the terrain, the wall breaks in stretches and every gate is rubble; the numbers are `ruin_standing`,
  `ruin_wall_fall` and `ruin_extent_share` on the tier's `sites.toml` row, and the single building is kept for a ruin with no
  origin or no room) and
  shrine (one walled room with an altar); the entrance faces a gate. `camp.py`, `battlefield.py` and `boat.py` are open-air
  (tents, a trampled field with debris and wrecked wagons, hull); a camp's `purpose` picks its site row (`camp_<purpose>`).
- **Building kinds** (`data/buildings.toml`, `kinds.py`). A lot holds a kind: `housing` (the house), `production`
  (farmhouse, mill, mine, lodge, fishery: the `building` of a `poi_styles` row) or `civic` (the centre of a tier). A row
  gives its `rows` and `width`, shapes, room roles, furniture family and roof look. A `structure` is a building a layout draws
  itself (tower, watchtower, gatehouse, ruin, tent, deckhouse): a label, a rank and a roof, no size. A kind's roof is a plan cell of its
  own in a reserved block (`KIND_ROOF_BASE + rank`, `world/tile.py`), so a plan stays one `uint8` array and the outside
  view shows each kind in its colour; inside, a kind is told by its rooms and furniture. **Every roof in every site is a kind's:**
  a layout roofs a building with `kinds.lay_roof`, which stamps the roof on the sky view and returns the `SiteBuilding` the
  layout lists (the explorer names it); there is no plain roof cell.
- **The centre** (`settlement._centre`, `_plot`). Every tier row names a `centre` kind (hamlet gathering point, village
  chapel, town hall, city cathedral, capital palace). The plaza is a paved square, the *reserved plot*, sized for the
  centre of the settlement's *potential* plus an apron; the centre of the manifest's tier stands in it at the plaza point,
  its door facing the busiest street, on its own random streams, and the plot is carved out of the ground the `fill` share
  counts. Swapping the centre kind (a promotion) therefore changes nothing outside the plot (the rule behind growth never
  redrawing a plan). A ruin keeps its centre as its guaranteed survivor.
- **Specialized buildings** (`surroundings.settlement_kinds`). A pure rule reads small windows of terrain round the
  settlement (fertility, forest, roughness, fresh water, sea), scores each production kind by its `suits` weights
  (`needs_tag`, `min_score`), and shares the potential's `specialized` slots (the most) by score (D'Hondt, `max_per_kind`);
  a hamlet's style kind is first. They are fixed slots: the layout places *every* kind in list order (`edge` kinds on the
  outer ground, the mill at the river bank with its wheel, the fishery beside the harbour's pier; a kind with no room leaves
  its slot to housing), stamps the first `manifest.specialized` and takes the rest back out, keeping their ground clear of
  houses and trees, so a slot's spot never depends on how many stand.
- **A homestead that grows** (`manifest.grown_from`, `plan._grown_lot`, `settlement._stamp_grown`). The hamlet's plan stamps the
  homestead's own building first, where it stood (the lot `homestead.homestead_lot` finds, moved by the difference between the
  two windows), runs the plaza and streets round it and joins its door to the nearest street; it is the hamlet's first
  specialized building. The yard's dressing is not carried over.
- **Dressings** (`data/dress.toml`, `dress.py`). A dressing has variants drawn by condition (`standing` or `ruin`) and POI
  kind: a field is full or harvested rows, or in a ruin harvested or dead. A variant is an existing cell or a look of its
  own in the dress cell block (`DRESS_BASE + rank`). In a ruin each dressing (field, clearing, spoil, pier, boats, wheel,
  supplies) is recorded as it is laid and worn by its `wear` shares: bare terrain, rubble or overgrowth.
- **Scales.** One plan per face, scaled into the cells its extent covers by `blit.sample_rect`. Where a view is coarser
  than the plan, the cell of highest `OUTSIDE_PRIORITY` wins, so a one-cell wall survives. Void is transparent. The
  world's road is drawn everywhere (roads layer, under the plans); a plan leaves its cells void and adds only lanes.
- **The site view** (explorer). Zooming in on a POI opens its site: the window drawn one plan cell per terminal cell,
  only the visible cells (a `DetailSampler` with `origin` and `shape`). The cursor is one cell `(px, py)`; the tile
  cursor follows the tile under it. Moving past the window leaves for local. Zoom steps out.
- **Floors.** Floor 0 is the ground and entry level: dungeons descend (`lowest_floor … 0`), towers rise (`0 … top`), and
  settlements rise too: each tier row has a `floors` range and the buildings nearest the plaza are the tallest. An upper
  storey is cut back (`settlement._storey_rects`, `sites.settlement.upper`): an L or T keeps its outline on the first
  storey or only one wing (a tower on the building), a rectangle loses a share of its length at one end, and the part
  cut away shows its kind roof; the stairs stand on a free floor cell of both floors. A site whose layout is in `sites.roof_layouts`
  has one more level than its storeys, the roof level (`geometry.site_roof_floor`), where every building shows as its roof
  (a settlement lays it itself; every other layout is built on its ground floor and the roof level shows that plan's `outside`,
  `plan._roof_view`). Camps (tent roofs; underneath the tent's tarp, lifted tarp ends and posts, then inset bedrolls, bare floor and a little gear) and boats (the deckhouse roof over the cabin) have
  one; a battlefield builds nothing and has none.
  `<` / `>` cycle floors inside a site or on its tiles; entering starts at floor 0.
- **Cache and overlay.** Plans are memoised per world and config in a bounded cache (`sites.cache_size`), read-only.
  Runtime edits compose on top via `Overlay.apply_interior` (copy-on-write), keyed by the site seed and floor.
- **Colour.** Plan cells take glyphs from `render.interior_glyphs` (`interior_glyphs_ascii` for ASCII) and colours from
  `render.interior_palette`; bridge cells use the deck and wall colours of `render.detail_colors`; a building kind's
  roof and a dress variant's own look take theirs from their `tables.buildings` and `tables.dress` rows (`interior_style`
  covers all 256 cell ids).

A new kind is a row in `data/sites.toml` and, if it needs a new pattern, a `@layout("name")` function registered in
`sites/` (render and explorer iterate the sites generically).

---

## Explorer (`explorer/`)

The only place that reads keys or writes the screen. `explorer.app.run` is **event driven**: it composes a
frame, diff-writes it, blocks on a key, and repeats. Before blocking it spends idle time preparing the next frames
(`explorer/prefetch.py`): the render cache's chunks round the screen (`render.cache.prefetch_screens`), then the
ground-floor plans of the sites within `render.cache.prefetch_site_km` of the cursor, one small step at a time,
stopping when a key is waiting. Once that is done an idle explorer uses no CPU.

- **Frame.** `compose_frame` builds the map for the current scale and mode (the sampler, with the camera
  still until the cursor reaches a viewport edge, then re-centred on it, about half a screen at a time
  (`controls.pan = "centre"`, one full redraw per half screen of travel), or stepped along with it (`"edge"`)), reverses the cursor's cell (its
  whole tile block at zoom and local), and pastes the info panel under it into one terminal-sized grid.
  `e` exports the map grid *without* the cursor.
- **Writer.** `DiffWriter` compares the grid with the last frame (numpy) and sends a cursor move and the
  new cells for each run of changed cells, with a style sequence only where the style changes, naming only the
  parts (bold, glyph colour, fill) that differ from the last one sent; runs and segments are found for the whole
  frame at once and colour codes are memoised. An unchanged frame writes nothing. It owns the alternate screen, the hidden cursor and line wrap, and
  restores them on exit even after an error. Colour is truecolor, 256 or none.
- **Keys.** A reader yields tokens (`termios` cbreak on POSIX with a self-pipe for resize, `msvcrt` on
  Windows); `resolve_action` maps them through the rebindable `keys` table. Any key closes the `?` help.
  Move keys already waiting (a held key's repeats) are applied together and drawn once (`reader.pending`), so the
  cursor stops when the key is let go instead of working through a backlog.
- **Testing.** The loop takes an injected key source and output stream, so the tests drive it with a
  scripted keyboard, replay the written escape codes on a tiny virtual screen, and run the real program on a
  pseudo-terminal. The Windows paths cannot be exercised on Linux.
- **Chronicle pager.** `run_chronicle` is a second, smaller loop over the same reader, writer and key table (see the chronicle
  section above); its frame is built by `compose_pager_frame` and its state is a `PagerState`.
- **Panel layout.** Every panel row has a fixed place (see the layout rule in `explorer/CLAUDE.md`): the island line, the cursor
  tile, the realm (two rows), the POI line, the hook of the point of interest (its row is reserved, blank when there is none), the
  legend (`render.legend_rows` rows, growing only when more is on screen) and, under it, the detail area: an open site's buildings,
  then in the political view only the latest events at the cursor's tile and its realm's (`render.panel_events`, as many as fit).
  The other views leave those rows to themselves. The panel reads events through `explorer/events.py` (`EventReader`;
  `ChronicleReader` reads through `world.ledger.EventLog`: the generated chronicle and, later, a simulation's events as one list).
- **History viewer.** `t` opens `explorer/history_viewer.py` on the explorer's own reader and writer, at the latest event at the
  cursor (the present when there is none), and quitting it returns to the same explorer state. `--history [YEAR]`
  (`scripts/history.sh`) runs it alone. See the territory section below.
- **Time seam.** `explorer/ticks.py`: `run(ticks=...)` takes a `TickSource` (default `NoTicks`: nothing ticks, so the loop blocks on
  keys as always). While a source is `active` the loop polls it between keys (`controls.tick_poll_seconds`) and runs the ticks
  due at the `Clock`'s speed (`p` pauses, `+` / `-` step `controls.tick_speeds`); without a source those keys only say so.
- **Restart.** `r` makes the same world again from its seed (`pipeline.generate(config, world.master_seed)`, or the injected
  `regenerate`) and resets the view, overlay, render cache and clock; the tick source's `reset(world)` lets a simulation
  forget its state.

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
