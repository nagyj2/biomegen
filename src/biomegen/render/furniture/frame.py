"""The framed static map: title bar, scale bar, latitude gutter, longitude ticks around a cell grid."""

from __future__ import annotations

from ...config.model import Config
from ...world.world import World
from ..grid import RGB, CellGrid, Document, Span
from .graticule import latitude_labels, longitude_labels
from .scalebar import scale_bar


def title_text(world: World, config: Config, ascii_only: bool) -> str:
    """Return the title bar text from ``render.furniture.title``."""
    cfg = config.get("render.furniture")
    separator = cfg["title_sep"]["ascii" if ascii_only else "unicode"]
    return cfg["title"].format(
        name=world.island_name or "the island",
        sep=separator,
        seed=world.seed,
        style=world.terrain_style,
        km_w=f"{world.width * world.km_per_col:,.0f}",
        km_h=f"{world.height * world.km_per_row:,.0f}",
    )


def build_frame(world: World, config: Config, grid: CellGrid, ascii_only: bool = False) -> Document:
    """Return the framed map as a document: ``grid`` must show the whole world, one cell per tile.

    The first line is the title and scale bar, then one line per map row with the latitude gutter and
    side borders, then the bottom border with longitude ticks and the longitude labels.
    """
    cfg = config.get("render.furniture")
    margin = int(cfg["margin"])
    frame_fg: RGB = tuple(cfg["frame_fg"])
    dim_fg: RGB = tuple(cfg["dim_fg"])
    horizontal, vertical, top_left, top_right, bottom_left, bottom_right, tick_left, tick_right, tick_bottom = cfg[
        "frame_ascii" if ascii_only else "frame_unicode"
    ]
    degree = "" if ascii_only else "°"
    cols = grid.cols

    bar = scale_bar(world.scale, cols, config, ascii_only)
    top = horizontal * 2 + title_text(world, config, ascii_only)
    if len(top) + len(bar) + 2 <= cols:
        top += horizontal * (cols - len(top) - len(bar) - 2) + bar + horizontal * 2
    top = (top + horizontal * cols)[:cols]
    document: Document = [[Span(" " * margin + top_left + top + top_right, frame_fg, None, True)]]

    latitudes = latitude_labels(world.scale, grid.rows, config, degree)
    for row, cells in enumerate(grid.to_document()):
        label = latitudes.get(row, "")
        document.append(
            [
                Span(label.rjust(margin - 1) + " ", dim_fg),
                Span(tick_left if label else vertical, frame_fg),
                *cells,
                Span(tick_right if label else vertical, frame_fg),
            ]
        )

    bottom = [horizontal] * cols
    longitude_line = [" "] * (cols + 2)
    for col, label in longitude_labels(world.scale, cols, config, degree).items():
        bottom[col] = tick_bottom
        start = col + 1 - len(label) // 2
        window = longitude_line[max(0, start - 1) : start + len(label) + 1]
        if start >= 0 and start + len(label) <= len(longitude_line) and all(ch == " " for ch in window):
            longitude_line[start : start + len(label)] = list(label)
    document.append([Span(" " * margin + bottom_left + "".join(bottom) + bottom_right, frame_fg)])
    document.append([Span(" " * margin + "".join(longitude_line), dim_fg)])
    return document
