# tests/

Run with `scripts/test.sh [pytest args]` (or `uv run pytest -q`). `scripts/check.sh` adds lint and mypy.

## Rules

- Mirror `src/biomegen/`: `config/`, `util/`, `world/`, `interiors/`, `pipeline/`, `render/`, `export/`.
  `widget.py` is tested in `test_widget.py`; each folder has an `__init__.py`.
- One assertion concept per test (all assertions relate to one behaviour). Put a comment at the top of the
  test saying what is verified when the code does not make it obvious.
- No mocking unless I/O or time is involved; use real objects and in-memory fakes.
- Module-scoped fixtures for generated worlds (`pipeline.generate` is the slow part); keep seeds fixed.
- The package is installed editable, so tests import `biomegen` directly; do not set `PYTHONPATH`.

## Determinism

- `tests/pipeline/test_generation.py` compares the world fingerprint across `PYTHONHASHSEED` values in
  subprocesses. Any use of builtin `hash()` in the generation path fails it.
- The before/after proof for refactors is `scripts/fingerprint.sh` output, not a pinned literal.

## Known skips

- `tests/render/test_ui.py` skips the curses loop test without a TTY (one skip is expected headless).
