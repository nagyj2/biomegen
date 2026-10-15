#!/usr/bin/env bash
# Launch the interactive app. All arguments go to biomegen; no --seed means a random seed.
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"
help_if_asked "Usage: scripts/run.sh [biomegen args]   (no --seed: random seed; later -h is biomegen's)" "$@"

uv run biomegen "$@"
