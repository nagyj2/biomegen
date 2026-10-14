#!/usr/bin/env bash
# Full gate: ruff format check, ruff lint, mypy, then the test suite. Stops at the first failure.
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -q "$@"
