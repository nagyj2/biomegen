"""The labels layer: names of landmasses (or realms), ranges, seas and lakes placed on open cells.

The module is called ``names`` so it does not shadow the ``labels`` argument used elsewhere in this package.
"""

from __future__ import annotations

import math

import numpy as np

from ...config.model import Config
from ...util.geometry import distance_to
from ...world.derived import derived
from ...world.entities import GeoFeature
from ...world.territory import fallen_owner, predecessor_owner
from ...world.tile import WaterType
from ...world.world import World
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

    def fits(self, col: int, row: int, text: str, over_water: bool = False) -> bool:
        if row < 0 or row >= self.grid.rows or col < 1 or col + len(text) > self.grid.cols - 1:
            return False
        if over_water:
            span = slice(col, col + len(text))
            if not (self.ctx.sampler.inside[row, span] & ~self.ctx.land[row, span]).all():
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

    def place(self, text: str, positions: list[tuple[int, int]], fg: tuple[int, ...], over_water: bool = False) -> bool:
        """Draw ``text`` at the first of ``positions`` (tile coordinates of its first letter) that fits.

        ``over_water`` also requires every cell under the text to be water.
        """
        for tile_x, tile_y in positions:
            cell = self.ctx.sampler.cell_of(tile_x, tile_y)
            if cell is not None and self.fits(cell[0], cell[1], text, over_water):
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


def _sea_middles(world: World, config: Config, seas: list[GeoFeature]) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(clearance_km, owner)`` per tile: the salt-water distance to land or the map edge, and the nearest sea.

    ``owner`` is the index in ``seas`` of the sea whose anchor is nearest (-1 off the salt water). A sea's anchor is its
    point farthest from land, which on an ocean framed by the map edge lies against the edge; the tile of its water
    with the greatest clearance is the middle of the open water instead. Worked out once per world.
    """
    anchors = tuple(sea.anchor for sea in seas)

    def build() -> tuple[np.ndarray, np.ndarray]:
        salt = world.water_type == int(WaterType.SALT)
        blocked = ~salt
        blocked[[0, -1], :] = True
        blocked[:, [0, -1]] = True
        clearance = distance_to(blocked, backend=config.get("compute.backend"), sampling=world.scale.sampling)
        ys, xs = np.indices(salt.shape)
        reach = np.stack([np.hypot((xs - x) * world.km_per_col, (ys - y) * world.km_per_row) for x, y in anchors])
        owner = np.where(salt, np.argmin(reach, axis=0), -1)
        return clearance, owner

    if not anchors:
        return np.zeros(world.water_type.shape, dtype=np.float32), np.full(world.water_type.shape, -1)
    return derived(world, (__name__, "sea_middles", anchors), build, world.water_type)


def _sea_starts(world: World, config: Config, seas: list[GeoFeature], index: int, count: int) -> list[tuple[int, int]]:
    """Return up to ``count`` label start positions for ``seas[index]``, the middle of its water first."""
    clearance, owner = _sea_middles(world, config, seas)
    ys, xs = np.nonzero(owner == index)
    if len(xs) == 0:
        return []
    ax, ay = seas[index].anchor
    order = np.lexsort((xs, ys, np.hypot(xs - ax, ys - ay), -clearance[ys, xs]))[:count]
    text = seas[index].name
    return [(int(xs[i]) - len(text) // 2, int(ys[i])) for i in order]


def _realm_labels(ctx: LayerContext, placer: _Placer, cfg: dict) -> None:
    """Name the realms in capitals near their centres, largest first, in a lightened shade of their colour."""
    world = ctx.world
    kinds = set(cfg["realm_kinds"])
    smallest = float(cfg["realm_min_area_km2"])
    cell_km2 = world.scale.cell_area_km2
    # (owner value, text, colour): the realms; at a past moment fallen realms and predecessors are named too.
    named = [(r.id, r.short, r.color) for r in world.realms if r.short and r.kind in kinds]
    if ctx.moment is not None:
        named += [(fallen_owner(f.id), f.name, f.color) for f in world.fallen_realms if f.name]
        named += [(predecessor_owner(p.id), p.name, p.color) for p in world.predecessors if p.name]
    stored = {r.id: r.area_km2 for r in world.realms}

    def area(owner: int) -> float:
        """Today the realm's stored area; at a past moment what the owner held then."""
        return stored[owner] if ctx.moment is None else float(np.count_nonzero(ctx.owners == owner)) * cell_km2

    big = [(owner, text, color, area(owner)) for owner, text, color in named if area(owner) >= smallest]
    aspect = world.scale.aspect
    for owner, text, color, _area in sorted(big, key=lambda entry: (-entry[3], entry[0])):
        ys, xs = np.nonzero(ctx.owners == owner)
        text = text.upper()
        nearest = np.lexsort((xs, ys, np.hypot(xs - xs.mean(), (ys - ys.mean()) * aspect)))
        starts = [(int(xs[i]) - len(text) // 2, int(ys[i])) for i in nearest[: int(cfg["realm_candidates"])]]
        colour = mix_colors(color, (255, 255, 255), float(cfg["realm_lighten"]))
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
    seas = sorted((f for f in by_kind.get("sea", []) if f.name), key=lambda f: f.id)
    for index, sea in enumerate(seas):
        starts = _sea_starts(world, ctx.config, seas, index, int(cfg["sea_candidates"]))
        placer.place(sea.name, starts, tuple(cfg["sea_fg"]), over_water=True)
    for lake in largest("lake", int(cfg["max_lakes"])):
        if lake.cells:
            placer.place(
                lake.name, _around(lake, lake.name, int(cfg["lake_candidates"]), aspect), tuple(cfg["lake_fg"])
            )
