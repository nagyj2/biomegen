#!/usr/bin/env bash
# Headless export of the whole island (SVG, plus PNG when Pillow is installed).
# Usage: scripts/export.sh [seed] [dir]   (default: fixture seed, build/export)
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

seed="${1:-${fixture_seed}}"
out_dir="${2:-${build_dir}/export}"

# export.dir is a config key, so pass it through a throwaway config overlay.
overlay="$(mktemp --suffix=.toml)"
trap 'rm -f "${overlay}"' EXIT
printf '[export]\ndir = "%s"\n' "${out_dir}" >"${overlay}"

uv run biomegen --seed "${seed}" --config "${overlay}" --export world
