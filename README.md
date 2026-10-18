# biomegen

A seed-reproducible **procedural island generator and explorer** that runs in your terminal. It
builds a realistic island — terrain, climate, rivers and lakes, natural biomes, realms with
rulers, vassals, wars and alliances, points of interest (villages, towns, cities, capitals, towers, dungeons, ruins,
battlefields, watchtowers, shrines, camps, boats) connected by meandering roads — and lets you explore it in a colour terminal UI,
zoom in to see structure detail, and export the view to SVG/PNG.

> **Status:** The world generator and the layered renderer are in place (redesign phases 0–4; see
> `docs/redesign_plan.md`). One layer stack draws the interactive explorer, static maps, zoomed views and
> the SVG/PNG exports, so they all look alike. Every POI archetype renders an interior embedded in the
> terrain at the zoom (shell) and local (full, furnished) scales, with floor cycling for towers and dungeons.
> Settlements and politics (realms, vassals, relations and a political view with borders and war fronts) and the
> chronicle (a derived history, `--chronicle`) are in, and POIs follow that history (ruins of fallen realms, battlefields,
> watchtowers on war fronts, shrines) with a stored hook each; hamlets and lone buildings (homesteads: a farm, mill, mine,
> lodge or fishery, with no map marker) stand in the generated world; the explorer's info panel is the next phase.

---

## Install

Requires Python 3.14 or newer.

```bash
uv venv ~/.venvs/biome --python 3.14
export UV_PROJECT_ENVIRONMENT=~/.venvs/biome   # selects the environment for every uv command
uv sync --extra dev                            # runtime + dev tooling; installs biomegen editable
```

The explorer talks to the terminal directly with ANSI escape codes (no curses), on Linux, macOS and Windows 10+.
Truecolor is used where the terminal supports it (`--color` overrides the detection).

`noise` is an **optional** extra noise backend (`noise_lib`) that needs a C compiler. biomegen runs
correctly without it using the default pure-numpy `perlin` backend.

## Development checks

```bash
uv run ruff check .
uv run ruff format .
uv run mypy src/biomegen/config src/biomegen/util src/biomegen/world
```

---

## Run

```bash
uv run biomegen                                        # random island, interactive UI
uv run biomegen --seed 12345                           # reproducible island from an integer seed
uv run biomegen --seed 0xCAFE                          # hex seeds are accepted
uv run biomegen --seed "my island"                     # any string is a valid seed
uv run biomegen --config my.toml                       # override any defaults (see config.example.toml)
uv run biomegen --width 240 --height 60                # override world dimensions
uv run biomegen --noise-backend opensimplex            # use OpenSimplex noise instead of default Perlin
uv run biomegen --noise-backend value                  # use value noise (cheaper, blockier look)
uv run biomegen --seed 1 --headless                    # generate + print stats, no terminal needed
uv run biomegen --seed 1 --chronicle                    # the world's history, one dated line per event
uv run biomegen --seed 1 --chronicle --chronicle-format json   # the same as JSON, with the realms and places it names
uv run biomegen --seed 1 --history 400                  # the history viewer: the political map at the end of year 400 (a terminal)
uv run biomegen --seed 1 --start dawn --view terrain    # a young world at year 0: land only, nothing settled
uv run biomegen --seed 1 --view terrain --color none    # static map with legend, no UI
uv run biomegen --seed 1 --scale zoom --at 60,30        # a magnified part of the world (zoom or local)
uv run biomegen --seed 1 --view terrain --save map.svg  # write a map image (.svg .png .html .txt), no UI
```

Algorithm flags override the TOML config value for that run only — they do not modify any file.
The `--noise-backend` flag accepts the same strings as its config key (`terrain.noise_backend`). Run `uv run biomegen --help` for the full
list of registered choices (the optional `noise_lib` backend only appears if the C-extension is
installed).

A random seed is always echoed to stdout so every run remains reproducible.

---

## Controls (interactive)

Run `uv run biomegen` (or `scripts/run.sh`) in a terminal. There are **three view scales**: the **map**
(whole island), **zoom** (mid detail), and **local** (close detail). All three share one cursor — a
tile coordinate — and an info panel under the map shows the tile, region, point of interest and a legend.

