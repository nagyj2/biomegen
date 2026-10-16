#!/usr/bin/env bash
# Cold site-plan build cost per kind of POI: the plan of every settlement, ruin and homestead built from an empty cache,
# ground floor, pooled over the seeds. Two measures: CPU milliseconds (best of N runs; noisy when the machine is loaded)
# and the Python function calls of one build (deterministic, so a change in work shows even when the clock is noisy).
# The 8d budget: no row's mean grows more than 25%.
# Usage: scripts/bench_sites.sh [--seed S]... [runs]   (default: seeds 42 and 7, 3 runs)
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

help_if_asked "Usage: scripts/bench_sites.sh [--seed SEED]... [runs]   (default: seeds 42 7, 3 runs)" "$@"
seeds=()
runs=3
while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--seed" ]]; then seeds+=("${2:?--seed needs a value}"); shift 2
    else runs="$1"; shift; fi
done
if [[ ${#seeds[@]} -eq 0 ]]; then seeds=(42 7); fi

uv run python - "${runs}" "${seeds[@]}" <<'PY'
import cProfile
import pstats
import sys
import time
from collections import defaultdict

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.sites import site_plan
from biomegen.sites.plan import clear_cache

runs = int(sys.argv[1])
seeds = [int(v) for v in sys.argv[2:]]
config = load_config(None)
KINDS = ("capital", "city", "town", "village", "hamlet", "homestead", "ruin")
times: dict[str, list[float]] = defaultdict(list)
calls: dict[str, list[int]] = defaultdict(list)
for seed in seeds:
    world = pipeline.generate(config, seed)
    for poi in world.pois:
        if poi.kind not in KINDS:
            continue
        key = poi.kind if poi.kind != "ruin" else f"ruin({poi.ruin_of or 'none'})"
        best = float("inf")
        for _ in range(runs):
            clear_cache()
            start = time.process_time()
            site_plan(poi, 0, config, world)
            best = min(best, time.process_time() - start)
        times[key].append(best * 1000.0)
        clear_cache()
        profiler = cProfile.Profile()
        profiler.enable()
        site_plan(poi, 0, config, world)
        profiler.disable()
        calls[key].append(pstats.Stats(profiler).total_calls)  # type: ignore[attr-defined]
print(f"cold site plan builds, seeds {' '.join(str(s) for s in seeds)}, best of {runs}")
print(f"{'kind':<16} {'n':>4} {'mean ms':>9} {'max ms':>9} {'mean calls':>11}")
for key in sorted(times):
    values = times[key]
    print(f"{key:<16} {len(values):4d} {sum(values) / len(values):9.1f} {max(values):9.1f} {sum(calls[key]) / len(calls[key]):11.0f}")
PY
