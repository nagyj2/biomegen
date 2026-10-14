#!/usr/bin/env bash
# Headless export of the whole island: an SVG, plus a PNG when Pillow is installed.
# Usage: scripts/export.sh [seed] [dir]   (default: fixture seed, build/export)
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

seed="${1:-${fixture_seed}}"
out_dir="${2:-${build_dir}/export}"
mkdir -p "${out_dir}"

uv run biomegen --seed "${seed}" --view terrain --no-legend --save "${out_dir}/world_${seed}.svg" >/dev/null
uv run biomegen --seed "${seed}" --view terrain --no-legend --save "${out_dir}/world_${seed}.png" >/dev/null
ls "${out_dir}"