| Key | Action |
|-----|--------|
| Arrow keys / `HJKL` | Move the cursor (pans the viewport at the edges) |
| `WASD` | Scroll the viewport, dragging the cursor if it would leave (moves the cursor on the fit map) |
| `Shift`+arrows / capital `WASD` · `HJKL` | Fast-move (`controls.fast_step` tiles at a time) |
| `Space` | Step **out** one scale: biome↔zoom, local→zoom |
| `z` | Step **in** one scale: biome→zoom→local |
| `f` | Toggle fit-to-screen ↔ 1:1 panning (map only) |
| `v` | Next view: terrain, elevation, temperature, rainfall |
| `t` | History viewer, opened at the latest event at the cursor (`q` returns here) |
| `r` | Restart from the seed (the same world, with the view reset) |
| `p` · `+` · `-` | Pause · speed up · slow down the simulation clock (nothing ticks yet) |
| `?` | Show the key help |
| `<` / `>` | Cycle floors up / down when standing on a multi-floor structure (e.g. a dungeon) |
| `e` / `E` | Export current view / whole island to `export.dir` (SVG always, PNG if Pillow present) |
| `q` / `Esc` | Quit |

> Most terminals send the same code for `Space` and `Shift`+`Space`, so a dedicated key (`z`) is
> used for the deeper zoom. Set `keys.local = " "` only if your terminal distinguishes them.

All keys are rebindable in config (see `[keys]` below).

---

## Configuration

Copy `config.example.toml`, uncomment and change only the keys you care about, and pass it with
`--config`. Every key has a built-in default — you never need a complete file.

```bash
uv run biomegen --config my.toml
```

The authoritative defaults and inline documentation are in
[`src/biomegen/config/defaults/`](src/biomegen/config/defaults/).

### Quick reference — all user-tunable options

#### `[general]`
| Key | Default | Description |
|-----|---------|-------------|
| `seed` | `0` | Master seed. `0` picks a random seed and echoes it. |

#### `[world]`
| Key | Default | Description |
|-----|---------|-------------|
| `width` | `240` | Map width in tiles |
| `height` | `60` | Map height in tiles (keep `width × size_km[1] / size_km[0] / 2` for 2:1 cells) |
| `size_mode` | `"fixed"` | `"fixed"` (reproducible) or `"auto"` (fit to current terminal) |
| `size_km` | `[6000.0, 3000.0]` | Physical map extent `[east-west, north-south]` in km |
| `center_lat` | `"seed"` | Map-centre latitude in degrees (north positive), or `"seed"` to pick one per seed |
| `center_lat_range_deg` | `[18.0, 48.0]` | Absolute latitude range used by `center_lat = "seed"` |
| `center_lon` | `0.0` | Map-centre longitude in degrees (east positive) |

#### `[compute]`
| Key | Default | Description |
|-----|---------|-------------|
| `backend` | `"scipy"` | `"scipy"` (fastest) · `"numpy"` · `"pure"` (no scipy required) |

#### `[terrain]`
| Key | Default | Description |
|-----|---------|-------------|
| `noise_backend` | `"perlin"` | `"perlin"` · `"value"` · `"opensimplex"` · `"noise_lib"` |
| `style` | `"seed"` | Terrain style row (`continents` · `pangaea` · `archipelago` · `islands`), or `"seed"` |
| `land_fraction_jitter` | `0.04` | ± per-seed jitter on the style's land fraction |
| `max_elevation_m` | `[4300.0, 7400.0]` | Range for the height of the highest summit (m) |
| `max_depth_m` | `[4500.0, 7500.0]` | Range for the depth of the deepest sea (m) |

#### `[climate]`
| Key | Default | Description |
|-----|---------|-------------|
| `offset_c` | `0.0` | Warm (+) or cool (-) the whole world, °C |
| `lapse_c_per_km` | `6.5` | Temperature drop per km of height |
| `westerly_band_deg` | `[30.0, 60.0]` | Latitudes with westerly winds (easterlies elsewhere) |

#### `[hydrology]`
| Key | Default | Description |
|-----|---------|-------------|
| `river_land_share` | `0.035` | Share of land cells (largest catchments first) that become river channel |
| `river_min_drainage_km2` | `5000.0` | Minimum wetness-weighted catchment (km²) for a river channel |
| `min_lake_area_km2` | `3000.0` | Depressions smaller than this are not lakes |
| `lake_min_depth_m` | `15.0` | Minimum standing-water depth (m) for a lake cell |
| `river_width_scale` | `0.5` | How fast rivers widen with drainage area |
| `river_max_width` | `5` | Maximum river width in tiles |

