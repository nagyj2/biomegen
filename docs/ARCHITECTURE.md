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
direct CLI flags (`--noise-backend`, `--poi-sampler`) for single-run overrides without touching any
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
    entities.py         POI / Region / River / Lake / GeoFeature dataclasses
  interiors/            Lazy, deterministic, LRU-cached POI interior builders
    grid.py             Shared toolkit: BSP partition, carving, stair shafts, walls/doors/streets,
                        furnishing scatter, registry + build cache
    shapes.py           Swappable organic outer-boundary masks (blob/cellular/drunkard/diamond/cross)
    dungeon.py          Dungeon: stacked descending rooms, aligned stairs, depth-scaled furnishing
    tower.py            Tower: stacked ascending rooms, lookout top floor, sparse quarters
    settlement.py       City/town/village: multiple walled buildings + PATH streets + plaza
    ruin.py             Ruin: a building eroded into rubble and breached walls (single floor)
    camp.py             Camp: bespoke open-air clearing — campfire, tents, wagon (no walls)
    boat.py             Boat: bespoke planked hull + deck + cargo, floating on water
  pipeline/             Ordered generation stages (see Pipeline section below)
    __init__.py         generate() orchestrator + stats()
    physical/
      terrain.py        Stage 1 — style, mountain belts, rank sea level, elevation_m, ocean, dist_to_ocean
      climate.py        Stage 2 — °C (latitude, lapse), wind moisture + rain shadow, rain_mm
      hydrology.py      Stage 3 — rivers, lakes, flow accumulation
      biomes.py         Stage 4 — biome from °C / mm / m, relief, volcanoes
      geography.py      Stage 5 — landmass_id; landmass, range, peak, lake, sea, river features
    regions.py          Stage 6 — region segmentation + colour
    poi_placement.py    Stage 7 — POI anchor placement
    poi_fields.py       Shared suitability distance fields for POI scoring
    poi_rules.py        Per-kind POI rules, eligibility masks, score arrays
    poi_sampler.py      Blue-noise / random / grid POI samplers
    civilization/
      roads.py          Stage 8 — road network + bridge POIs + per-POI road-entrance recording
    story/
      poi_interiors.py  Stage 9 — POI interior metadata (footprint/bbox/entrance; no grids)
    naming.py           Stage 10 — names and lore for all entities
  naming/
    cultures.py         Culture profiles + biome-biased culture assignment
    syllables.py        Syllable-assembly name generator
    markov.py           Order-N character Markov name generator
    forge.py            Name-generation facade (root → dressed name)
    grammar.py          Tracery-style grammar expander
    grammar_rules.toml  Lore sentence templates (machine-readable; mirrored in docs/GRAMMAR.md)
    lore.py             Region fact extraction + lore assembly
  render/               Pure frame building (no terminal I/O); layer stack shared by every output
    grid.py             CellGrid IR (glyph, fg, bg, bold arrays) and the Document / Span form for static text
    sampler.py          Sampler: how a grid cell reads the world (one cell per tile, strided viewport)
    fit.py              FitSampler: fit-to-screen map, each cell shows its block's most salient tile
    detail.py           DetailSampler: zoom and local scales, warped continuous lookup; camera helpers
    views.py            View: layer lists per scale family + tint ramp, from render.views
    colors.py           Colour maths and per-biome / relief / detail / interior lookup arrays from the tables
    scatter.py          Stable per-cell decoration keyed on tile and sub-cell
    static.py           render_static (framed map + legend) and render_detail (zoom/local grid)
    colortest.py        --color-test swatches
    layers/             terrain relief tint water clutter roads bridges interiors markers names(labels) compass
    furniture/          frame, graticule, scale bar, legend for static maps
    backends/           ansi plain html svg png (a grid or document -> text or image)
  explorer/             Interactive terminal app (the only place that reads keys or writes the screen)
    state.py            ViewState, edge-pan camera, cursor start, floor sync and cycling, scale and mode steps
    input.py            Key readers (termios / msvcrt), key tokens, rebindable key -> action table
    writer.py           ANSI diff writer: alternate screen, writes only changed runs of cells
    panel.py            Info panel (tile, region, POI, legend, controls) and the ? help overlay
    exports.py          e / E: SVG (and PNG) of the screen's map or the whole world
    app.py              compose_frame (map + cursor + panel) and the event-driven loop
