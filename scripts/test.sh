#!/usr/bin/env bash
# Run the test suite. Extra arguments go to pytest, e.g. scripts/test.sh tests/config -k defaults
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

uv run pytest -q "$@"
