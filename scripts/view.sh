#!/usr/bin/env bash
# Static map of the whole world with its legend (plain text when piped, coloured on a terminal).
# Usage: scripts/view.sh [view] [seed] [extra biomegen args]   (default: terrain, fixture seed)
# Magnified part of the world: scripts/view.sh terrain 42 --scale zoom --at 60,30   (or --scale local)
# One point of interest's site: scripts/view.sh terrain 42 --scale site --at 168,23   (--floor N for other floors)
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

view="${1:-terrain}"
seed="${2:-${fixture_seed}}"
shift $(($# > 2 ? 2 : $#))

uv run biomegen --seed "${seed}" --view "${view}" "$@"
