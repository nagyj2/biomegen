# tests/

Run with `scripts/test.sh [pytest args]` (or `uv run pytest -q`). `scripts/check.sh` adds lint and mypy.

## Rules

- Mirror `src/biomegen/`: `config/`, `util/`, `world/`, `pipeline/` (with `physical/`, `civilization/`),
  `sampling/`, `sites/`, `naming/`, `render/`, `explorer/`. `widget.py` is tested in `test_widget.py`; each folder has an `__init__.py`.
  Two files sit at the top: `test_layering.py` (every package imports only a lower layer; `world/` only `util` and `config`) and
  `test_scripts.py` (the measuring scripts run).
- One assertion concept per test (all assertions relate to one behaviour). Put a comment at the top of the
  test saying what is verified when the code does not make it obvious.
- No mocking unless I/O or time is involved; use real objects and in-memory fakes.
- Module-scoped fixtures for generated worlds (`pipeline.generate` is the slow part); keep seeds fixed.
- The package is installed editable, so tests import `biomegen` directly; do not set `PYTHONPATH`.
- Physical-stage tests build small synthetic worlds (a strip, a bowl, two islands) so each mechanism is
  checked on its own; whole-world checks use a 96x48 world and fixed seeds.

## Determinism

- `tests/pipeline/test_generation.py` compares the world fingerprint across `PYTHONHASHSEED` values in
  subprocesses. Any use of builtin `hash()` in the generation path fails it.
- The before/after proof for refactors is `scripts/fingerprint.sh` output, not a pinned literal. Its seeds are 42, 7 and 1337
  plus 11 (a defection) and 15 (an offshoot), which `tests/pipeline/story/test_secession_fixtures.py` keeps honest.
- Secession tests run on small hand-made worlds and on worlds made with a config where one form has chance 1 (the other forms'
  weights 0); the default chance is low, so the default fixture seeds hold few secessions.

## Known skips

- None expected on Linux or macOS. The explorer's pseudo-terminal tests (`tests/explorer/test_input.py`,
  `tests/test_cli.py`) are skipped on Windows, where the Windows key reader and VT handling are untested.
- No xfails or skips are expected on Linux or macOS. Site tests build small worlds with `tests/sites/conftest.py`
  (`flat_world`, `add_poi`, a `config` with the extent jitter off) and check whole generated worlds in
  `tests/sites/test_world_plans.py`.