#### `[biomes]`
| Key | Default | Description |
|-----|---------|-------------|
| `bands` | 5 bands | Temperature bands (°C), each with rainfall rules (mm) and a default biome |
| `swamp_min_rain_mm` | `3000.0` | Rain above which wet lowland becomes swamp |
| `swamp_max_elevation_m` | `300.0` | Swamp only below this height |
| `beach_max_elevation_m` | `150.0` | Warm land touching the sea below this height is beach |
| `shallow_km` | `75.0` | Sea within this distance of land is shallows |
| `sea_ice_c` | `-1.8` | Sea colder than this (with noise) freezes |
| `volcano_counts` | `[0, 1, 1, 2, 2, 3]` | Volcano count, one value drawn per seed |

Relief (hills, mountains, peaks) comes from the `min_elevation_m` column of `[tables.relief.*]`.

#### `[politics]`
| Key | Default | Description |
|-----|---------|-------------|
| `city_state_far_km` | `540.0` | A city this far from every capital is likely to be a city-state (`city_state_far_chance` 0.7, else `city_state_chance` 0.25) |
| `tribe_max` / `tribe_min_area_km2` | `6` / `40000.0` | Tribes claim up to this many of the largest unclaimed areas, each at least this big |
| `claim_budget_km` | `1500.0` | How far (cost in km) a realm of strength 1 reaches over flat land |
| `river_cost` / `coastal_hop_km` / `coastal_hop_cost` | `3.0` / `60.0` / `6.0` | Extra cost of a river cell; how far from land a realm may hop over water, and at what cost |
| `vassal_area_ratio` | `2.0` | A major swears fealty only to a major at least this many times larger |
| `habitats` | dry / cold / wood | Biome groups that favour a realm name form |
| `reason_near_km` | `250.0` | A war or rivalry names a river, range or sea only within this distance of the border |

Realm kinds (strength, rural population, vassal chance), name and ruler forms, relation weights and realm colours are
in `src/biomegen/data/polity.toml`; reason texts for wars, rivalries, alliances and trade in `reasons.toml`.

#### `[poi]`
| Key | Default | Description |
|-----|---------|-------------|
| `density` | `1.0` | Multiplies every wild kind's count (one per `km2_per_poi`) and every style's count |
| `forest_biomes`, `forest_radius_km` | `forest, taiga, jungle`; `90` | The forest term of a style's score: the share of land in that radius under those biomes |
| `style_founded_years` | `homestead [5, 200]`, `hamlet [20, 400]` | How long before the present a generated homestead or hamlet was founded |

Per-kind rows (placement numbers, the events that make a kind, name forms, hooks and the simulation seams) are in
`src/biomegen/data/pois.toml`; the fates of a fallen realm's ruins and the shrine sites are its `poi_fates` and `poi_sites`.
Hamlets and lone buildings (homesteads) are placed by its `poi_styles` rows (farm, mill, mine, lodge, fishery): each style
scores the land its own way and sets how much suited land makes one.

#### `[sites]`
| Key | Default | Description |
|-----|---------|-------------|
| `size_jitter` | `0.25` | Seeded per-POI variation of a site's extent |
| `margin_tiles` | `0.5` | Terrain kept round a site's extent in the site view |
| `max_gates` | `3` | Road gates cut into a site's edge |
| `room_rows` | `[3, 6]` | Room (interior) height range in rows (widths follow `render.cell_aspect`); a building's outer size is its `rows` and `width` in `data/buildings.toml` |
| `street_gap` | `[1, 1]` | Clear ground `[columns, rows]` round each settlement building |
| `clutter_density` | `0.10` | Fraction of free floor cells furnished |
| `shape` | `"mixed"` | Outline for solid buildings: `rectangle`/`blob`/`cellular`/`drunkard`/`diamond`/`cross`/`mixed` |
| `ruin_erosion` | `0.45` | Fraction of a ruin's walls that have collapsed once it is old (`ruin_erosion_young` and `ruin_erosion_years` set how fast a new ruin gets there) |
| `ruin_damage` / `ruin_rubble` | see `config.example.toml` | How hard a ruin damages a building that survives (breaches per room, share of floor cracked, furniture stripped, rooms unroofed, at full wear) and how much of a destroyed building stays rubble |
| `kinds.*` | — | What a settlement is chosen to have: the `radius_km` of land read round it and the `saturate` value of each term (fertility, forest, hilly share, fresh water, coast) |
| `bridge_max_rows` | `6` | The widest water a settlement street will bridge |
| `settlement.*` | — | Settlement growth: `fill` (share of ground built on), `trees`, `radius`, `wobble`, `road_stretch` (outline shape), `spokes`, `rings`, `ring_gap`, `max_lanes` (street network), `wall_inset`, `lot_tries` |

