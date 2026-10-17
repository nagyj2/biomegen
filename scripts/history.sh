#!/usr/bin/env bash
# Open the history viewer: the political map at moments of the past, the powers then and the chronicle beside it.
# An optional first argument is the year to open at (the map at the end of it); the rest go to biomegen.
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"
help_if_asked "Usage: scripts/history.sh [YEAR] [biomegen args]   (no --seed: random seed; later -h is biomegen's)" "$@"

year=()
if [[ "${1:-}" =~ ^[0-9]+$ ]]; then year=("$1"); shift; fi
uv run biomegen --history "${year[@]}" "$@"
