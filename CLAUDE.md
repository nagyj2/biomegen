# biomegen

Seed-reproducible procedural island generator with a terminal explorer. Code map: `docs/ARCHITECTURE.md`.
Redesign plan and phases: `docs/redesign_plan.md`. Nested `CLAUDE.md` files hold per-folder rules.

## Rules

- **Data driven.** New features are customizable through the config file: tunables live in
  `src/biomegen/config/defaults/`, never as literals in stage code (see `src/biomegen/config/CLAUDE.md`).
  Per-name attribute rows (biomes, relief, tiers) live in `src/biomegen/data/*.toml`; distances are km.
- **uv only.** `uv sync --extra dev`, `uv run ...`; never call `python`, `pip` or `pytest` directly.
- **Named environment.** Runs use the uv environment `biome`, selected with `UV_PROJECT_ENVIRONMENT`
  (set under `env` in `.claude/settings.local.json`, not stored in the repo). Scripts fail fast without it.
- **Commits.** One commit per completed task; `git mv` moves and the edits they require are separate
  commits (the tree may not run between them). Never push without being asked.
- **Dependencies.** Name any new dependency and its purpose before adding it.

## Commands

All wrap `uv run`. Arguments go straight to biomegen (or pytest); `--seed S` works everywhere and no seed means a random
one (echoed). `-h` as the first argument shows the script's usage; later `-h` reaches biomegen. Fixtures live in `scripts/_fixtures.sh`:

- `scripts/test.sh [pytest args]`: run the tests.
- `scripts/check.sh`: ruff format check, ruff, mypy, pytest.
- `scripts/run.sh [args]`: launch the app.
- `scripts/stats.sh [args]`: headless stats dump, including the fingerprint.
- `scripts/chronicle.sh [args]`: print the chronicle (`--chronicle-format json`).
- `scripts/history.sh [YEAR] [args]`: the history viewer (political map through time, `--history`); opens at the end of YEAR.
- `scripts/fingerprint.sh [--seed S]`: world fingerprints (default seeds 42, 7, 1337, 11, 15; 11 and 15 hold a defection and an
  offshoot, since a proof needs fixed worlds); the before/after proof for refactors.
- `scripts/export.sh [args]`: headless SVG/PNG export to `build/export`.
- `scripts/view.sh [args]`: a static map fitted to the terminal; add `--scale zoom|local --at X,Y` for a magnified part.
- `scripts/bench_render.sh [--seed S] [runs] [COLSxROWS] [view]`: frame times of the detail layers and the explorer frame.

## Layering

Dependency direction: `util -> config -> world -> sampling -> sites, naming -> pipeline -> render -> explorer -> cli`. A lower
layer never imports a higher one; `render/` does no terminal I/O (rules in `src/biomegen/render/CLAUDE.md`).

## Determinism (do not break)

Same seed must give the same world on any machine. Details in `docs/ARCHITECTURE.md`, "Determinism rules".

- `blake2b` only, never builtin `hash()`; sub-streams come from `util.rng.derive(seed, *labels)`. Key a draw on what an entity
  is, never on a ledger position: an event id shifts when events are added, so POI draws use `poi_rules.event_key`.
- Iterate collections in a defined order (`sorted()`) in Python-loop stages.
- `scripts/fingerprint.sh` output must not change in a refactor; a behaviour change must say so.

## Handoffs

When a phase ends, write a new top section in `docs/handoffs/landed-work.md` ending with a
`## Resume prompt` built from `docs/templates/resume_prompt.md`. `docs/handoffs/` is local only (git-excluded).
