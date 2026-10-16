#!/usr/bin/env bash
# Static map sized to the terminal (override with --width/--height). All arguments go to biomegen.
# Magnified part: scripts/view.sh --scale zoom --at 60,30 (or local); one site: --scale site --at 168,23 [--floor N]
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"
help_if_asked "Usage: scripts/view.sh [biomegen args]   (default view terrain, sized to this terminal, no --seed: random
  seed; later -h is biomegen's)" "$@"

# The map frame adds 8 columns and ~4 rows; the legend prints below it.
uv run biomegen --view terrain --width $(($(tput cols) - 8)) --height $(($(tput lines) - 5)) "$@"
