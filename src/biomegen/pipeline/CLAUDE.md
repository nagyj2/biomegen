# pipeline/

Ordered generation stages that fill an immutable `World`. `pipeline/__init__.py` (`generate`) owns the order.

## Rules

- A stage is `run(world, config, seed) -> None`. It reads only fields produced by earlier stages and writes
  only its own; there is no backtracking.
- One rng label per stage (a stage may add sub-labels, e.g. `rng.derive(seed, "terrain", "warp")`). First
  labels must be in `util.rng.LABELS`; add new ones there, never ad-hoc strings. Streams come from `rng.derive*`, never
  `random` or `numpy.random` seeded by hand, never builtin `hash()`.
- Iterate collections in a defined order (`sorted()`); dict and set order is not a contract.
- Every tunable comes from `config.get(...)`, not a literal (see `config/CLAUDE.md`).
- Folders say what a stage models: `physical/` (land and water), `civilization/` (settlements, roads), `story/` (POI
  content). Flat modules still to be reorganised (`regions`, `pois`, `naming`) stay in `pipeline/` until the phase that
  replaces them.

## Physical stages (`physical/`)

- Order: terrain -> climate -> hydrology -> biomes -> geography. Terrain sits inside the land gate.
- Units are physical: `elevation_m` (m, < 0 = sea), `temperature_c` (°C), `rain_mm` (mm/yr), distances
  in km. Sample noise with `noise.km_grid` and measure with `geo.distance_to(..., sampling=world.scale.sampling)`
  so a different grid resolution keeps every `_km` / `_km2` tunable's meaning.
- Ranked thresholds (sea level, moisture, river share) sort with `kind="stable"`, so ties keep row-major
  order; component lists sort by size then first cell, never by labelling-backend order.
- Water: `water_type` is the truth (salt sea, fresh lake or river). A river keeps its land biome;
  `WATER_BIOMES` only says whether the cover itself is water. Old render code draws rivers through
  `render/surface.py`.
- Shared fields have documented co-owners: hydrology flattens lake surfaces in `elevation_m` and
  recomputes `rain_mm` (via `climate.rainfall_mm`) after its moisture bonus. No other stage rewrites
  an earlier stage's field.
- Per-name rows (styles, relief heights, geo name forms) are data tables; classifier numbers stay in
  `config/defaults/`. Time stages with `scripts/bench.sh` when a change could slow them.

## Civilization stages (`civilization/`, `pois.py`)

- Order: regions -> settlements -> pois -> roads -> poi_interiors -> naming. Settlements are placed first and
  every later stage counts them (spacing, remoteness, road endpoints).
- Tiers are data (`data/tiers.toml`): placement order is `rank`, count is land km² over `land_per_settlement_km2`,
  separation is `spacing_km`, and `backbone` says whether roads join the tier into the trunk. A new tier is a row,
  not a code branch; the settlement interior builder and the render markers still need the kind registered.
- Distances are km on the anisotropic grid: use `world.scale` (`km_per_col`, `km_per_row`, `cell_area_km2`), never a
  tile count. A placement test compares km, not tiles.
- Candidates sort by score then row-major order (`argsort(kind="stable")` or `lexsort`), so equal scores never
  depend on iteration order.
- Roads route per landmass (a connected `water_type != SALT` component), so they never cross open ocean. The trunk is
  a minimum spanning tree over *every pair* of backbone settlements in km (a k-nearest graph can leave a backbone town
  out); villages and wild POIs branch off as spurs to the nearest road tile. A step costs its km length, over the
  biome and relief `move_cost` rows.
- Wild POIs (`pois.py`) are interim: counts are area over `km2_per_poi`, and phase 8 replaces them with data rows.

## Adding a stage

1. Create the module with `run(...)`, add its label to `LABELS`, call it in `generate()` at the right point.
2. Add a test under `tests/pipeline/` mirroring the module, plus a stats entry if it adds countable output.
3. Update the stage list in `docs/ARCHITECTURE.md`.
4. Run `scripts/fingerprint.sh` before and after and explain every change.
