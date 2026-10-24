# sim/

The tick simulation of the finished present world (`docs/simulation_plan.md`): observer only, deterministic, data driven. Built in
sub-phases 10a to 10h; this file grows with them (10a: state, hydrate, tick loop, no behaviour).

## Rules

- **Layer.** Between `pipeline` and `render`: it may import `world`, `sites`, `naming` and the pipeline's pure helpers, never `render` or
  `explorer` (`tests/test_layering.py`). State dataclasses live in `world/` (`sim_state.py`, `reader.py`); logic lives here.
- **Tunables** are in `config/defaults/sim.py` (the `sim` section), per-name rows in `data/*.toml`, distances in km. No literals in sim code.
- **Time is integer ticks.** `sim.ticks_per_month` ticks make a month (`SimState.tick // ticks_per_month`). No float accumulation in state.
- **Determinism.** Streams come from `rng.derive(seed, "sim", ...)`, never builtin `hash()`; iterate in sorted order (factions by id).