tests/                  pytest suite mirroring src/: golden-world hash, RNG determinism, config, overlay, renderer, explorer …
docs/GRAMMAR.md         Naming/lore grammar reference
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
| `region_id` | int32 | 0..R-1, -1=ocean | regions |
| `poi_index` | int32 | 0..P-1, -1=none | poi_placement |
| `road` | uint8 | 0 / 1 | roads |
| `road_tier` | uint8 | 0=none, 1=trunk, 2=spur | roads |
| `dist_to_ocean` | float32 | ≥ 0 tiles (km in phase 5) | terrain |
| `flow_accum` | float64 | km², wetness-weighted catchment | hydrology |

Sparse entity lists: `pois`, `regions`, `rivers`, `lakes`, `features` (`GeoFeature`), `island_name`.

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
- `interior`: sparse `(interior_seed, floor) → {(x, y): Cell}` for POI floor layouts.

JSON-serialisable. The base biome arrays are never mutated after generation.

---

## Generation pipeline

Order is load-bearing: each stage only consumes fields produced by earlier stages, eliminating
backtracking. A **land-exists gate** wraps the cheap terrain stage: if a seed yields less than
`world.min_land_fraction` land, the seed is deterministically perturbed and terrain re-runs (up to
`world.regen_attempts` times) before the expensive downstream stages run. Terrain sets its sea level by
rank, so the gate only trips when a style's land fraction is configured below the minimum.

```
terrain → climate → hydrology → biomes → geography → regions
         → poi_placement → roads → poi_interiors → naming
```

Roads run **before** POI interiors: the road network is laid to each POI anchor first, records the
direction it arrives from on every POI, and the interiors stage then sites that POI's footprint
entrance (and biases the interior door) to the road-facing side.

### Stage 1 — Terrain (`pipeline/physical/terrain.py`)

Produces `elevation_m`, the salt ocean (`water_type`) and `dist_to_ocean` (tiles, for POI scoring until
the phase-5 rewrite). Ported from the reference `_elevation`:

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

### Stage 6 — Regions (`pipeline/regions.py`)

Groups tiles into named regions — contiguous zones of biologically similar cover:

1. **Similarity grouping**: each biome is mapped to a group (e.g. forest + jungle + taiga + swamp
   share one group, configurable in `regions.similarity_groups`).
2. **Connected components**: 4-connected components of equal group id, labelled with
   `scipy.ndimage.label` or in-house BFS.
3. **Small-region merging**: components below `min_region_size` tiles are merged into their
   largest-border neighbour, iterating to stability (max 64 passes). Processed smallest-first so
   slivers dissolve into substantial regions.
4. **Large-region splitting**: if `max_region_size` is set, oversized regions are Voronoi-split via
   farthest-point-seeded BFS until all are within the limit. Farthest-point sampling gives good
   spatial separation of the sub-region seeds.
5. **Coastal extension**: ocean tiles within `coastal_ocean_depth` steps of land are assigned to
   the nearest land region (nearest-region BFS), giving shallow coastal water a region identity for
   naming purposes.
6. **Per-region colour**: each region gets its dominant biome's palette colour ± a per-region
   `color_jitter` drawn from a seeded RNG, so adjacent same-biome regions remain visually distinct.

### Stage 7 — POI placement (`pipeline/poi_placement.py`, `poi_fields.py`, `poi_rules.py`, `poi_sampler.py`)

