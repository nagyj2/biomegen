"""Static rendering: one view of the whole world as a framed map with its legend, with no terminal I/O.

This is the path behind ``--view`` and the exporters. It composes the layer stack, the frame furniture
and the legend into a :class:`StaticRender`; the caller picks a back-end and writes the result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ..config.model import Config
from ..sampling.detail import SCALE_SITE, centred_detail_sampler
from ..sampling.sampler import Sampler
from ..sites import site_at, site_floor_range, site_geometry, site_places, window_sampler
from ..world.overlay import Overlay
from ..world.reader import WorldReader
from ..world.world import World
from .furniture.frame import build_frame
from .furniture.legend import build_legend
from .grid import CellGrid, Document
from .layers import build_grid
from .views import resolve_view


@dataclass(frozen=True)
class StaticRender:
    """A finished static map.

    Attributes:
        grid: The map body, one cell per world tile (what SVG and PNG draw); a detail render has many cells
            per tile.
        document: The framed map followed by the legend (what ANSI, plain and HTML print); a detail render
            is the bare grid.
    """

    grid: CellGrid
    document: Document


def render_static(
    world: World,
    config: Config,
    view_name: str = "terrain",
    *,
    labels: str = "all",
    ascii_only: bool = False,
    color: bool = True,
    legend: bool = True,
    overlay: Optional[Overlay] = None,
    reader: Optional[WorldReader] = None,
) -> StaticRender:
    """Render view ``view_name`` of the whole ``world``.

    Args:
        world: The generated world.
        config: The merged configuration.
        view_name: A key of ``render.views``.
        labels: ``"all"`` draws feature names, ``"none"`` leaves them off.
        ascii_only: Use only 7-bit glyphs.
        color: Whether the output is coloured; without colour sparse biomes draw on every cell.
        legend: Append the legend and gazetteer.
        overlay: Runtime edits to composite, or ``None``.
        reader: The simulation's view of the world; ``None`` renders the world as generated.
    """
    view = resolve_view(config, view_name)
    sampler = Sampler.viewport(world, world.height, world.width)
    grid = build_grid(world, config, view, sampler, overlay, ascii_only, color, labels, reader=reader)
    document = build_frame(world, config, grid, ascii_only)
    if legend:
        width = int(config.get("render.furniture.margin")) + grid.cols + 2
        document += build_legend(world, config, view, width, ascii_only, reader)
    return StaticRender(grid, document)


def render_detail(
    world: World,
    config: Config,
    scale: str,
    view_name: str = "terrain",
    *,
    at: Optional[tuple[int, int]] = None,
    area: tuple[int, int] = (120, 36),
    ascii_only: bool = False,
    color: bool = True,
    floor: int = 0,
    overlay: Optional[Overlay] = None,
    reader: Optional[WorldReader] = None,
) -> StaticRender:
    """Render a magnified part of the world: the zoom or local scale centred on one tile, or the site view of a POI.

    Args:
        world: The generated world.
        config: The merged configuration.
        scale: ``"zoom"``, ``"local"`` or ``"site"`` (the site covering ``at``: a plan cell per terminal cell,
            centred on it and clipped to ``area``).
        view_name: A key of ``render.views``; its ``detail_layers`` are drawn.
        at: The tile to centre on; the middle of the map when ``None``.
        area: Columns and rows available. The grid holds whole tiles only, so it may be a little smaller.
        ascii_only: Use only 7-bit glyphs.
        color: Whether the output is coloured.
        floor: The floor of multi-floor interiors to draw.
        overlay: Runtime edits to composite, or ``None``.
        reader: The simulation's view of the world; ``None`` renders the world as generated.
    """
    view = resolve_view(config, view_name)
    centre = at if at is not None else (world.width // 2, world.height // 2)
    if scale == SCALE_SITE:
        poi = site_at(world, config, centre[0], centre[1], reader)
        geometry = site_geometry(poi, config) if poi is not None else None
        if poi is None or geometry is None:
            hint = _nearest_site(world, config, centre, reader)
            raise ValueError(f"no site at tile {centre[0]},{centre[1]}{hint}")
        col, row = geometry.cell_at(float(centre[0]), float(centre[1]))
        cols, rows = min(area[0], geometry.cols), min(area[1], geometry.rows)
        origin = (_camera(col, cols, geometry.cols), _camera(row, rows, geometry.rows))
        sampler = window_sampler(world, config, geometry, origin, (rows, cols))
        lowest, highest = site_floor_range(poi, config)
        floor = max(lowest, min(floor, highest))
    else:
        sampler = centred_detail_sampler(world, config, scale, area[0], area[1], centre)
    grid = build_grid(world, config, view, sampler, overlay, ascii_only, color, floor=floor, reader=reader)
    return StaticRender(grid, grid.to_document())


def _camera(cell: int, size: int, total: int) -> int:
    """The first cell of a ``size``-wide view over ``total`` cells that is centred on ``cell`` and kept inside them."""
    return max(0, min(cell - size // 2, total - size))


def _nearest_site(world: World, config: Config, tile: tuple[int, int], reader: Optional[WorldReader] = None) -> str:
    """A hint for a tile with no site: the point of interest with a site nearest to it (empty when there is none)."""
    places = site_places(reader if reader is not None else WorldReader(world), config)
    found = [(math.hypot(poi.x - tile[0], poi.y - tile[1]), poi) for _i, poi, _g in places]
    if not found:
        return ""
    _distance, poi = min(found, key=lambda item: (item[0], item[1].y, item[1].x))
    return f" (nearest site: {poi.name or poi.kind} ({poi.kind}) at {poi.x},{poi.y})"