Per-kind rows (layout, `extent_tiles`, `rows_per_tile`, furniture set) are in `src/biomegen/data/sites.toml`; furniture
weights in `furniture.toml`. Building kinds (house, farmhouse, mill, mine, lodge, fishery and the centre of each settlement tier: size, roof,
what suits them) are in `buildings.toml`; dressings (the wheat field with full, harvested and dead variants, and the wear a ruin gives them) in `dress.toml`.

#### `[roads]`
| Key | Default | Description |
|-----|---------|-------------|
| `pathfinder` | `"astar"` | Road router: `"astar"` · `"tcod"` · `"dijkstra"` |
| `civilized_connect_prob` | `0.9` | Probability a civilized POI is road-connected |
| `uncivilized_connect_prob` | `0.25` | Probability an uncivilized POI is road-connected |
| `meander_strength` | `0.30` | Noise-field bend added to road paths (0 = straight) |

#### `[render]`
| Key | Default | Description |
|-----|---------|-------------|
| `zoom_scale` | `4` | Zoom detail: cell height (in terminal rows) per biome tile |
| `local_rows` | `4` | Local detail: biome tiles shown vertically on screen |
| `cell_aspect` | `2.0` | Widen detail cells so world tiles read ~square |
| `blend_strength` | `0.85` | Biome boundary bleed at detail scales (0 = crisp grid) |
| `blend_scale` | `2.5` | Feature size (tiles) of the boundary-blend warp |
| `default_view` | `"fit"` | Starting biome-map view: `"fit"` · `"onetoone"` |
| `status_height` | `15` | Terminal rows reserved for the info panel |
| `panel_events` | `4` | Events the panel lists in the political view: the latest at the cursor, then its realm's latest |
| `legend_rows` | `3` | Rows the panel's legend always takes; it grows only when more is on screen |
| `views.*` | — | Layer lists per view (`layers` for the map, `detail_layers` for zoom and local) and its tint ramp |
| `ramps.*` | — | Colour ramps for the elevation, temperature and rainfall views (the political view tints by realm) |
| `markers.*` | — | Per-POI display character |
| `detail_colors.*` | — | Colours of the road bed and bridges at zoom and local |
| `realm_tint.*` / `borders.*` | — | The political view: realm colour mixing, border and war-front colours |

#### `[export]`
| Key | Default | Description |
|-----|---------|-------------|
| `dir` | `"./images"` | Output directory for exported images (created on demand) |
| `cell_px` | `12` | Tile/cell size in pixels for exported images |
| `png` | `true` | Also write a PNG alongside the SVG (needs Pillow; SVG is always written) |
| `filename_pattern` | `"{name}_{seed}_{view}"` | Output basename; `{name}` island name, `{seed}` master seed, `{view}` = `world`/`map`/`zoom`/`local` (with `-<view>` for data views) |

Exports come from the same layer stack as the screen and are **deterministic** — a given seed always
produces byte-identical SVG. The whole-island export (`E`) renders every world tile at `cell_px`; the
view export (`e`) captures the on-screen map (without the cursor) at its current scale and camera,
including any open POI interior. `--save FILE` writes the same images without the UI.


#### `[history]`
The derived history (`--chronicle`) and the territory under it. The history viewer (`--history [YEAR]`, `t` in the explorer)
shows the political map at moments of the past.

| Key | Default | Description |
|-----|---------|-------------|
| `months_per_year` | `12` | Events and territory changes carry a month 1 to this |
| `territory.expansions` | `{major [1,2], city_state [0,1], tribal [0,1], fallen [0,1]}` | Large annexations of wild land per realm |
| `territory.expansion_share` | `[0.15, 0.3]` | Share of a realm's present area one annexation takes |
| `territory.core_share` | `0.3` | Least share of its present area a realm holds when founded |
| `territory.fallen_area_km2` | `[50000, 300000]` | The land a fallen realm held when it fell |
| `territory.strips` | see `config/defaults/history.py` | Land a battle or peace moves along a front |
| `viewer.map_share` | `0.6` | Share of the width the viewer's map takes |
| `viewer.marker_years` | `30` | Events this many years back are marked (faded) on the viewer's map |