Places cities, towns, villages, towers, dungeons, ruin, camps, and boats:

1. **Shared suitability fields**: `freshwater_distance` and `coast_distance` are computed once.
   A `remoteness` field is updated after each civilized POI lands, so later uncivilized kinds
   naturally cluster away from settlements.
2. **Priority order**: `city → town → village → tower → dungeon → ruin → camp → boat`. Higher-value
   settlements claim the best land first; the shared spacing set prevents stacking.
3. **Scoring**: each kind defines eligibility (allowed biomes, elevation bounds) and weighting
   (freshwater affinity, coastal affinity, remoteness weight). Score = product of applicable
   weights + per-tile jitter noise. Land kinds additionally require their (max) footprint to be at
   least `poi.min_footprint_land` dry land (`poi_rules.footprint_land_fraction_mask`, a summed-area
   table over the water mask), so a structure can sit on a coast but never mostly over water; the
   interior builder then forms it *around* whatever water the footprint clips (see Stage 8 / Interiors).
   Boats (`on_water`) are exempt — they anchor on water by design.
4. **Blue-noise sampling** (default): candidate tiles are drawn from the scored distribution and
   accepted only if they are ≥ `min_spacing` tiles from all previously placed POIs (Poisson-disk
   style). Alternatives: `random` (unconstrained sampling) and `grid` (evenly spaced).
5. **Interior seed**: each POI mints a deterministic `interior_seed = blake2b(master_seed, "poi_interior", x, y)` used by the lazy interior builder (see Stage 8 and the Render layer).

### Stage 8 — Roads (`pipeline/civilization/roads.py`)

Connects POIs with meandering least-cost roads, **before** interiors so the network can shape each
POI's entrance:

1. **Landmass grouping**: `water_type != SALT` (land + rivers + lakes, but not ocean) is labelled
   with 8-connected components. Roads are only routed within one component — they cannot cross open
   ocean, and a river slicing an island does not split it for routing purposes.
2. **Connection graph**: k-nearest-neighbour candidate edges → Kruskal MST over the civilized POIs
   (the settlement backbone; falls back to all POIs if none exist) → probabilistic attachment of
   remaining POIs (civilized at `civilized_connect_prob`, uncivilized at `uncivilized_connect_prob`)
   → extra loop edges at `extra_edge_prob`. All random draws consume a per-component RNG in a fixed
   sorted edge order. Roads route to each POI's anchor (interiors set the perimeter entrance later).
3. **Routing**: A* over a per-tile cost surface. Cost factors: `base_cost` (flat ground) +
   `slope_cost_per_km × |Δelevation_m| / 1000` + `uphill_surcharge_per_km` (uphill only) + `water_cost` (cross water) +
   `mountain_cost` (high terrain). Existing road tiles are discounted by `road_discount`.
   A low-frequency noise field (`meander_strength`) bends roads organically. A `turn_cost` penalty
   reduces zigzagging. Search is bounded to a padded bounding box + `max_expansions` cap; a
   Bresenham straight-line fallback fires if A* exhausts its budget.
   - **Trunk phase**: MST + loop edges are routed first.
   - **Spur phase**: isolated POIs connect to the nearest existing road tile (not to a distant POI),
     preventing parallel-road artefacts.
4. **Bridges**: each contiguous run of water tiles a routed road crosses becomes one `bridge` POI,
   minted the moment the crossing is found. The bridge joins the two land road pieces flanking the run
   (`p0`/`p1`, stored on the POI `extra`) and its marker sits on the run tile nearest the **centre of
   that straight span**. Freshwater runs of any length are bridged; ocean runs exceeding
   `_MAX_OCEAN_BRIDGE` tiles are skipped. Mixed ocean+river runs are split at the salt/fresh boundary.
   Bridges are emergent from road×water intersections — they are not independently sampled. A
   per-run **overlap guard** (a shared set of already-spanned water tiles) prevents two roads fording
   the same spot from stacking duplicate decks — the first (trunk-phase, usually longest) bridge wins,
   so a wide ford reads as one bridge (connected straight segments), not piled-up overlapping ones.
