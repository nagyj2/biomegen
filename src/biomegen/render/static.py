"""Static rendering: one view of the whole world as a framed map with its legend, with no terminal I/O.

This is the path behind ``--view`` and the exporters. It composes the layer stack, the frame furniture
and the legend into a :class:`StaticRender`; the caller picks a back-end and writes the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..config.model import Config
from ..world.overlay import Overlay
from ..world.world import World
from .furniture.frame import build_frame
from .furniture.legend import build_legend
from .grid import CellGrid, Document
from .layers import build_grid
from .sampler import Sampler
from .views import resolve_view


@dataclass(frozen=True)
class StaticRender:
    """A finished static map.

    Attributes:
        grid: The map body, one cell per world tile (what SVG and PNG draw).
        document: The framed map followed by the legend (what ANSI, plain and HTML print).
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
    """
    view = resolve_view(config, view_name)
    sampler = Sampler.viewport(world, world.height, world.width)
    grid = build_grid(world, config, view, sampler, overlay, ascii_only, color, labels)
    document = build_frame(world, config, grid, ascii_only)
    if legend:
        width = int(config.get("render.furniture.margin")) + grid.cols + 2
        document += build_legend(world, config, view, width, ascii_only)
    return StaticRender(grid, document)
