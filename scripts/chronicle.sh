#!/usr/bin/env bash
# Print a world's chronicle. Usage: scripts/chronicle.sh [seed] [text|json]   (default: fixture seed, text)
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

uv run biomegen --seed "${1:-${fixture_seed}}" --chronicle --chronicle-format "${2:-text}"
