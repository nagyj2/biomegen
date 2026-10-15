# data/

Attribute tables keyed by name: one row per biome, relief level, settlement tier, terrain style or
geographic feature kind, site or furniture set. Numbers that apply to the whole world (counts, budgets, thresholds) stay in
`config/defaults/`, not here.

## How they load

- `config/defaults/tables.py` reads every file in `DATA_FILES` with `tomllib` and puts each top-level
  table under the `tables` config section (`tables.biomes`, `tables.relief` from `biomes.toml`;
  `tables.detail`, `tables.detail_relief` from `detail.toml`; `tables.tiers`; `tables.styles` from `terrain.toml`;
  `tables.geo_names` from `geography.toml`; `tables.sites` from `sites.toml`; `tables.furniture` from `furniture.toml`; `tables.realm_kinds`, `tables.realm_forms`,
  `tables.relation_weights` and `tables.realm_colors` from `polity.toml`; `tables.reasons` and `tables.reason_tokens` from
  `reasons.toml`; `tables.chronicle` from `chronicle.toml`).
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

## Politics

- `polity.toml`: `realm_kinds` has one row per kind (`major`, `city_state`, `tribal`: strength and rural population
  spans, vassal chance). `realm_forms` rows are the ways a realm is named and ruled; a row names its `kind`, a `habitat`
  (`any`, or `dry`, `cold`, `wood`, `high` to favour it, `open` as the default) and a `weight`, and each kind needs an
  `any` or `open` row. `relation_weights` (`major_pair`, `other_pair`) and `realm_colors` (HSV per role) are fixed row sets.
- `reasons.toml`: `reasons` has one row per relation kind with `templates`; the tokens a template may use are checked
  (`{town}`, `{river}`, `{range}`, `{sea}` for war and rivalry; `{goods_a}`, `{goods_b}`, `{short_a}`, `{short_b}` for trade).
  `reason_tokens` gives the words used when the world lacks the place.
- Counts, budgets and distances (km) are in the `politics` config section.

## Chronicle

- `chronicle.toml`: `chronicle` has one row per kind of event text (`founding`, `settling`, `conquest`, `war`, `rivalry`,
  `treaty_alliance`, `treaty_trade`, `battle`, `fall`). `templates` are sentences that name no nearby place;
  `templates_near` (optional) are sentences that name one with `{near}` and must contain it. The tokens a row may use are
  listed in the file's header and checked (`{year}` is allowed everywhere); `{near}` is allowed in `templates_near` only.
- The history stage picks a template per event (`templates_near` only when a settlement qualifies, see
  `pipeline/CLAUDE.md`) and naming fills the tokens. To change a wording, edit the row; to add a token, see "Token
  resolution" in `pipeline/CLAUDE.md`.
- Counts, years and distances (km) are in the `history` config section.

## Adding a table or column

Add the schema to `config/tables.py`, the file to `DATA_FILES` if it is new, a header comment documenting
every key, and a test in `tests/config/test_tables.py`.