5. **Entrance recording**: after routing, each non-bridge POI records the dominant compass direction
   the network arrives from (`extra['road_entry']`); roads from the same side collapse to one entry.
   Stage 9 turns that into the perimeter entrance and the road-facing interior door.

### Stage 9 — POI interiors (`pipeline/story/poi_interiors.py`)

Cheap, **render-only metadata** for each POI's detail-view interior — no grids are generated here.
For every POI with a configured `interiors.footprints.<kind>` it sets the **footprint** (in world
tiles, centred on the anchor) and the clamped on-map **bbox**. The actual interior **grids** are
built lazily and deterministically from `interior_seed` on first view (see Render layer → Interiors).

**Entrance + road cleanup**: because roads are already laid, this stage places `poi.entrance` on the
footprint perimeter facing `extra['road_entry']` (the interior builder biases its door to the same
side), and clears the **land** road tiles strictly inside the footprint (the 1-tile perimeter ring is
kept so the road still meets the structure; water tiles keep their flag so a bridge under a footprint
survives). The biome arrays are untouched, and the road clear is a pure function of the placed POIs,
so generation stays reproducible. POIs with no road keep `entrance` at the anchor.

**Coastal area restoration**: a footprint that clips water loses interior area to it (the builder forms
the structure around the coast). To keep coastal structures full-sized, this stage grows the footprint —
symmetrically, so the anchor stays centred — until its dry-land tile count is back to the nominal
(size-jittered) area, capped at `interiors.expand_max_factor`. Water never blocks growth (the extra coast
is carved again by the builder); other POIs do — each POI claims its footprint rectangle and every anchor
is off-limits, so a grown structure never overlaps a neighbour. POIs grow in placement (priority) order,
so higher-value settlements claim space first. Boats keep their nominal footprint (they sit on water).

### Stage 10 — Naming (`pipeline/naming.py`, `naming/`)

Assigns names and generates lore for all entities:

- **Culture assignment**: each region draws its culture from a biome-biased weighted distribution
  seeded on `(master_seed, "naming.culture", region_id)`. POIs, rivers, and lakes inherit their
  region's culture. The island name uses its largest region's culture.
- **Root generation** (per-entity RNG keyed on `(category, *stable_key)`):
  - *Syllable assembly* (default): draws `onset + nucleus + coda` from the culture's phoneme sets
    with a vowel-collision guard and syllable-boundary length cap.
  - *Markov* (optional, per category): an order-N character Markov chain trained on a small
    per-culture seed corpus generates phonotactically consistent names. Selected by
    `naming.generators.<category> = "markov"`.
- **Dressing**: roots are dressed per entity category — settlements append a culture suffix
  (`-ton`, `-vik`, `-loth`, …), dungeons/ruin/towers get evocative patterns (`Ruins of X`,
  `X Catacombs`), regions append a geographic descriptor (`Wood`, `Peaks`, `Sands`).
- **Lore**: 1–4 sentences per region drawn from a Tracery-style grammar in `grammar_rules.toml`.
  `#token#` expands to another symbol or to a pre-bound region fact (`region_name`, `biome`,
  `size`, `culture_adj`, `settlement_phrase`, `water_phrase`). Facts always have safe defaults.

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
| POI sampler | `poi.sampler` | `--poi-sampler` | `bluenoise`\* · `random` · `grid` |
| Pathfinder | `roads.pathfinder` | — | `astar`\* · `tcod` · `dijkstra` |
| Interior partition | `interiors.partition` | — | `bsp`\* · `tcod_bsp` |
| Interior shape | `interiors.shape` | — | `mixed`\* · `rectangle` · `blob` · `cellular` · `drunkard` · `diamond` · `cross` |
| Interior builder | (by POI kind) | — | `dungeon` · `tower` · `city` · `town` · `village` · `ruin` · `camp` · `boat` |
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
  zoom and local, plus an optional tint ramp (elevation, temperature, rainfall). `v` cycles them.
