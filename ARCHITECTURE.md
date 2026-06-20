# biomegen — architecture & code-map

This document is the **map of the codebase, written for both humans and AI assistants**. Read it
first: it explains where everything lives, how data flows, and the rules that keep generation
reproducible. Each module also carries a docstring describing its own role in more detail.

---

## Mental model

`main.py` parses CLI args, loads config, resolves a seed, and calls `biomegen.pipeline.generate`,
which runs a fixed sequence of stages that fill an immutable `World` (parallel numpy arrays per
tile). Runtime/gameplay changes never touch that base — they go into a separate `Overlay` that is
composited on read. The `render` layer draws the composited world with curses. Every interchangeable
algorithm is looked up from a `Registry` by a string key read from config, so swapping algorithms is
normally a config change, not a code change. A subset of algorithm families is also exposed as
direct CLI flags (`--noise-backend`, `--poi-sampler`) for single-run overrides without touching any
file.

---

## Directory map

```
main.py                 CLI entry (argparse → config → generate → curses app | headless | preview)
biomegen/
  registry.py           Generic name→implementation registry (the swappability mechanism)
  config/
    defaults.py         Authoritative defaults — every tunable key lives here
    loader.py           TOML deep-merge onto defaults
    model.py            Frozen Config, dotted-path get(), section() sub-view
    validate.py         Coerce/clamp values on load
  util/
    rng.py              DETERMINISM ANCHOR — blake2b sub-stream derivation; never builtin hash()
    noise.py            Noise backends (Perlin, Value, OpenSimplex, noise_lib) + fBm + domain warp
    geometry.py         Neighbours, connected-components, distance transforms, A*
  world/
    tile.py             Biome / WaterType / Cell enums + TileView accessor
    world.py            Immutable World (parallel numpy arrays) + fingerprint()
    overlay.py          Mutable Overlay (runtime edits, composited at read time)
    entities.py         POI / Region / River / Lake dataclasses
  pipeline/             Ordered generation stages (see Pipeline section below)
    __init__.py         generate() orchestrator + stats()
    heightmap.py        Stage 1 — elevation
    island_mask.py      Stage 2 — ocean/land classification + dist_to_ocean
    climate.py          Stage 3 — temperature + moisture fields
    hydrology.py        Stage 4 — rivers, lakes, flow accumulation
    biomes.py           Stage 5 — Whittaker biome classification
    regions.py          Stage 6 — region segmentation + colour
    poi_placement.py    Stage 7 — POI anchor placement
    poi_fields.py       Shared suitability distance fields for POI scoring
    poi_rules.py        Per-kind POI rules, eligibility masks, score arrays
    poi_sampler.py      Blue-noise / random / grid POI samplers
    roads.py            Stage 8 — road network + bridge POIs
    naming.py           Stage 9 — names and lore for all entities
  naming/
    cultures.py         Culture profiles + biome-biased culture assignment
    syllables.py        Syllable-assembly name generator
    markov.py           Order-N character Markov name generator
    forge.py            Name-generation facade (root → dressed name)
    grammar.py          Tracery-style grammar expander
    grammar_rules.toml  Lore sentence templates (machine-readable; mirrored in docs/GRAMMAR.md)
    lore.py             Region fact extraction + lore assembly
  render/
    palette.py          Colour authority — truecolor / 256-color / basic / mono capability ladder
    glyphs.py           Glyph lookup tables from config
    state.py            ViewState + camera helpers (edge-pan, center-cam)
    map_view.py         Biome-map frame construction (fit-to-screen or 1:1)
    zoom_view.py        Detail-view frame construction (zoom + local scales) with biome blending
    status.py           Status panel + legend rendering
    preview.py          ASCII preview (no curses — usable headlessly)
    input.py            Key-binding resolution
    app.py              Curses bootstrap + main event loop
tests/                  pytest suite: golden-world hash, RNG determinism, config, overlay, UI, …
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
| `elevation` | float64 | [0, 1] | heightmap |
| `temperature` | float64 | [0, 1] | climate |
| `moisture` | float64 | [0, 1] | climate + hydrology |
| `biome` | uint8 | `Biome` enum int | island_mask, hydrology, biomes |
| `water_type` | uint8 | `WaterType` enum int | island_mask, hydrology |
| `region_id` | int32 | 0..R-1, -1=ocean | regions |
| `poi_index` | int32 | 0..P-1, -1=none | poi_placement |
| `road` | uint8 | 0 / 1 | roads |
| `road_tier` | uint8 | 0=none, 1=trunk, 2=spur | roads |
| `dist_to_ocean` | float32 | ≥ 0 | island_mask |
| `flow_accum` | float64 | ≥ 0 | hydrology |

Sparse entity lists: `pois`, `regions`, `rivers`, `lakes`, `island_name`.

`World.fingerprint()` hashes all fields via blake2b for the golden-world test.

### Overlay (`world/overlay.py`)

The **only** mutable runtime state. Two layers composited over the immutable base at read time:

- `surface`: sparse `(x, y) → attrs dict` for gameplay edits on the map surface.
- `interior`: sparse `(interior_seed, floor) → {(x, y): Cell}` for POI floor layouts.

JSON-serialisable. The base biome arrays are never mutated after generation.

---

## Generation pipeline

Order is load-bearing: each stage only consumes fields produced by earlier stages, eliminating
backtracking. A **land-exists gate** wraps the first two cheap stages: if a seed yields less than
`world.min_land_fraction` land, the seed is deterministically perturbed and those stages re-run (up
to `world.regen_attempts` times) before the expensive downstream stages run.

```
heightmap → island_mask → climate → hydrology → biomes → regions
         → poi_placement → roads → naming
