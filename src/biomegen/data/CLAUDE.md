# data/

Attribute tables keyed by name: one row per biome, relief level or settlement tier. Numbers that apply
to the whole world (counts, budgets, thresholds) stay in `config/defaults/`, not here.

## How they load

- `config/defaults/tables.py` reads every file in `DATA_FILES` with `tomllib` and puts each top-level
  table under the `tables` config section (`tables.biomes`, `tables.relief`, `tables.tiers`).
- A user config overrides with the ordinary deep-merge: `[tables.biomes.desert]` + `goods = "glass"`
  changes one attribute and keeps the rest of the row.
- `config/tables.py` validates every row against its table's schema (`SCHEMAS`): unknown keys, missing
  keys and wrong kinds are errors; colours accept `[r, g, b]` or `"#rrggbb"`.
- Stages read rows through `config.get("tables.<table>.<name>.<key>")`, never by opening these files.

## Adding a row

1. Add the row with every key the file's header comment lists (only optional keys may be omitted).
2. Biome and relief rows are keyed by the lower-case enum member name in `world/tile.py`; relief must have
   exactly one row per `Relief` member. A new biome also needs its enum entry (from phase 3).
3. When order matters, it is a column (`rank` in tiers), never file order.
4. Run `scripts/check.sh`. A changed row that a stage reads changes the world: compare
   `scripts/fingerprint.sh` before and after.

## Adding a table or column

Add the schema to `config/tables.py`, the file to `DATA_FILES` if it is new, a header comment documenting
every key, and a test in `tests/config/test_tables.py`.
