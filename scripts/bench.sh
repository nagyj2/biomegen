#!/usr/bin/env bash
# Per-stage generation time (seconds) at several world sizes, best of N runs on a seed.
# Usage: scripts/bench.sh [runs] [WxH ...]   (default: 3 runs at 128x32 192x48 192x75 256x64 320x80)
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

help_if_asked "Usage: scripts/bench.sh [--seed SEED] [runs] [WxH ...]   (no --seed: random seed)" "$@"
bench_seed_args "$@"
set -- "${bench_args[@]}"
runs="${1:-3}"
shift || true
sizes=("$@")
if [[ ${#sizes[@]} -eq 0 ]]; then
    sizes=(128x32 192x48 192x75 256x64 320x80)
fi

uv run python - "${bench_seed}" "${runs}" "${sizes[@]}" <<'PY'
import sys

from biomegen import pipeline
from biomegen.config import load_config

seed, runs, sizes = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3:]
table = []
for size in sizes:
    width, height = (int(v) for v in size.split("x"))
    config = load_config(None)
    config.data["world"].update({"width": width, "height": height})
    best: dict[str, float] = {}
    for _ in range(runs):
        timings: dict[str, float] = {}
        world = pipeline.generate(config, seed, timings)
        for stage, seconds in timings.items():
            best[stage] = min(best.get(stage, seconds), seconds)
    km = f"{world.km_per_col:.1f}x{world.km_per_row:.1f}"
    table.append((size, km, best))

stages = list(table[0][2])
print(f"{'size':>8} {'km/cell':>10} " + " ".join(f"{s[:9]:>9}" for s in stages) + f" {'total':>7}")
for size, km, best in table:
    cells = " ".join(f"{best[s]:9.3f}" for s in stages)
    print(f"{size:>8} {km:>10} {cells} {sum(best.values()):7.3f}")
PY
