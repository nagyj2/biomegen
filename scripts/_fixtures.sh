#!/usr/bin/env bash
# Shared fixtures for scripts/*.sh. Source this file; do not execute it.
#
# Pins the fixture seeds and sizes so outputs are comparable between runs and between agent and user,
# runs from the repo root, and refuses to run without a named uv environment (never falls back silently).

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

if [[ -z "${UV_PROJECT_ENVIRONMENT:-}" ]]; then
    echo "error: UV_PROJECT_ENVIRONMENT is not set; point it at the biome uv environment" >&2
    echo "       e.g. export UV_PROJECT_ENVIRONMENT=~/.venvs/biome (see README, Install)" >&2
    exit 1
fi

# Default fixture seed, the extra fingerprint seeds, and a small fast world for quick checks.
fixture_seed=42
fixture_fingerprint_seeds=(42 7 1337 11 15)
fixture_small_width=64
fixture_small_height=32
build_dir="${repo_root}/build"

# Print $1 and exit when the FIRST script argument is -h/--help (later ones reach biomegen). Usage: help_if_asked "text" "$@"
help_if_asked() {
    local text="$1"
    shift
    if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
        printf '%s\n' "${text}"
        exit 0
    fi
}

# For the python-driven benches: find --seed in "$@" (random when absent) and leave the other args in bench_args.
bench_seed_args() {
    bench_seed=""
    bench_args=()
    while [[ $# -gt 0 ]]; do
        if [[ "$1" == "--seed" ]]; then bench_seed="${2:?--seed needs a value}"; shift 2
        else bench_args+=("$1"); shift; fi
    done
    bench_seed="${bench_seed:-$((RANDOM * 32768 + RANDOM))}"
    echo "seed=${bench_seed}" >&2
}
