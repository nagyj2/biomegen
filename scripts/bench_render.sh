#!/usr/bin/env bash
# Frame time (milliseconds) of the zoom and local detail frames and of the whole explorer frame, best of N runs on a
# seed's world, then a cold pan sweep: the cursor held moving right across the world (and across the largest site),
# every frame composed and diff-written with no warm caches, the way the explorer draws while a key is held.
# Usage: scripts/bench_render.sh [runs] [seed] [COLSxROWS] [view]   (default: 5 runs, fixture seed, 120x36, terrain)
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

runs="${1:-5}"
seed="${2:-${fixture_seed}}"
area="${3:-120x36}"
view_name="${4:-terrain}"

uv run python - "${seed}" "${runs}" "${area}" "${view_name}" <<'PY'
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
from biomegen.render.views import resolve_view, view_names

seed, runs = int(sys.argv[1]), int(sys.argv[2])
area_w, area_h = (int(v) for v in sys.argv[3].split("x"))
view_name = sys.argv[4]
config = load_config(None)
world = pipeline.generate(config, seed)


def best_ms(call) -> float:
    best = float("inf")
    for _ in range(runs):
        start = time.perf_counter()
        call()
        best = min(best, time.perf_counter() - start)
    return best * 1000.0


print(f"seed {seed}, world {world.width}x{world.height}, viewport {area_w}x{area_h} cells, view {view_name}, best of {runs}")
view = resolve_view(config, view_name)
view_index = view_names(config).index(view_name)
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
    state = ExplorerState(mode=mode, scale=scale, recenter=True, view_index=view_index)
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

# The site view of the largest settlement (the biggest window the explorer draws).
from biomegen.explorer.state import step_in
from biomegen.sites import site_geometry

settlements = [poi for poi in world.pois if poi.kind in ("capital", "city")]
biggest = max(settlements, key=lambda poi: site_geometry(poi, config).box_cols * site_geometry(poi, config).box_rows)
state = ExplorerState(scale="zoom", cx=biggest.x, cy=biggest.y, recenter=True, view_index=view_index)
step_in(world, config, state)
size = (area_w, area_h + 12)
overlay = Overlay()
compose = best_ms(lambda: compose_frame(world, config, state, overlay, size))
frame = compose_frame(world, config, state, overlay, size)
sink = io.StringIO()
writer = DiffWriter(sink, "truecolor")


def site_full_write():
    writer.invalidate()
    writer.draw(frame.screen)


full = best_ms(site_full_write)
state.px += 1
moved = compose_frame(world, config, state, overlay, size)


def site_step_write():
    writer.invalidate()
    writer.draw(frame.screen)
    writer.draw(moved.screen)


step = best_ms(site_step_write) - full
print(f"{'site':>6} {compose:9.1f} {full:11.1f} {step:11.1f} {compose + step:7.1f}   ({biggest.kind} at {biggest.x},{biggest.y})")

# The pan sweep: cold caches, the cursor stepped right one tile (one cell inside a site) per frame across the world on
# the starting cursor's row, each frame composed and diff-written. Best-of timings hide the cost of new ground coming
# into view (a camera scroll repaints the screen, a site's plan is built the first time it shows); this does not.
from biomegen.explorer.state import move_cursor
from biomegen.sites import clear_cache


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))]


def sweep(state: ExplorerState, steps: int) -> None:
    clear_cache()
    sink = io.StringIO()
    writer = DiffWriter(sink, "truecolor")
    overlay = Overlay()
    composes, writes, sizes = [], [], []
    for _ in range(steps):
        start = time.perf_counter()
        frame = compose_frame(world, config, state, overlay, size)
        middle = time.perf_counter()
        before = sink.tell()
        writer.draw(frame.screen)
        composes.append((middle - start) * 1000.0)
        writes.append((time.perf_counter() - middle) * 1000.0)
        sizes.append((sink.tell() - before) / 1024.0)
        move_cursor(world, config, state, 1, 0)
    label = state.scale if state.poi is None else "site"
    total = sum(composes) + sum(writes)
    print(
        f"{label:>6} {steps:6d} {percentile(composes, 0.5):7.1f} {percentile(composes, 0.95):7.1f} {max(composes):7.1f}"
        f" {percentile(writes, 0.5):7.1f} {max(writes):7.1f} {percentile(sizes, 0.5):7.1f} {max(sizes):7.1f}"
        f" {total / steps:7.1f}"
    )


print()
print(f"pan sweep, cold caches, {area_w}x{area_h + 12} terminal: compose and write ms, KiB written per frame")
print(f"{'scale':>6} {'frames':>6} {'cmp p50':>7} {'cmp p95':>7} {'cmp max':>7} {'wr p50':>7} {'wr max':>7}"
      f" {'KiB p50':>7} {'KiB max':>7} {'mean ms':>7}")
start_x, start_y = initial_cursor(world, config)
for scale in ("zoom", "local"):
    sweep(ExplorerState(scale=scale, cx=0, cy=start_y, recenter=True, view_index=view_index), world.width)
clear_cache()
state = ExplorerState(scale="zoom", cx=biggest.x, cy=biggest.y, recenter=True, view_index=view_index)
step_in(world, config, state)
geometry = site_geometry(biggest, config)
state.px = 0
sweep(state, geometry.cols - 1)
PY
