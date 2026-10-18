# config/

Every tunable lives here. The program must run correctly with no config file at all.

## Adding a tunable

1. Add the key and its value to the matching section module in `defaults/` (one module per top-level
   section, each exposing `VALUES`; `defaults/__init__.py` assembles `DEFAULTS`). Comment units and ranges.
2. A new top-level section is a new module plus an entry in `DEFAULTS` (`tests/config/test_defaults.py`
   fails if a module is not wired in).
3. If a user would plausibly set it, show it in `config.example.toml`. The file is a sparse overlay: it may
   only name sections and keys that exist in the defaults.
4. Touch `validate.py` only when the value needs coercion (colours) or a clamp that would otherwise crash a
   stage. Validation collects every problem before raising; keep it light.

## Units

- New distances are km and areas km² (name them `*_km`, `*_km2`), never tiles or cells, so a different
  grid resolution keeps their meaning. Convert at the call site with `world.scale` (`util/units.py`).
- Existing tile-based keys convert when their stage is rewritten (phases 3-5), not before.
- Physical constants (`KM_PER_DEGREE`) are not tunables; they stay in code.

## Tables

- Per-name attribute rows (biomes, relief, tiers, polity, POI kinds and their fates and sites) live in `../data/*.toml`,
  not in `defaults/`. `defaults/tables.py` loads them as the `tables` section; one file may not repeat
  another's table. Global numbers (counts, budgets) stay in `defaults/`.
- Each table has a row schema in `tables.py` (`SCHEMAS`); a new table or column needs an entry there.
  See `../data/CLAUDE.md` for adding a row.

## Rules

- Read values through `Config.get("section.key")` at the call site; never import `DEFAULTS` outside `config/`.
- Callers work on copies (`get_defaults()` deep-copies); never mutate `DEFAULTS` in place.
- Precedence is CLI flag > config file > defaults. A new CLI flag overrides the merged tree in `cli.py`.
- Changing a default changes the world: say so, and compare `scripts/fingerprint.sh` before and after.
- **Populations are scaled after the draw** (`population.py`): every population drawn from a table (`tables.tiers.<tier>.pop`,
  `poi.homestead_people`, a realm kind's `rural_per_km2`) is multiplied by `settlements.pop_scale` with `scaled_people`, and a
  population is measured against its tier's range with `tier_pop_range`. To raise or lower the numbers change the scale; changing a
  range changes the draws and so, through the tribes' seats, the world.
