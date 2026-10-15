#!/usr/bin/env bash
# Headless stats dump, including the fingerprint. All arguments go to biomegen.
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"
help_if_asked "Usage: scripts/stats.sh [biomegen args]   (no --seed: random seed; later -h is biomegen's)" "$@"

uv run biomegen --headless "$@"