- **Layers** (`render/layers/`): `terrain`, `relief`, `tint`, `water`, `clutter`, `roads`, `bridges`,
  `interiors`, `markers`, `labels`, `compass`. Colours and glyphs come from `tables.biomes`, `tables.relief`,
  `tables.detail` and `tables.detail_relief` (`data/*.toml`), and the `render.*` config; none are literals.
- **Back-ends** (`render/backends/`) turn a grid or document into ANSI, plain text, HTML, SVG or PNG.
- Hot paths are numpy; the only Python loops are over POIs and road links.

**Scales and the cursor.** Three scales share one tile cursor and one camera:

- **Map**: `fit` (the whole world scaled down) or `1:1` (one cell per tile, panned). Toggle with `f`.
- **Zoom**: each tile is a `zoom_scale x (zoom_scale * cell_aspect)` block of cells.
- **Local**: the screen shows `local_rows` tiles vertically, each magnified further; furnished interiors
  appear here.

**Detail scales.** A `DetailSampler` maps each cell of a tile's `cell_w x cell_h` block to a continuous world
position (tile centres on the integers) and reads the biome, relief and river coverage through the
biome-blend warp. `terrain` draws the biome's floor glyph on every cell (a rocky floor on mountain relief),
`relief` only recolours, `clutter` scatters the `tables.detail` glyphs (denser where wetter or higher),
`water` draws river coverage, `roads` the thin bed, `bridges` the decks, `markers` one cell per tile and
`interiors` the zoom shell or local furniture. Hillshade is bilinear elevation, the same at every scale.

**Biome blending** at detail scales: each cell looks up its biome at a domain-warped world
position (`blend_strength`, `blend_scale`). The warp is a pure function of world position + seed, so
zoom and local are consistent samplings of the same blend — they look like zooms of each other.
Setting `blend_strength = 0` gives a crisp grid. Water is blended by bilinear coverage
(`water_blend_threshold`) so diagonal rivers and lakes join.

**Roads & bridges** at detail scales (the `roads` and `bridges` layers, drawn over terrain but under POI
markers and interiors): the map keeps its single-cell road glyphs, but at zoom/local roads are not
markers — they render like the rivers do.

- *Roads* are a thin meandering **bed**: a detail cell is road when its (road-warped) world position
  lies within `road_half_width` tiles of the straight line joining two 8-adjacent land-road tile
  centres. That distance test is a pure function of world position, so zoom and local are the same
  shape at different scales. The bed is `road_glyph` (`:`) in the `detail_colors.road_*` colours with small
  clutter scattered along it (`road_clutter`, plus `road_clutter_local` fine detail at the close scale). A
  small `road_warp` gives it an organic wobble; water and river cells are never drawn over (bridges carry those).
- *Bridges* are a straight **deck flanked by walls**, drawn from each bridge POI's stored span
  endpoints (`extra['p0']`/`['p1']`) at whatever real angle the crossing has — cells within
  `road_half_width` of the span (perpendicular, clamped to its length, then extended `bridge_overhang`
  tiles past each end so the deck overlaps the road bed with no gap) are the deck, a band just beyond on
  either long side is the railing (`detail_colors.deck_*` / `wall_*`). Unlike roads this draws over the
  water it spans.

### Interiors (`interiors/`, drawn by the `interiors` layer)

POIs with a registered builder get **three forms**: the map marker (with a small wall outline of the
structure on the overview), a **zoom** shell, and a **local** full interior — all anchored in world space, so panning moves seamlessly
between outside and inside (the interior is *embedded in the terrain*, not a separate screen).

