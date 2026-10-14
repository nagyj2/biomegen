#!/usr/bin/env bash
# Frame time (milliseconds) of the zoom and local detail frames and of the whole explorer frame, best of N runs on a
# seed's world.
# Usage: scripts/bench_render.sh [runs] [seed] [COLSxROWS]   (default: 5 runs, fixture seed, 120x36)
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

runs="${1:-5}"
seed="${2:-${fixture_seed}}"
area="${3:-120x36}"

uv run python - "${seed}" "${runs}" "${area}" <<'PY'
import sys
import time

from biomegen import pipeline
from biomegen.config import load_config
import io

from biomegen.explorer.app import compose_frame
from biomegen.explorer.state import ViewState as ExplorerState
from biomegen.explorer.state import initial_cursor
from biomegen.explorer.writer import DiffWriter
from biomegen.sampling.detail import detail_sampler
from biomegen.render.layers import build_grid
from biomegen.render.views import resolve_view

seed, runs = int(sys.argv[1]), int(sys.argv[2])
area_w, area_h = (int(v) for v in sys.argv[3].split("x"))
config = load_config(None)
world = pipeline.generate(config, seed)


def best_ms(call) -> float:
    best = float("inf")
    for _ in range(runs):
        start = time.perf_counter()
        call()
        best = min(best, time.perf_counter() - start)
    return best * 1000.0


print(f"seed {seed}, world {world.width}x{world.height}, viewport {area_w}x{area_h} cells, best of {runs}")
view = resolve_view(config, "terrain")
print(f"{'scale':>6} {'cells':>7} {'layers ms':>10}")
for scale in ("zoom", "local"):
    probe = detail_sampler(world, config, scale, area_w, area_h, 0, 0)
    cam_x = max(0, world.width // 2 - probe.tiles_w // 2)
    cam_y = max(0, world.height // 2 - probe.tiles_h // 2)
    sampler = detail_sampler(world, config, scale, area_w, area_h, cam_x, cam_y)
    layers = best_ms(lambda: build_grid(world, config, view, detail_sampler(world, config, scale, area_w, area_h, cam_x, cam_y)))
    print(f"{scale:>6} {probe.tiles_w * probe.cell_w * probe.tiles_h * probe.cell_h:7d} {layers:10.1f}")

# The whole explorer frame: compose (layers, cursor, panel) and diff-write, at the same area plus a 12-row panel.
from biomegen.world.overlay import Overlay

print()
print(f"explorer frame on a {area_w}x{area_h + 12} terminal (budget 33 ms), best of {runs}")
print(f"{'scale':>6} {'compose':>9} {'full write':>11} {'step write':>11} {'frame':>7}")
for scale, mode in (("map", "fit"), ("map", "onetoone"), ("zoom", "fit"), ("local", "fit")):
    state = ExplorerState(mode=mode, scale=scale, recenter=True)
    state.cx, state.cy = initial_cursor(world, config)
    size = (area_w, area_h + 12)
    overlay = Overlay()
    compose = best_ms(lambda: compose_frame(world, config, state, overlay, size))
    frame = compose_frame(world, config, state, overlay, size)
    sink = io.StringIO()
    writer = DiffWriter(sink, "truecolor")

    def full_write():
        writer.invalidate()
        writer.draw(frame.screen)

    full = best_ms(full_write)
    state.cx += 1
    moved = compose_frame(world, config, state, overlay, size)

    def step_write():
        writer.invalidate()
        writer.draw(frame.screen)
        writer.draw(moved.screen)

    step = best_ms(step_write) - full
    label = scale if scale != "map" else f"map-{mode}"
    print(f"{label:>6} {compose:9.1f} {full:11.1f} {step:11.1f} {compose + step:7.1f}")
PY
