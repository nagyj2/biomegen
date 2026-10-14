# biomegen

A seed-reproducible **procedural island generator and explorer** that runs in your terminal. It
builds a realistic island — terrain, climate, rivers and lakes, natural biomes grouped into named
regions with generated lore, points of interest (villages, towns, cities, towers, dungeons, ruin,
camps, boats) connected by meandering roads — and lets you explore it with a colored curses UI,
zoom in to see structure detail, and export the view to SVG/PNG.

> **Status:** Phases 0–6 are complete and playable. Every POI archetype (dungeon, tower, city, town,
> village, ruin, camp, boat) renders an interior embedded in the terrain at the zoom (outline) and
> local (full, furnished) scales, with multi-floor cycling for dungeons and towers. The whole island
> or the current view can be exported to colour SVG (and PNG, if Pillow is installed) from the UI
> (`e` / `E`) or headlessly (`--export`). See the phase checklist below.

---

## Install

Requires Python 3.14 or newer.

```bash
uv venv ~/.venvs/biome --python 3.14
export UV_PROJECT_ENVIRONMENT=~/.venvs/biome   # selects the environment for every uv command
uv sync --extra dev                            # runtime + dev tooling; installs biomegen editable
```

`windows-curses` is installed automatically on Windows (the `curses` module is stdlib on Linux/macOS).

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
uv run biomegen --poi-sampler random                   # random POI placement instead of default blue-noise
uv run biomegen --poi-sampler grid                     # evenly-spaced POI placement
uv run biomegen --seed 1 --headless                    # generate + print stats, no terminal needed
uv run biomegen --seed 1 --preview                     # ASCII biome map, no curses
uv run biomegen --seed 1 --preview-zoom                # ASCII mid-detail (zoom) view
uv run biomegen --seed 1 --preview-local               # ASCII close-detail (local) view
uv run biomegen --seed 1 --export world                # write a full-island image to ./images, no UI
uv run biomegen --seed 1 --export view                 # write the biome map to ./images, no UI
```

Algorithm flags override the TOML config value for that run only — they do not modify any file.
The `--noise-backend` and `--poi-sampler` flags accept the same strings as their corresponding
config keys (`terrain.noise_backend` and `poi.sampler`). Run `uv run biomegen --help` for the full
list of registered choices (the optional `noise_lib` backend only appears if the C-extension is
installed).

A random seed is always echoed to stdout so every run remains reproducible.

---

## Controls (interactive)

There are **three view scales**: the **biome map** (whole island), **zoom** (mid detail), and
**local** (close detail). All three share one cursor — a biome-tile coordinate.

| Key | Action |
|-----|--------|
| Arrow keys / `WASD` / `HJKL` | Move the cursor (pans the viewport at the edges) |
| `Shift`+arrows / capital `WASD` · `HJKL` | Fast-move (`controls.fast_step` tiles at a time) |
| `Space` | Step **out** one scale: biome↔zoom, local→zoom |
| `z` | Step **in** one scale: biome→zoom→local |
| `f` | Toggle fit-to-screen ↔ 1:1 panning (biome map only) |
| `r` | Regenerate the world with a fresh random seed |
| `<` / `>` | Cycle floors up / down when standing on a multi-floor structure (e.g. a dungeon) |
| `e` / `E` | Export current view / whole island to `export.dir` (SVG always, PNG if Pillow present) |
| `q` | Quit |

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
| `width` | `192` | Map width in tiles |
| `height` | `75` | Map height in tiles |
| `sea_level` | `0.40` | Normalised elevation below which tiles are ocean/water |
| `size_mode` | `"fixed"` | `"fixed"` (reproducible) or `"auto"` (fit to current terminal) |
| `scale_x` | `1.0` | Stretch all terrain features along X (> 1 = wider landforms) |
| `scale_y` | `1.0` | Stretch all terrain features along Y |
| `size_km` | `[6000.0, 3000.0]` | Physical map extent `[east-west, north-south]` in km |
| `center_lat` | `35.0` | Map-centre latitude in degrees (north positive) |
| `center_lon` | `0.0` | Map-centre longitude in degrees (east positive) |

#### `[compute]`
| Key | Default | Description |
|-----|---------|-------------|
| `backend` | `"scipy"` | `"scipy"` (fastest) · `"numpy"` · `"pure"` (no scipy required) |

#### `[terrain]`
| Key | Default | Description |
|-----|---------|-------------|
| `noise_backend` | `"perlin"` | `"perlin"` · `"value"` · `"opensimplex"` · `"noise_lib"` |
| `octaves` | `7` | fBm octave count (more = finer terrain detail) |
| `persistence` | `0.54` | Amplitude falloff per octave (higher = rougher terrain) |
| `lacunarity` | `2.0` | Frequency growth per octave |
| `scale` | `58.0` | Base feature size in tiles (larger = broader landforms) |
| `warp_strength` | `0.55` | Domain-warp magnitude — higher gives more meandering coasts |
| `falloff_power` | `2.2` | Island falloff steepness — lower = broader/larger main island |
| `land_floor` | `0.18` | Interior elevation lift — keeps the main island solid |
| `coast_detail` | `0.42` | Coastline irregularity: peninsulas, bays, gulfs (0 = round) |
| `archipelago` | `0.42` | Satellite island strength (0 = single island) |
| `redistribution` | `1.0` | Post-normalisation exponent (> 1 pushes heights toward extremes) |

#### `[climate]`
| Key | Default | Description |
|-----|---------|-------------|
| `orientation` | `"equator-center"` | `"equator-center"` (warm middle) · `"north-pole-top"` |
| `lapse_rate` | `0.55` | Temperature drop with elevation (higher = colder mountains) |
| `moisture_redistribution` | `1.5` | > 1 biases the map drier (more desert/savanna) |
| `coastal_bias` | `0.10` | Extra moisture near the coast |

#### `[hydrology]`
| Key | Default | Description |
|-----|---------|-------------|
| `flow_model` | `"d8"` | `"d8"` or `"dinf"` |
| `accumulation_threshold` | `55` | Minimum upstream area to form a river channel |
| `min_lake_size` | `5` | Depression pools below this tile count are not lakes |
| `river_width_scale` | `0.5` | How fast rivers widen with drainage area |
| `river_max_width` | `5` | Maximum river width in tiles |

#### `[biomes]`
| Key | Default | Description |
|-----|---------|-------------|
| `classifier` | `"whittaker"` | Biome classification algorithm |
| `beach_max` | `0.45` | Max elevation for a tile to be eligible for beach |
| `mountain_min` | `0.76` | Elevation above which land becomes bare mountain |
| `snow_min` | `0.88` | Elevation above which land is permanent snow |

#### `[regions]`
| Key | Default | Description |
|-----|---------|-------------|
| `min_region_size` | `22` | Regions below this tile count are merged into neighbours |
| `max_region_size` | `100` | Regions above this are split (0 = no limit) |
| `color_jitter` | `28` | ±RGB jitter per region so same-biome regions look distinct |

#### `[poi]`
| Key | Default | Description |
|-----|---------|-------------|
| `sampler` | `"bluenoise"` | `"bluenoise"` · `"random"` · `"grid"` |
| `types.*` | — | Per-kind rules: `count`, `min_spacing`, `biomes`, `elevation_min/max`, `floors` |

#### `[interiors]`
| Key | Default | Description |
|-----|---------|-------------|
| `partition` | `"bsp"` | Interior room generator: `"bsp"` · `"tcod_bsp"` |
| `cells_per_tile` | `6` | Canonical interior resolution — detail cells per world tile |
| `room_min` / `room_max` | `4` / `10` | Min/max room side in interior cells |
| `clutter_density` | `0.10` | Fraction of free interior cells furnished (rubble/barrels/chests) |
| `size_jitter` | `0.4` | Per-POI footprint size variation (structures of a kind spawn larger/smaller) |
| `ruin_erosion` | `0.45` | Fraction of a ruin's walls that collapse to gaps / floor that cracks to rubble |
| `shape` | `"mixed"` | Outer-boundary shape for solid buildings (dungeon/tower/ruin): `rectangle`/`blob`/`cellular`/`drunkard`/`diamond`/`cross`/`mixed` |
| `footprints.*` | per-kind | Interior footprint in world tiles `[w, h]`, centred on the anchor |

#### `[roads]`
| Key | Default | Description |
|-----|---------|-------------|
| `pathfinder` | `"astar"` | Road router: `"astar"` · `"tcod"` · `"dijkstra"` |
| `civilized_connect_prob` | `0.9` | Probability a civilized POI is road-connected |
| `uncivilized_connect_prob` | `0.25` | Probability an uncivilized POI is road-connected |
| `meander_strength` | `0.30` | Noise-field bend added to road paths (0 = straight) |
| `bridges` | `true` | Place a bridge POI wherever a road must cross a river |

#### `[render]`
| Key | Default | Description |
|-----|---------|-------------|
| `zoom_scale` | `5` | Zoom detail: cell height (in terminal rows) per biome tile |
| `local_rows` | `4` | Local detail: biome tiles shown vertically on screen |
| `cell_aspect` | `2.0` | Widen detail cells so world tiles read ~square |
| `blend_strength` | `0.85` | Biome boundary bleed at detail scales (0 = crisp grid) |
| `blend_scale` | `2.5` | Feature size (tiles) of the boundary-blend warp |
| `default_view` | `"fit"` | Starting biome-map view: `"fit"` · `"onetoone"` |
| `status_height` | `12` | Terminal rows reserved for the status/legend panel |
| `try_truecolor` | `true` | Attempt per-region RGB colour where the terminal supports it |
| `palette.*` | — | Biome RGB base colours (0-255) |
| `glyphs.*` | — | Per-biome display character |
| `markers.*` | — | Per-POI/road display character |

#### `[export]`
| Key | Default | Description |
|-----|---------|-------------|
| `dir` | `"./images"` | Output directory for exported images (created on demand) |
| `cell_px` | `12` | Tile/cell size in pixels for exported images |
| `png` | `true` | Also write a PNG alongside the SVG (needs Pillow; SVG is always written) |
| `filename_pattern` | `"{name}_{seed}_{view}"` | Output basename; `{name}` island name, `{seed}` master seed, `{view}` = `world`/`biome`/`zoom`/`local` |

Exports are colour-faithful to the TUI (same region/biome/interior palette) and **deterministic** —
a given seed always produces byte-identical SVG. The whole-island export (`E` / `--export world`)
renders every world tile at `cell_px`; the view export (`e`) captures the on-screen frame at its
current scale and camera, including any open POI interior.

#### `[keys]`
| Key | Default | Description |
|-----|---------|-------------|
| `zoom` | `" "` | Step out a scale (Space) |
| `local` | `"z"` | Step into the deeper scale |
| `toggle_scale` | `"f"` | Toggle fit-to-screen ↔ 1:1 |
| `refresh` | `"r"` | Regenerate the world |
| `export_view` | `"e"` | Export current view |
| `export_world` | `"E"` | Export whole island |
| `quit` | `"q"` | Quit |

#### `[controls]`
| Key | Default | Description |
|-----|---------|-------------|
| `fast_step` | `8` | Tiles moved per Shift+arrow (capital WASD/HJKL) |

---

## How it works

The world is built by an ordered, fully seed-reproducible pipeline:

```
heightmap → island_mask → climate → hydrology → biomes → regions
         → poi_placement → roads → poi_interiors → naming
```

All algorithms are industry-standard and most are swappable via config (see `docs/ARCHITECTURE.md`).
Reproducibility is guaranteed by `blake2b`-derived named RNG sub-streams — every stage gets its
own independent stream, so changing one stage cannot shift another's output.

For full details on algorithms and design decisions, see **[ARCHITECTURE.md](docs/ARCHITECTURE.md)**.
The naming and lore grammar is documented in **[docs/GRAMMAR.md](docs/GRAMMAR.md)**.

---

## Build phases

- [x] Phase 0 — contracts + scaffolding (config, RNG, World/Overlay data model)
- [x] Phase 1 — utilities (noise, geometry) + tests
- [x] Phase 2 — generation core (heightmap → regions) + headless stats
- [x] Phase 3 — curses TUI — playable biome-map explorer
- [x] Phase 4 — POIs, meandering A\* roads + bridges, mixed-culture names & region lore
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
  - [x] `E` whole island (full-res) / `e` current view (biome/zoom/local) + headless `--export`
