#!/usr/bin/env bash
# Print world fingerprints, one "<seed> <fingerprint>" line per seed: the before/after proof for refactors.
# Usage: scripts/fingerprint.sh [seed ...]   (default: the fixture fingerprint seeds)
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

seeds=("$@")
if [[ ${#seeds[@]} -eq 0 ]]; then
    seeds=("${fixture_fingerprint_seeds[@]}")
fi

for seed in "${seeds[@]}"; do
    fingerprint="$(uv run biomegen --headless --seed "${seed}" | awk '/^fingerprint:/ {print $2}')"
    echo "${seed} ${fingerprint}"
done
