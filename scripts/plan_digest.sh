#!/usr/bin/env bash
# Digest of every site plan (every floor, inside and outside views) of a world: the proof that a refactor leaves plans
# unchanged and, with --list, which POIs a change moved (diff two --list outputs). Plans never move the world fingerprint.
# Usage: scripts/plan_digest.sh [--seed S] [--list]   (no --seed: the fingerprint seeds)
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

help_if_asked "Usage: scripts/plan_digest.sh [--seed SEED] [--list]   (no --seed: seeds ${fixture_fingerprint_seeds[*]}; --list prints one line per POI)" "$@"
seeds=()
list=0
while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--seed" ]]; then seeds+=("${2:?--seed needs a value}"); shift 2
    elif [[ "$1" == "--list" ]]; then list=1; shift
    else echo "error: unknown argument $1" >&2; exit 2; fi
done
if [[ ${#seeds[@]} -eq 0 ]]; then seeds=("${fixture_fingerprint_seeds[@]}"); fi

uv run python - "${list}" "${seeds[@]}" <<'PY'
import hashlib
import sys

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.sites import site_plan, site_pois

show_list = sys.argv[1] == "1"
config = load_config(None)
for seed in (int(v) for v in sys.argv[2:]):
    world = pipeline.generate(config, seed)
    overall = hashlib.blake2b(digest_size=16)
    for index, (poi, _geometry) in enumerate(site_pois(world, config)):
        digest = hashlib.blake2b(digest_size=8)
        for floor in range(poi.lowest_floor, poi.lowest_floor + poi.floor_count):
            plan = site_plan(poi, floor, config, world)
            if plan is not None:
                digest.update(plan.cells.tobytes())
                digest.update(plan.outside.tobytes())
        overall.update(digest.digest())
        if show_list:
            print(f"{seed} {index} {poi.kind} {poi.x},{poi.y} {digest.hexdigest()}")
    print(f"{seed} {overall.hexdigest()}")
PY
