#!/usr/bin/env bash
# Headless SVG and PNG export of the whole island to build/export. All arguments go to biomegen; --save is set here.
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"
help_if_asked "Usage: scripts/export.sh [biomegen args]   (writes build/export/world.{svg,png}; no --seed: random
  seed, echoed; later -h is biomegen's)" "$@"

mkdir -p "${build_dir}/export"
for suffix in svg png; do
    uv run biomegen --view terrain --no-legend --save "${build_dir}/export/world.${suffix}" "$@"
done
