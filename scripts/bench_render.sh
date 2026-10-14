#!/usr/bin/env bash
# Frame time (milliseconds) of the zoom and local detail frames, the old builder against the new layers,
# best of N runs on a seed's world.
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
from biomegen.render.detail import detail_sampler
from biomegen.render.layers import build_grid
from biomegen.render.state import ViewState
from biomegen.render.views import resolve_view
from biomegen.render.zoom_view import build_detail_frame, detail_cell_size

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
print(f"{'scale':>6} {'cells':>7} {'old ms':>8} {'new ms':>8} {'new/old':>8}")
for scale in ("zoom", "local"):
    cell_w, cell_h = detail_cell_size(scale, config, area_w, area_h)
    tiles_w, tiles_h = max(1, area_w // cell_w), max(1, area_h // cell_h)
    state = ViewState(scale=scale, cx=world.width // 2, cy=world.height // 2)
    state.cam_x = max(0, state.cx - tiles_w // 2)
    state.cam_y = max(0, state.cy - tiles_h // 2)
    old = best_ms(lambda: build_detail_frame(world, config, state, area_w, area_h, cell_w, cell_h))
    new = best_ms(lambda: build_grid(world, config, view, detail_sampler(world, config, scale, area_w, area_h, state.cam_x, state.cam_y)))
    print(f"{scale:>6} {tiles_w * cell_w * tiles_h * cell_h:7d} {old:8.1f} {new:8.1f} {new / old:8.2f}")

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