```

### Stage 1 — Heightmap (`pipeline/heightmap.py`)

Produces `world.elevation` [0, 1]. Algorithm:

1. **fBm terrain**: sum `octaves` of the configured noise backend at geometrically growing
   frequencies (`lacunarity`) and shrinking amplitudes (`persistence`). The result is normalised to
   [0, 1].
2. **Domain warp** (Inigo Quilez): before sampling, offset the coordinate grid by two decorrelated
   low-frequency fBm fields scaled by `warp_strength`. This bends straight noise contours into
   organic, meandering coastlines and ridgelines without adding extra octaves.
3. **Island mask**: a radial falloff centred on the map (falloff `= 1 - r^falloff_power`) is shaped
   by two independent noise fields:
   - *Coast detail*: medium-frequency noise, weighted by `(1 - core)` so it only acts near the
     shoreline. The interior stays solid; the outline gets peninsulas, bays, and gulfs.
   - *Archipelago*: low-frequency, positive-only lobes added outside the core, raising patches of
     ocean into small satellite islands.
4. **Blending**: `elevation = mask × (land_floor + (1 - land_floor) × terrain)`. A small
   `land_floor` lifts the interior gently so the main island stays solid and above sea level.
5. **Redistribution**: an optional exponent reshapes the elevation distribution (values > 1 push
   terrain toward the extremes — more flatlands and more mountains, fewer mid-slopes).

Config keys: `terrain.*` (noise_backend, octaves, persistence, lacunarity, scale, warp_strength,
falloff_power, land_floor, coast_detail, archipelago, redistribution, …).

### Stage 2 — Island mask (`pipeline/island_mask.py`)

Classifies tiles as ocean, interior water, or land and computes `dist_to_ocean`:

- **Ocean**: water tiles 4-connected to the map border (saltwater, edge-connected = open sea).
- **Interior water**: water tiles not connected to the border (provisionally freshwater lakes;
  hydrology refines them).
- **Land**: tiles at or above `world.sea_level`.
- `dist_to_ocean`: exact Euclidean distance transform from every tile to the nearest ocean tile
  (scipy `distance_transform_edt`; in-house BFS fallback). Used by climate, biomes, and hydrology.

### Stage 3 — Climate (`pipeline/climate.py`)

Produces `world.temperature` and base `world.moisture`.

- **Temperature**: a smooth, physically motivated field — no noise. A latitude gradient (warm equator
  / cold poles, controlled by `climate.orientation`) minus an elevation lapse rate (`lapse_rate ×
  normalised height above sea level`).
- **Moisture**: a statistically independent low-frequency fBm field (deliberately decorrelated from
  elevation so mountains are not automatically wet) with an optional coastal bonus that decays
  exponentially with `dist_to_ocean`. A `moisture_redistribution` exponent biases the map drier
  (> 1) for more biome variety.

### Stage 4 — Hydrology (`pipeline/hydrology.py`)

Standard GIS surface-hydrology pipeline (RichDEM / GRASS GIS family):

1. **Priority-flood** (Barnes, Lehman & Soille 2014): flood inward from the ocean boundary, raising
   each pit to its spill level. A monotonic counter breaks ties deterministically. O(n log n), uses a
   min-heap. Yields the depression-free `filled` surface and a `order` array (processing rank, used
   as a flat tie-breaker on flats).
2. **D8 flow directions**: each cell drains to its lowest 8-connected neighbour on the filled surface
   (key = `filled + order × 1e-9`). Vectorised via padded array shifts.
3. **Flow accumulation**: process cells high-to-low (a topological sweep guaranteed by the fill
   order), pushing unit drainage area to each cell's receiver. The result approximates upstream
   catchment area.
4. **Lake extraction**: cells where `filled - elevation` exceeds `lake_min_depth` are standing water.
   4-connected components of sufficient size (`min_lake_size`) become `Lake` entities.
5. **River extraction**: cells with `flow_accum ≥ accumulation_threshold` on land become channel
   thalwegs. Sources (cells with no upstream channel neighbours) are sorted by accumulation and
   traced downstream, yielding `River` paths.
6. **River widening**: each thalweg cell gets a radius `= f(accum / threshold)`, capped at
   `river_max_width`. Land neighbours within that radius are converted to river tiles — headwaters
   stay 1 tile wide; great rivers near the sea span several tiles.
7. **Freshwater moisture bonus**: land near fresh water gets an exponential moisture boost
   (`moisture_strength × exp(-dist / moisture_radius)`), making river valleys biome-greener.

### Stage 5 — Biomes (`pipeline/biomes.py`)

Whittaker-style temperature × moisture lookup, bracketed by elevation/coastal overrides:

1. **Matrix lookup**: temperature and moisture are bucketed into bands (`temp_bands`,
   `moisture_bands`) and indexed into a configurable 2-D matrix of biome names.
2. **Elevation overrides** (applied in ascending priority — later wins):
   - Beach: low elevation AND within `beach_dist` of ocean.
   - Mountain: elevation ≥ `mountain_min`.
   - Snow: elevation ≥ `snow_min`, or cold (`temp ≤ snow_temp`) at high elevation.
3. **Majority-vote smoothing**: one or more passes replace each land tile with the most common biome
   in its 3×3 neighbourhood, removing salt-and-pepper speckle at band edges. Vectorised via padded
   shifts.

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

Places cities, towns, villages, towers, dungeons, ruins, camps, and boats:

1. **Shared suitability fields**: `freshwater_distance` and `coast_distance` are computed once.
   A `remoteness` field is updated after each civilized POI lands, so later uncivilized kinds
   naturally cluster away from settlements.
2. **Priority order**: `city → town → village → tower → dungeon → ruins → camp → boat`. Higher-value
   settlements claim the best land first; the shared spacing set prevents stacking.
3. **Scoring**: each kind defines eligibility (allowed biomes, elevation bounds) and weighting
   (freshwater affinity, coastal affinity, remoteness weight). Score = product of applicable
   weights + per-tile jitter noise.
4. **Blue-noise sampling** (default): candidate tiles are drawn from the scored distribution and
   accepted only if they are ≥ `min_spacing` tiles from all previously placed POIs (Poisson-disk
   style). Alternatives: `random` (unconstrained sampling) and `grid` (evenly spaced).
5. **Interior seed**: each POI mints a deterministic `interior_seed = blake2b(master_seed, "poi_interior", x, y)` used by the lazy Phase-5 interior builder.

### Stage 8 — Roads (`pipeline/roads.py`)

Connects POIs with meandering least-cost roads:

1. **Landmass grouping**: `water_type != SALT` (land + rivers + lakes, but not ocean) is labelled
   with 8-connected components. Roads are only routed within one component — they cannot cross open
   ocean, and a river slicing an island does not split it for routing purposes.
2. **Connection graph**: k-nearest-neighbour candidate edges → Kruskal MST over the civilized POIs
   (the settlement backbone; falls back to all POIs if none exist) → probabilistic attachment of
   remaining POIs (civilized at `civilized_connect_prob`, uncivilized at `uncivilized_connect_prob`)
   → extra loop edges at `extra_edge_prob`. All random draws consume a per-component RNG in a fixed
   sorted edge order.
3. **Routing**: A* over a per-tile cost surface. Cost factors: `base_cost` (flat ground) +
   `slope_cost × |Δelevation|` + `uphill_surcharge` (uphill only) + `water_cost` (cross water) +
   `mountain_cost` (high terrain). Existing road tiles are discounted by `road_discount`.
   A low-frequency noise field (`meander_strength`) bends roads organically. A `turn_cost` penalty
   reduces zigzagging. Search is bounded to a padded bounding box + `max_expansions` cap; a
   Bresenham straight-line fallback fires if A* exhausts its budget.
   - **Trunk phase**: MST + loop edges are routed first.
   - **Spur phase**: isolated POIs connect to the nearest existing road tile (not to a distant POI),
     preventing parallel-road artefacts.
4. **Bridges**: every contiguous run of water tiles a routed road crosses becomes one `bridge` POI
   at the run's midpoint. Freshwater runs of any length are bridged; ocean runs exceeding
   `_MAX_OCEAN_BRIDGE` tiles are skipped. Mixed ocean+river runs are split at the salt/fresh
   boundary. Bridges are emergent from road×water intersections — they are not independently sampled.

### Stage 9 — Naming (`pipeline/naming.py`, `naming/`)

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
  (`-ton`, `-vik`, `-loth`, …), dungeons/ruins/towers get evocative patterns (`Ruins of X`,
  `X Catacombs`), regions append a geographic descriptor (`Wood`, `Peaks`, `Sands`).
- **Lore**: 1–4 sentences per region drawn from a Tracery-style grammar in `grammar_rules.toml`.
  `#token#` expands to another symbol or to a pre-bound region fact (`region_name`, `biome`,
  `size`, `culture_adj`, `settlement_phrase`, `water_phrase`). Facts always have safe defaults.

