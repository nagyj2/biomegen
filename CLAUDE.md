# biomegen

Seed-reproducible procedural island generator with a terminal explorer. Code map: `docs/ARCHITECTURE.md`.
Redesign plan and phases: `docs/redesign_plan.md`. Nested `CLAUDE.md` files hold per-folder rules.

## Rules

- **Data driven.** New features are customizable through the config file: tunables live in
  `src/biomegen/config/defaults/`, never as literals in stage code (see `src/biomegen/config/CLAUDE.md`).
- **uv only.** `uv sync --extra dev`, `uv run ...`; never call `python`, `pip` or `pytest` directly.
- **Named environment.** Runs use the uv environment `biome`, selected with `UV_PROJECT_ENVIRONMENT`
  (set under `env` in `.claude/settings.local.json`, not stored in the repo). Scripts fail fast without it.
- **Commits.** One commit per completed task; `git mv` moves and the edits they require are separate
  commits (the tree may not run between them). Never push without being asked.
- **Dependencies.** Name any new dependency and its purpose before adding it.

## Commands

All wrap `uv run` and pin fixture seeds and sizes in `scripts/_fixtures.sh`:

- `scripts/test.sh [pytest args]`: run the tests.
- `scripts/check.sh`: ruff format check, ruff, mypy, pytest.
- `scripts/run.sh [args]`: launch the app on the fixture seed (42).
- `scripts/stats.sh [seed]`: headless stats dump, including the fingerprint.
- `scripts/fingerprint.sh [seed ...]`: world fingerprints (default seeds 42, 7, 1337); the before/after
  proof for refactors.
- `scripts/export.sh [seed] [dir]`: headless SVG/PNG export (default `build/export`).

## Layering

Dependency direction: `util -> config -> world -> interiors, naming -> pipeline -> render -> cli`. A lower
layer never imports a higher one. The target layout (adds `explorer/`, `data/`) is in the plan, section 11.

## Determinism (do not break)

Same seed must give the same world on any machine. Details in `docs/ARCHITECTURE.md`, "Determinism rules".

- `blake2b` only, never builtin `hash()`; sub-streams come from `util.rng.derive(seed, *labels)`.
- Iterate collections in a defined order (`sorted()`) in Python-loop stages.
- `scripts/fingerprint.sh` output must not change in a refactor; a behaviour change must say so.

## Handoffs

When a phase ends, write a new top section in `docs/handoffs/landed-work.md` ending with a
`## Resume prompt` built from `docs/templates/resume_prompt.md`. `docs/handoffs/` is local only (git-excluded).
