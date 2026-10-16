#!/usr/bin/env bash
# Show a world's chronicle: a pager on a terminal, plain output when piped. All arguments go to biomegen
# (e.g. --kind war,battle --from-year 200 --realm Aimo --search treaty --no-pager --chronicle-format json).
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"
help_if_asked "Usage: scripts/chronicle.sh [biomegen args]   (no --seed: random seed; later -h is biomegen's)" "$@"

uv run biomegen --chronicle --chronicle-format text "$@"
