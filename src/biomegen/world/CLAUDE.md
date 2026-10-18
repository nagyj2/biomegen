# world/

The data model: the immutable `World` (per-tile arrays and sparse entity lists), the entities in it, the mutable `Overlay` and the
shapes a later simulation fills. It sits just above `util` and `config`.

## Rules

- **`world/` imports only `util` and `config`** (and itself). Nothing here may reach `sampling`, `sites`, `naming`, `pipeline`,
  `render` or `explorer`; `tests/test_layering.py` fails if it does. (`config/tables.py` and `config/validate.py` import the world's
  enums inside functions to check table rows: the one upward import that exists on purpose, allow-listed in that test.)
- **The `World` is immutable after generation.** Runtime edits go through `Overlay`; a simulation's state lives in a `SimState`
  beside the world, never in it. Per-tile arrays are in `World.FIELDS` and the fingerprint; sparse entities (POIs, realms, events,
  rulers, territory) are not, so adding or changing one never moves the fingerprint.
- **Entities are plain dataclasses** with defaulted trailing fields, so a new field never breaks a positional construction.
  `ChronicleEvent.tick` is the absolute month (`month_tick(year, month, months_per_year)`) and `derived` says the generation made
  it; `POI.potential` is the largest settlement tier its site could grow into.
- **Ids continue, never reuse.** `EventLog` (`ledger.py`) reads `World.chronicle` and a continuation as one list with `id == index`;
  a `SimState` (`sim_state.py`) numbers its rulers, predecessors and POIs after the generated ones (`next_ruler_id`,
  `next_predecessor_id`, `next_poi_index`, which counts the vanished POIs too). `SiteManifest` (`manifest.py`) is frozen: a
  change is a new manifest.
- **Time keys are `(year, month, event id)`** (`territory.Key`, `at_end`); a moment `(year, month)` means the end of that month.
- **`derived.py`** keeps values worked out from the arrays, once per world, checked by a source digest; a simulation's per-tile
  lookups belong there.
