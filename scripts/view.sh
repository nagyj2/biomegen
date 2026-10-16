#!/usr/bin/env bash
# Static map sized to the terminal (override with --width/--height). All arguments go to biomegen.
# Magnified part: scripts/view.sh --scale zoom --at 60,30 (or local); one site: --scale site --at 168,23 [--floor N]
# (a site view is one plan cell per terminal cell, centred on the tile and clipped to the terminal).
# A magnified view keeps the default world size, so its coordinates mean the same on every terminal and are those of the
# explorer and `scripts/stats.sh`; only the plain map is sized to the terminal.
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"
help_if_asked "Usage: scripts/view.sh [biomegen args]   (default view terrain, sized to this terminal, no --seed: random
  seed; --scale zoom|local|site --at X,Y keeps the default world size; later -h is biomegen's)" "$@"

# The map frame adds 8 columns and ~4 rows; the legend prints below it.
sizing=(--width $(($(tput cols) - 8)) --height $(($(tput lines) - 5)))
for argument in "$@"; do
    if [[ "${argument}" == "--scale" ]]; then sizing=(); fi
done
uv run biomegen --view terrain "${sizing[@]}" "$@"
