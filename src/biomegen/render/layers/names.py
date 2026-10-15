"""The labels layer: names of landmasses (or realms), ranges, seas and lakes placed on open cells.

The module is called ``names`` so it does not shadow the ``labels`` argument used elsewhere in this package.
"""

from __future__ import annotations

import math

import numpy as np

from ...world.entities import GeoFeature
from ..colors import mix_colors, scale_colors
from ..grid import CellGrid
from . import LAYERS, LayerContext


class _Placer:
    """Places text on a grid without overlapping markers, earlier labels or the grid edge."""

    def __init__(self, ctx: LayerContext, grid: CellGrid) -> None:
        self.ctx = ctx
        self.grid = grid
        self.reserved = grid.bold.copy()  # markers drawn by earlier layers
        self.labelled = np.zeros_like(self.reserved)
        self.fill_scale = float(ctx.config.get("render.labels.fill_scale"))

    def fits(self, col: int, row: int, text: str) -> bool:
        if row < 0 or row >= self.grid.rows or col < 1 or col + len(text) > self.grid.cols - 1:
            return False
        window = slice(col - 1, col + len(text) + 1)
        return not (self.reserved[row, window].any() or self.labelled[row, window].any())

    def put(self, col: int, row: int, text: str, fg: tuple[int, ...]) -> None:
        span = slice(col, col + len(text))
        self.grid.glyph[row, span] = list(text)
        self.grid.fg[row, span] = fg
        self.grid.bg[row, span] = scale_colors(self.grid.bg[row, span], self.fill_scale)
        self.grid.bold[row, span] = True
        self.labelled[row, span] = True

    def place(self, text: str, positions: list[tuple[int, int]], fg: tuple[int, ...]) -> bool:
        """Draw ``text`` at the first of ``positions`` (tile coordinates of its first letter) that fits."""
        for tile_x, tile_y in positions:
            cell = self.ctx.sampler.cell_of(tile_x, tile_y)
            if cell is not None and self.fits(cell[0], cell[1], text):
                self.put(cell[0], cell[1], text, fg)
                return True
        return False


def _around(feature: GeoFeature, text: str, count: int, aspect: float) -> list[tuple[int, int]]:
    """Return up to ``count`` label start positions, nearest the centre of the feature's cells first."""
    cells = feature.cells
    centre_x = sum(x for x, _ in cells) / len(cells)
    centre_y = sum(y for _, y in cells) / len(cells)
    nearest = sorted(cells, key=lambda c: (math.hypot(c[0] - centre_x, (c[1] - centre_y) * aspect), c[1], c[0]))
    return [(x - len(text) // 2, y) for x, y in nearest[:count]]


def _realm_labels(ctx: LayerContext, placer: _Placer, cfg: dict) -> None:
    """Name the realms in capitals near their centres, largest first, in a lightened shade of their colour."""
    world = ctx.world
    kinds = set(cfg["realm_kinds"])
    big = [r for r in world.realms if r.short and r.kind in kinds and r.area_km2 >= float(cfg["realm_min_area_km2"])]
    aspect = world.scale.aspect
    for realm in sorted(big, key=lambda r: (-r.area_km2, r.id)):
        ys, xs = np.nonzero(world.realm_id == realm.id)
        text = realm.short.upper()
        nearest = np.lexsort((xs, ys, np.hypot(xs - xs.mean(), (ys - ys.mean()) * aspect)))
        starts = [(int(xs[i]) - len(text) // 2, int(ys[i])) for i in nearest[: int(cfg["realm_candidates"])]]
        colour = mix_colors(realm.color, (255, 255, 255), float(cfg["realm_lighten"]))
        placer.place(text, starts, tuple(int(c) for c in colour))


@LAYERS.register("labels")
def labels_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Name the largest landmasses and ranges (the realms in a political view), seas and lakes when ``labels`` is all.

    Settings are ``render.labels``.
    """
    if ctx.labels != "all":
        return
    cfg = ctx.config.get("render.labels")
    world = ctx.world
    placer = _Placer(ctx, grid)
    aspect = world.scale.aspect
    by_kind: dict[str, list[GeoFeature]] = {}
    for feature in world.features:
        by_kind.setdefault(feature.kind, []).append(feature)

    def largest(kind: str, limit: int) -> list[GeoFeature]:
        features = [f for f in by_kind.get(kind, []) if f.name]
        return sorted(features, key=lambda f: (-f.area_km2, f.id))[:limit]

    if ctx.view.political:
        _realm_labels(ctx, placer, cfg)
    else:
        for landmass in largest("landmass", int(cfg["max_landmasses"])):
            text = " ".join(landmass.name.upper())
            if len(text) > grid.cols // 3:
                text = landmass.name.upper()
            inland = sorted(landmass.cells, key=lambda c: (-float(world.dist_to_ocean[c[1], c[0]]), c[1], c[0]))
            starts = [(x - len(text) // 2, y) for x, y in inland[: int(cfg["landmass_candidates"])]]
            placer.place(text, starts, tuple(cfg["landmass_fg"]))
        for mountains in largest("range", int(cfg["max_ranges"])):
            if mountains.cells:
                placer.place(
                    mountains.name,
                    _around(mountains, mountains.name, int(cfg["range_candidates"]), aspect),
                    tuple(cfg["range_fg"]),
                )
    for sea in sorted((f for f in by_kind.get("sea", []) if f.name), key=lambda f: f.id):
        x, y = sea.anchor
        starts = [(x - len(sea.name) // 2 + dx, y + dy) for dy in (0, 1, -1, 2, -2) for dx in (0, -4, 4)]
        placer.place(sea.name, starts, tuple(cfg["sea_fg"]))
    for lake in largest("lake", int(cfg["max_lakes"])):
        if lake.cells:
            placer.place(
                lake.name, _around(lake, lake.name, int(cfg["lake_candidates"]), aspect), tuple(cfg["lake_fg"])
            )