- **One artifact, two samplings.** Each interior is generated once at a *canonical* resolution
  (`interiors.cells_per_tile` cells per world tile across the footprint) by the per-kind builder,
  the layer **nearest-neighbour samples** it into the footprint's block of cells (`sample_rect_array`).
  So zoom and local are coarse/fine views of the same grid, exactly like the biome blend. At **zoom**
  the building shell is drawn (`ZOOM_VISIBLE`: walls and floor, furniture shown as floor); at **local**
  every non-`VOID` cell is drawn — the full furnished interior; on the **map** only `STRUCTURAL` cells
  (walls/doors/stairs) of the top floor, leaving the marker cell clear. `VOID` is transparent, so terrain shows through gaps.
- **Lazy + cached + deterministic.** `build_interior(poi, floor, config, world=None)` dispatches to
  the kind's builder, memoised by `functools.lru_cache` on the cheap scalar inputs; the cached base
  array is read-only. Everything is a pure function of `interior_seed` (+ floor), so a POI regenerates
  identically every open. Runtime edits compose on top via `Overlay.apply_interior` (copy-on-write).
- **Terrain-aware (forms around water).** When `world` is supplied (both render paths do), the builder
  receives a *buildable* cell mask — the footprint's water tiles upsampled to canonical resolution and
  pulled back by `interiors.coast_margin` cells — packed into the cache key (`InteriorCtx.land_mask_bytes`,
  so it stays deterministic). Solid builders confine their outline to the largest dry blob
  (`build_room_structure`); settlements drop only buildings that fit on land; the camp clips its
  clearing. The eroded margin stays `VOID`, so a strip of bare biome floor reads as a little coast.
  An inland POI's mask is empty (`b""`) → it builds exactly as before and shares that cache entry.
  As a hard backstop, the `interiors` layer never draws an interior cell
  over a water tile — **except `boat`**, which floats on water by design. So no structure is ever
  stamped over water even if a corridor clips the shore; bridges have no builder and are unaffected.
- **Signed floors, both directions.** **Floor 0 is always the ground/entry level** (set by
  `poi_rules.floors_for`): dungeons descend (`lowest_floor … 0`), towers rise (`0 … top`). Stairs sit
  on **aligned shafts** fixed across floors (seeded floor-independently) so floors stack vertically;
  floor 0 gets the exterior DOOR, the far end only the stairs back. `grid.floor_links` /
  `grid.stamp_circulation` encode this once for every stacked builder. `<` / `>` cycle floors when the
  cursor is on the footprint (`explorer.state.cycle_floor`); `sync_floor` enters at floor 0.
- **Colour.** Interior cells are filled with `render.interior_palette` (bridge cells with the deck and wall
  colours of `render.detail_colors`); the glyph is the same colour lightened by `render.interior_fg_scale`.

**Every archetype except `bridge` has a builder**, all sharing the `grid.py` toolkit:

| Builder | Pattern | Notes |
|---------|---------|-------|
| `dungeon` / `tower` | Stacked solid building | descend / ascend from floor 0; aligned stairs; depth-scaled loot vs. sparse quarters + lookout |
| `city` / `town` / `village` | Multi-building settlement | one builder; BSP plots → walled buildings, PATH streets + plaza, terrain between; a road-connected settlement opens a road-facing door in its edge-most building + a street to the plaza |
| `ruin` | Eroded single-floor building | `interiors.ruin_erosion` collapses walls to gaps and cracks floor to rubble |
| `camp` | Bespoke open-air | cleared FLOOR patch + campfire + tents + wagon, no walls (the clearing is what reads at zoom) |
| `boat` | Bespoke hull on water | planked WALL hull around a FLOOR deck + cabin + cargo; VOID around it shows the water |

A new archetype plugs in the same way: drop `interiors/<kind>.py` with an
`@register_interior("<kind>")` builder, add a footprint entry, import it in `interiors/__init__.py` —
no render or pipeline changes (both iterate the registry generically).

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
