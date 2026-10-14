# data/

Attribute tables keyed by name: one row per biome, relief level, settlement tier, terrain style or
geographic feature kind, site or furniture set. Numbers that apply to the whole world (counts, budgets, thresholds) stay in
`config/defaults/`, not here.

## How they load

- `config/defaults/tables.py` reads every file in `DATA_FILES` with `tomllib` and puts each top-level
  table under the `tables` config section (`tables.biomes`, `tables.relief` from `biomes.toml`;
  `tables.detail`, `tables.detail_relief` from `detail.toml`; `tables.tiers`; `tables.styles` from `terrain.toml`;
  `tables.geo_names` from `geography.toml`; `tables.sites` from `sites.toml`; `tables.furniture` from `furniture.toml`).
- A user config overrides with the ordinary deep-merge: `[tables.biomes.desert]` + `goods = "glass"`
  changes one attribute and keeps the rest of the row.
- `config/tables.py` validates every row against its table's schema (`SCHEMAS`): unknown keys, missing
  keys and wrong kinds are errors; colours accept `[r, g, b]` or `"#rrggbb"`.
- Stages read rows through `config.get("tables.<table>.<name>.<key>")`, never by opening these files.

## Adding a row

1. Add the row with every key the file's header comment lists (only optional keys may be omitted).
2. Biome and relief rows are keyed by the lower-case enum member name in `world/tile.py`; both tables must
   have exactly one row per member, so a new biome is an enum entry plus a row (and a band rule in
   `config/defaults/biomes.py` if the classifier should produce it). Relief rows with `min_elevation_m`
   are chosen by height (highest match wins); rows without it (none, volcano) are set otherwise.
3. A new terrain style is a `styles` row; `weight = 0` keeps it out of the per-seed draw. A `geo_names`
   row needs a `forms` list whose every pattern contains `{n}` exactly once.
4. When order matters, it is a column (`rank` in tiers), never file order.
5. Run `scripts/check.sh`. A changed row that a stage reads changes the world: compare
   `scripts/fingerprint.sh` before and after.

## Sites and furniture

- `sites.toml` has one row per POI kind: its `layout`, the `furniture` set, `extent_tiles` (w, h in world tiles, below 1
  for a site smaller than a tile), `rows_per_tile` (plan resolution) and, for settlements, `grows_with_pop`,
  `plaza_tiles` and the optional `walled` (a wall with a gate where each road arrives). Every settlement tier in `tiers.toml` and every `poi.types` kind needs a site row to be zoomable.
- `furniture.toml` has weight sets nested by family then room role (`[furniture.dungeon.vault]` + `chest = 4.0`): each
  key a lower-case `Cell` name, each value a weight. A layout asks for a role per room; a missing role leaves it bare.
  `validate_tables` checks the keys and that each site row names a family that exists.

## Adding a table or column

Add the schema to `config/tables.py`, the file to `DATA_FILES` if it is new, a header comment documenting
every key, and a test in `tests/config/test_tables.py`.
