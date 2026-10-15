#!/usr/bin/env bash
# Print world fingerprints, the before/after proof for refactors. Without --seed it runs the fixed fingerprint seeds
# (a proof needs the same worlds each time); with --seed it runs just that one. Other arguments go to biomegen.
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"
help_if_asked "Usage: scripts/fingerprint.sh [--seed SEED] [biomegen args]   (no --seed: seeds ${fixture_fingerprint_seeds[*]})" "$@"

if [[ " $* " == *" --seed "* ]]; then
    uv run biomegen --headless "$@" | awk '/^(biomegen: seed|fingerprint)/'
    exit
fi
for seed in "${fixture_fingerprint_seeds[@]}"; do
    echo "${seed} $(uv run biomegen --headless --seed "${seed}" "$@" | awk '/^fingerprint:/ {print $2}')"
done
