#!/usr/bin/env bash
# Headless stats dump, including the fingerprint. Usage: scripts/stats.sh [seed]
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

uv run biomegen --headless --seed "${1:-${fixture_seed}}"
