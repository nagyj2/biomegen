"""The roads layer: road tiles drawn with a glyph that follows their connections."""

from __future__ import annotations

import numpy as np

from ...config.model import Config
from ...sampling.detail import SCALE_LOCAL, DetailSampler
from ...sampling.roads import KIND_NAMES, RoadBed, road_bed
from ..colors import scale_colors
from ..grid import CellGrid
from . import LAYERS, LayerContext

# Bits of the eight-neighbour connection mask, clockwise from north.
_N, _NE, _E, _SE, _S, _SW, _W, _NW = 1, 2, 4, 8, 16, 32, 64, 128
_CARDINAL_INDEX = ((_N, 1), (_E, 2), (_S, 4), (_W, 8))  # mask bit -> bit of the 16-entry cardinal glyph index
_RISING = (_NE, _SW)  # neighbours on a "╱" line; the other two diagonals (_SE, _NW) lie on a "╲" line
_DIAGONALS = (_NE, _SE, _SW, _NW)


def connection_mask8(road: np.ndarray) -> np.ndarray:
    """Return, per tile, a bit mask of its road links (N 1, NE 2, E 4, SE 8, S 16, SW 32, W 64, NW 128).

    An orthogonal neighbour counts when it is road. A diagonal neighbour counts only when neither orthogonal tile
    between it and this tile is road: otherwise the two already join through that tile, and the corner would be
    drawn as a spurious diagonal.
    """
    padded = np.pad(road.astype(bool), 1)
    north, east = padded[:-2, 1:-1], padded[1:-1, 2:]
    south, west = padded[2:, 1:-1], padded[1:-1, :-2]
    neighbours = (
        (_N, north),
        (_NE, padded[:-2, 2:] & ~north & ~east),
        (_E, east),
        (_SE, padded[2:, 2:] & ~south & ~east),
        (_S, south),
        (_SW, padded[2:, :-2] & ~south & ~west),
        (_W, west),
        (_NW, padded[:-2, :-2] & ~north & ~west),
    )
    mask = np.zeros(road.shape, dtype=np.uint8)
    for bit, present in neighbours:
        mask |= np.where(present, bit, 0).astype(np.uint8)
    return mask


def road_glyph_table(config: Config, ascii_only: bool) -> np.ndarray:
    """Return the glyph for each of the 256 eight-neighbour masks, so every way two roads can join is drawable.

    No diagonal neighbour: the box-drawing glyph for the cardinal mask (``render.roads.glyphs``), so an orthogonal
    junction is drawn as the matching tee or cross. Any diagonal neighbour: the junction glyph (an asterisk) wherever
    three or more links meet. Fewer than three: ``╱`` or ``╲`` along a line, ``╳`` where two diagonals bend, and the
    slant of the diagonal when a single diagonal link joins an orthogonal one.
    """
    cfg = config.get("render.roads")
    key = "ascii" if ascii_only else "glyphs"
    cardinal = cfg[key]
    rising, falling, crossing = cfg["diagonal"][key]
    junction = cfg["junction"][key]
    table = np.empty(256, dtype="U1")
    for mask in range(256):
        index = sum(value for bit, value in _CARDINAL_INDEX if mask & bit)
        diagonal = [bit for bit in _DIAGONALS if mask & bit]
        slants = {rising if bit in _RISING else falling for bit in diagonal}
        if not diagonal:
            table[mask] = cardinal[index]
        elif bin(mask).count("1") >= 3:
            table[mask] = junction
        elif len(slants) == 1 and (index or len(diagonal) <= 2):
            table[mask] = next(iter(slants))
        else:
            table[mask] = crossing
    return table


def _bridges(ctx: LayerContext, grid: CellGrid, found: RoadBed, dry: np.ndarray) -> None:
    """Draw where the road bed lies over water: a deck, with railings in the band as wide again beside it."""
    cfg = ctx.config
    glyphs = cfg.get("render.bridge_glyphs") or {}
    colors = cfg.get("render.detail_colors")
    open_water = ctx.sampler.inside & ~dry & ~ctx.site_mask
    for mask, part in ((found.rail & open_water & ~found.bed, "wall"), (found.bed & open_water, "deck")):
        if mask.any():
            grid.put(
                mask,
                glyph=str(glyphs.get(part, ":" if part == "deck" else "#")),
                fg=tuple(colors[f"{part}_fg"]),
                bg=scale_colors(colors[f"{part}_bg"], ctx.shade),
            )


def _detail_roads(ctx: LayerContext, grid: CellGrid, sampler: DetailSampler) -> None:
    """Draw the road network as a thin meandering bed (see :func:`biomegen.sampling.roads.road_bed`).

    Water and river cells are left to bridges; the bed carries clutter glyphs (``render.road_clutter``, plus
    ``road_clutter_local`` at the local scale).
    """
    cfg = ctx.config
    found = road_bed(sampler, ctx.world, cfg)
    if found is None:
        return
    kind = found.kind
    dry = ctx.land & ~ctx.river
    _bridges(ctx, grid, found, dry)
    bed = found.bed & dry & ~ctx.site_mask
    if not bed.any():
        return
    key = "ascii" if ctx.ascii_only else "glyphs"
    bed_glyphs = cfg.get("render.road_bed")[key]
    lone = cfg.get("render.roads")[key][0]
    glyph = np.array([bed_glyphs[name] for name in KIND_NAMES] + [lone], dtype="U1")[kind]
    chance = ctx.scatter("road")
    choice = ctx.scatter("road", "glyph")
    clutter = cfg.get("render.road_clutter") or {}
    local = cfg.get("render.road_clutter_local") or {}
    clutter_glyphs = list(clutter.get("glyphs") or [])
    clutter_density = float(clutter.get("density", 0.0)) if clutter_glyphs else 0.0
    if clutter_glyphs:
        pick = np.minimum((choice * len(clutter_glyphs)).astype(np.int64), len(clutter_glyphs) - 1)
        glyph = np.where(chance < clutter_density, np.array(clutter_glyphs, dtype="U1")[pick], glyph)
    local_glyphs = list(local.get("glyphs") or [])
    if sampler.scale == SCALE_LOCAL and local_glyphs:
        pick = np.minimum((choice * len(local_glyphs)).astype(np.int64), len(local_glyphs) - 1)
        extra = (chance >= clutter_density) & (chance < clutter_density + float(local.get("density", 0.0)))
        glyph = np.where(extra, np.array(local_glyphs, dtype="U1")[pick], glyph)
    colors = cfg.get("render.detail_colors")
    grid.put(bed, glyph=glyph, fg=tuple(colors["road_fg"]), bg=scale_colors(colors["road_bg"], ctx.shade))


@LAYERS.register("roads")
def roads_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Draw road tiles with the glyph for their eight-neighbour mask (:func:`road_glyph_table`); the fill is kept.

    At the detail scales roads are a thin bed instead (see :func:`_detail_roads`).
    """
    if isinstance(ctx.sampler, DetailSampler):
        _detail_roads(ctx, grid, ctx.sampler)
        return
    cfg = ctx.config.get("render.roads")
    road = ctx.sampler.inside & (ctx.sampler.nearest(ctx.world.road) > 0)
    if not road.any():
        return
    glyphs = road_glyph_table(ctx.config, ctx.ascii_only)
    grid.put(road, glyph=glyphs[ctx.sampler.nearest(connection_mask8(ctx.world.road))], fg=tuple(cfg["fg"]))
