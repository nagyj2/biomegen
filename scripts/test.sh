#!/usr/bin/env bash
# Run the tests. All arguments go to pytest.
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"
help_if_asked "Usage: scripts/test.sh [pytest args]   (later -h is pytest's)" "$@"

uv run pytest -q "$@"