#### `[keys]`
| Key | Default | Description |
|-----|---------|-------------|
| `zoom` | `" "` | Step out a scale (Space) |
| `local` | `"z"` | Step into the deeper scale |
| `toggle_scale` | `"f"` | Toggle fit-to-screen ↔ 1:1 |
| `cycle_view` | `"v"` | Next view |
| `history` | `"t"` | History viewer at the latest event at the cursor |
| `tick_pause` · `tick_faster` · `tick_slower` | `"p"` · `"+"` · `"-"` | The simulation clock (inactive until a simulation exists) |
| `history_prev` · `history_next` | `"["` · `"]"` | History viewer: the previous / next change of the map |
| `history_prev_tile` · `history_next_tile` | `"{"` · `"}"` | History viewer opened from the explorer: the previous / next event at the selected tile |
| `history_goto` · `history_present` | `"g"` · `"\\"` | History viewer: go to a year / the present |
| `help` | `"?"` | Key help |
| `refresh` | `"r"` | Restart from the seed: the same world made again, with the view, edits and clock reset |
| `export_view` | `"e"` | Export current view |
| `export_world` | `"E"` | Export whole island |
| `quit` | `"q"` | Quit |

#### `[controls]`
| Key | Default | Description |
|-----|---------|-------------|
| `fast_step` | `8` | Tiles moved per Shift+arrow (capital WASD/HJKL) |
| `tick_speeds` | `[0.25 … 8]` | The clock speeds the faster and slower keys step through |
| `tick_poll_seconds` | `0.02` | How often the loop checks the keyboard while a simulation ticks |

#### `[tables]`
Per-name attribute tables loaded from `src/biomegen/data/*.toml`: `tables.biomes` and `tables.relief`
(`biomes.toml`: glyphs, colours, habitability, move cost, goods) and `tables.tiers` (`tiers.toml`:
settlement markers, population, spacing and density in km), plus the political tables of `polity.toml` and `reasons.toml`. Override one attribute of one row in your
config, e.g. `[tables.biomes.desert]` with `goods = "glass"`; each file documents its keys.

---

## How it works

The world is built by an ordered, fully seed-reproducible pipeline:

```
terrain → climate → hydrology → biomes → geography → settlements → roads → realms → diplomacy
         → history → pois → spurs → naming
```

All algorithms are industry-standard and most are swappable via config (see `docs/ARCHITECTURE.md`).
Reproducibility is guaranteed by `blake2b`-derived named RNG sub-streams — every stage gets its
own independent stream, so changing one stage cannot shift another's output.

For full details on algorithms and design decisions, see **[ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Build phases

- [x] Phase 0 — contracts + scaffolding (config, RNG, World/Overlay data model)
- [x] Phase 1 — utilities (noise, geometry) + tests
- [x] Phase 2 — generation core (heightmap → regions) + headless stats
- [x] Phase 3 — terminal explorer — playable map (now the ANSI explorer of redesign phase 4)
- [x] Phase 4 — POIs, meandering A\* roads + bridges, mixed-culture names
- [x] Phase 5 — detail interiors, clutter, multi-floor POIs, overlay
  - [x] Infrastructure: lazy/LRU-cached interior builders, registry, embedded detail rendering
        (zoom outline / local full interior), signed multi-floor cycling, overlay compositing
  - [x] **Dungeon** & **tower** — stacked solid buildings (descend / ascend), aligned stairs, furnishing
  - [x] **City / town / village** — multi-building settlements with streets and a plaza
  - [x] **Ruin** — eroded single-floor building (collapsed walls, rubble)
  - [x] **Camp** & **boat** — bespoke open-air tents and a planked hull on water
- [x] Phase 6 — SVG/PNG export
  - [x] Curses-free RGB colour resolver (palette-faithful, no terminal needed)
  - [x] Deterministic colour-SVG exporter; optional PNG raster via Pillow (graceful without it)
  - [x] `E` whole island (full-res) / `e` current view (biome/zoom/local) + headless `--save` (this phase's `--export` flag was replaced in redesign phase 4)
