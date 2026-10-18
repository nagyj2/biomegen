#!/usr/bin/env bash
# Per-stage generation time (seconds) at several world sizes, best of N runs on a seed.
# Usage: scripts/bench.sh [runs] [WxH ...]   (default: 3 runs at 128x32 192x48 192x75 256x64 320x80)
#        scripts/bench.sh --sim [runs] [WxH ...]   the simulation spike: what a tick would cost (default: 5 runs at 240x60)
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

help_if_asked "Usage: scripts/bench.sh [--seed SEED] [--sim] [runs] [WxH ...]   (no --seed: random seed; --sim times the claim Dijkstra, the front distance and the danger field)" "$@"
bench_seed_args "$@"
set -- "${bench_args[@]}"
mode=stages
if [[ "${1:-}" == "--sim" ]]; then mode=sim; shift; fi
runs="${1:-$([[ "$mode" == sim ]] && echo 5 || echo 3)}"
shift || true
sizes=("$@")
if [[ ${#sizes[@]} -eq 0 ]]; then
    if [[ "$mode" == sim ]]; then sizes=(240x60); else sizes=(128x32 192x48 192x75 256x64 320x80); fi
fi

if [[ "$mode" == sim ]]; then
    # Measurement only: nothing here is simulation code. It times the three pieces a tick would redo (plan section 7, 9b),
    # using the stage's own private claim function, so the numbers are what a later `sim/` would pay.
    uv run python - "${bench_seed}" "${runs}" "${sizes[@]}" <<'PY'
import copy
import math
import sys
import time

import numpy as np
from scipy import ndimage

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.pipeline.civilization import realms
from biomegen.util import rng

seed, runs, sizes = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3:]


def best_ms(work) -> float:
    """The best of ``runs`` timings of ``work()``, in milliseconds."""
    best = math.inf
    for _ in range(runs):
        start = time.perf_counter()
        work()
        best = min(best, time.perf_counter() - start)
    return best * 1000.0


for size in sizes:
    width, height = (int(v) for v in size.split("x"))
    config = load_config(None)
    config.data["world"].update({"width": width, "height": height})
    world = pipeline.generate(config, seed)
    scale = world.scale
    stream = rng.derive(seed, "bench", "sim")

    # 1. The claim Dijkstra over every realm (what a border recompute reruns), the cost surface it needs, and cheaper forms.
    solid = realms.solid_mask(world)
    enter = realms._enter_cost(world, config, solid)
    seeds = []
    for realm in world.realms:
        if realm.seat_poi >= 0:
            x, y = world.pois[realm.seat_poi].x, world.pois[realm.seat_poi].y
        else:
            y, x = (int(v) for v in np.argwhere(world.realm_id == realm.id)[0])
        seeds.append(realms._Seed(realm.kind, realms._draw_strength(config, realm.kind, stream), x, y, realm.seat_poi))
    pair = seeds[:2]
    short = copy.deepcopy(config)
    short.data["politics"]["claim_budget_km"] = float(config.get("politics.claim_budget_km")) / 4.0
    print(f"{size} ({scale.km_per_col:.1f}x{scale.km_per_row:.1f} km/cell, {len(seeds)} realms, best of {runs}):")
    print(f"  cost surface (enter cost)        {best_ms(lambda: realms._enter_cost(world, config, solid)):8.1f} ms")
    print(f"  claim Dijkstra, every realm      {best_ms(lambda: realms._claim(world, config, enter, solid, seeds)):8.1f} ms")
    print(f"  claim Dijkstra, one pair         {best_ms(lambda: realms._claim(world, config, enter, solid, pair)):8.1f} ms")
    print(f"  claim Dijkstra, quarter budget   {best_ms(lambda: realms._claim(world, short, enter, solid, seeds)):8.1f} ms")

    # 2. Front distance: km from every cell to the nearest war front cell.
    front = world.front
    print(
        f"  front distance ({int(front.sum())} front cells)   "
        f"{best_ms(lambda: ndimage.distance_transform_edt(~front, sampling=(scale.km_per_row, scale.km_per_col))):8.1f} ms"
    )

    # 3. Danger field of the bandit holds: one nearest-source transform, and a window per source.
    sources = [
        (p.x, p.y, float(p.bandit_strength), float(config.get(f"tables.pois.{p.kind}.bandit_radius_km", 0.0)))
        for p in world.pois
        if p.bandit_strength > 0 and float(config.get(f"tables.pois.{p.kind}.bandit_radius_km", 0.0)) > 0.0
    ]

    def danger_nearest() -> np.ndarray:
        mask = np.zeros(world.front.shape, dtype=bool)
        strength = np.zeros(world.front.shape)
        reach = np.ones(world.front.shape)
        for x, y, s, r in sources:
            mask[y, x], strength[y, x], reach[y, x] = True, s, r
        km, (iy, ix) = ndimage.distance_transform_edt(
            ~mask, sampling=(scale.km_per_row, scale.km_per_col), return_indices=True
        )
        return strength[iy, ix] * np.clip(1.0 - km / reach[iy, ix], 0.0, 1.0)

    def danger_windows() -> np.ndarray:
        field = np.zeros(world.front.shape)
        for x, y, s, r in sources:
            rx, ry = math.ceil(r / scale.km_per_col), math.ceil(r / scale.km_per_row)
            x0, x1, y0, y1 = max(0, x - rx), min(world.width, x + rx + 1), max(0, y - ry), min(world.height, y + ry + 1)
            yy, xx = np.ogrid[y0:y1, x0:x1]
            km = np.hypot((xx - x) * scale.km_per_col, (yy - y) * scale.km_per_row)
            field[y0:y1, x0:x1] += s * np.clip(1.0 - km / r, 0.0, 1.0)
        return field

    print(f"  danger field, nearest source ({len(sources)})  {best_ms(danger_nearest):8.1f} ms")
    print(f"  danger field, a window each ({len(sources)})   {best_ms(danger_windows):8.1f} ms")
PY
    exit 0
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
