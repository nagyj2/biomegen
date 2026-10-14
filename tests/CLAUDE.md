# tests/

Run with `scripts/test.sh [pytest args]` (or `uv run pytest -q`). `scripts/check.sh` adds lint and mypy.

## Rules

- Mirror `src/biomegen/`: `config/`, `util/`, `world/`, `interiors/`, `pipeline/` (with `physical/`),
  `render/`, `explorer/`. `widget.py` is tested in `test_widget.py`; each folder has an `__init__.py`.
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
- The before/after proof for refactors is `scripts/fingerprint.sh` output, not a pinned literal.

## Known skips

- None expected on Linux or macOS. The explorer's pseudo-terminal tests (`tests/explorer/test_input.py`,
  `tests/test_cli.py`) are skipped on Windows, where the Windows key reader and VT handling are untested.
- Non-strict xfails (user decision, phase 3): `test_interior_door_faces_road` (river can split a settlement
  footprint; phase 5) and two tower-stair tests (the entrance corridor can overwrite a stair). They xpass
  on the current default world; they guard seed-dependent edge cases.
