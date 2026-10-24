#!/usr/bin/env bash
# Run the simulation headless: print the series (a row at the start and every N years) and the sim fingerprint.
# With --proof it prints `seed fingerprint` for each fixed fingerprint seed instead (the before/after proof for a change that
# must not alter the simulation; a run of YEARS years each).
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"
usage="Usage: scripts/simulate.sh [--seed SEED] [YEARS] [--every N]   (no --seed: random seed; defaults sim.series.years and every_years)
       scripts/simulate.sh --proof [YEARS]   (seeds ${fixture_fingerprint_seeds[*]})"
help_if_asked "${usage}" "$@"

if [[ " $* " == *" --proof "* ]]; then
    forward=()
    for arg in "$@"; do [[ "${arg}" == "--proof" ]] || forward+=("${arg}"); done
    for seed in "${fixture_fingerprint_seeds[@]}"; do
        echo "${seed} $(uv run python -m biomegen.sim --seed "${seed}" --fingerprint-only "${forward[@]}")"
    done
    exit 0
fi

bench_seed_args "$@"
uv run python -m biomegen.sim --seed "${bench_seed}" "${bench_args[@]}"