---

## Swappable algorithms (Registry pattern)

Each algorithm family has a `Registry` instance. To add a new algorithm: implement it, decorate
with `@REGISTRY.register("name")`, and reference `"name"` in the config. No call-site edits needed.

The **CLI flag** column lists flags accepted by `main.py` for single-run overrides (no config file
needed). All other families are changed via their config key.

| Family | Config key | CLI flag | Built-in choices |
|--------|-----------|----------|-----------------|
| Noise backend | `terrain.noise_backend` | `--noise-backend` | `perlin`\* · `value` · `opensimplex` · `noise_lib`† |
| Biome classifier | `biomes.classifier` | — | `whittaker` |
| Flow model | `hydrology.flow_model` | — | `d8` · `dinf` |
| POI sampler | `poi.sampler` | `--poi-sampler` | `bluenoise`\* · `random` · `grid` |
| Pathfinder | `roads.pathfinder` | — | `astar`\* · `tcod` · `dijkstra` |
| Interior partition | `interiors.partition` | — | `bsp`\* · `tcod_bsp` |
| Spatial compute | `compute.backend` | — | `scipy`\* · `numpy` · `pure` |

\* default   † optional C-extension; unavailable if not installed (no C compiler needed for defaults)

CLI flags use the same selector strings as config. A flag takes precedence over both the TOML
overlay and the built-in default for that run only.

---

## Render layer

Three view scales share one biome-tile cursor and one camera:

- **Biome map** (`map_view.py`): whole-island overview. `fit` mode downsamples the world to fit the
  terminal; `1:1` panning mode shows one tile per cell. Toggle with `f`.
- **Zoom** (`zoom_view.py`): each biome tile is rendered as a `zoom_scale × (zoom_scale × cell_aspect)`
  block of detail cells. The cursor tile is outlined.
- **Local** (`zoom_view.py`, same renderer): the screen shows `local_rows` biome tiles vertically,
  each magnified further. POI interiors will render only at this scale (Phase 5).

**Biome blending** at detail scales: each cell looks up its biome at a domain-warped world
position (`blend_strength`, `blend_scale`). The warp is a pure function of world position + seed, so
zoom and local are consistent samplings of the same blend — they look like zooms of each other.
Setting `blend_strength = 0` gives a crisp grid.

**Colour capability ladder** (`palette.py`): the palette detects terminal capability and uses the
highest available mode — truecolor (`init_color` with per-region RGB), 256-color, 8-color, or
monochrome — falling back gracefully.

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
