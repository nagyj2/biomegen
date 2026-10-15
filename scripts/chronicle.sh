#!/usr/bin/env bash
# Print a world's chronicle. All arguments go to biomegen (e.g. --chronicle-format json).
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"
help_if_asked "Usage: scripts/chronicle.sh [biomegen args]   (no --seed: random seed; later -h is biomegen's)" "$@"

uv run biomegen --chronicle --chronicle-format text "$@"
