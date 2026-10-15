#!/usr/bin/env bash
# Full gate: ruff format check, ruff lint, mypy, then the test suite. Stops at the first failure.
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"
help_if_asked "Usage: scripts/check.sh [pytest args]   (ruff format, ruff, mypy, pytest; later -h is pytest's)" "$@"
script_usage="Usage: scripts/check.sh [pytest args]
  Run ruff format check, ruff, mypy and pytest, stopping at the first failure. No seed applies.
  -h as the first argument shows this text; anywhere else it is passed to pytest."
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then printf '%s\n' "${script_usage}"; exit 0; fi

uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -q "$@"
