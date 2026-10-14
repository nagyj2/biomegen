"""Stage 5: geography - landmasses, mountain ranges, peaks, seas, lakes and named rivers.

Ported from the reference generator's ``_regions`` (``docs/reference/worldgen.py``), minus the names (the
naming stage gives every feature its name):

1. **Landmasses.** Every 8-connected component of solid land (land that is not lake; rivers count as land)
   gets a ``landmass_id``, largest first. Components of at least ``min_landmass_km2`` become landmass
   features with a summit.
2. **Ranges.** Connected mountain, peak and volcano relief of at least ``min_range_km2``, with a summit.
   Every distinct summit (of a range or a landmass) is one peak feature.
3. **Lakes.** Hydrology's lakes of at least ``min_named_lake_km2``.
4. **Seas.** Up to ``max_seas`` sea cells farthest from land, at least ``sea_min_offshore_km`` out and
   ``sea_spacing_km`` apart, each with the greatest depth within ``sea_depth_radius_km``.
5. **Rivers.** The ``max_named_rivers`` rivers with the largest catchment at the mouth that are at least
   ``min_river_km`` long; ``into`` is the lake at the mouth, else the nearest sea.

Writes ``landmass_id`` and ``features``. Everything is ordered by size or distance with row-major tie-breaks,
so the result is deterministic without a random stream.
"""

from __future__ import annotations

import numpy as np

from ...config.model import Config
from ...util import geometry as geo
from ...world.entities import GeoFeature
from ...world.tile import Biome, Relief, WaterType
from ...world.world import World

Cell = tuple[int, int]


def _components(mask: np.ndarray, backend: str) -> list[np.ndarray]:
    """Return the 8-connected components of ``mask`` as flat-index arrays, largest first.

    Ties in size go to the component whose first cell (row-major) comes first, so the order does not
    depend on the labelling backend.
    """
    labels, count = geo.label_by_value(mask.astype(np.uint8), connectivity=8, backend=backend)
    flat = labels.ravel()
    inside = np.flatnonzero(mask.ravel())
    groups: dict[int, list[int]] = {}
    for index in inside.tolist():
        groups.setdefault(int(flat[index]), []).append(index)
    cells = [np.array(g, dtype=np.int64) for g in groups.values()]
    cells.sort(key=lambda c: (-c.size, int(c[0])))
    return cells


def _xy(world: World, flat: np.ndarray) -> list[Cell]:
    """Return ``(x, y)`` tuples for flat indices."""
    return [(int(i) % world.width, int(i) // world.width) for i in flat.tolist()]


def _summit(world: World, flat: np.ndarray) -> int:
    """Return the flat index of the highest cell (first in row-major order on ties)."""
    heights = world.elevation_m.ravel()[flat]
    return int(flat[int(np.argmax(heights))])


class _Builder:
    """Collects features and deduplicates peaks by summit cell."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.features: list[GeoFeature] = []
        self._peak_at: dict[int, int] = {}

    def add(self, kind: str, anchor: Cell, **fields: object) -> GeoFeature:
        feature = GeoFeature(id=len(self.features), kind=kind, anchor=anchor, **fields)  # type: ignore[arg-type]
        self.features.append(feature)
        return feature

    def peak(self, flat_index: int) -> int:
        """Return the peak feature id for a summit cell, creating it on first use."""
        if flat_index not in self._peak_at:
            x, y = flat_index % self.world.width, flat_index // self.world.width
            peak = self.add("peak", (x, y), elevation_m=float(self.world.elevation_m[y, x]))
            self._peak_at[flat_index] = peak.id
        return self._peak_at[flat_index]


def _landmasses(world: World, config: Config, build: _Builder, solid: np.ndarray, backend: str) -> None:
    cell_km2 = world.scale.cell_area_km2
    min_cells = float(config.get("geography.min_landmass_km2")) / cell_km2
    landmass_id = np.full(world.width * world.height, -1, dtype=np.int32)
    for rank, flat in enumerate(_components(solid, backend)):
        landmass_id[flat] = rank
        if flat.size >= min_cells:
            top = _summit(world, flat)
            x, y = top % world.width, top // world.width
            build.add(
                "landmass",
                (x, y),
                ref=rank,
                cells=_xy(world, flat),
                area_km2=flat.size * cell_km2,
                elevation_m=float(world.elevation_m[y, x]),
                summit=build.peak(top),
            )
    world.landmass_id = landmass_id.reshape(world.height, world.width)


def _ranges(world: World, config: Config, build: _Builder, solid: np.ndarray, backend: str) -> None:
    cell_km2 = world.scale.cell_area_km2
    min_cells = float(config.get("geography.min_range_km2")) / cell_km2
    high = solid & np.isin(world.relief, [int(Relief.MOUNTAIN), int(Relief.PEAK), int(Relief.VOLCANO)])
    for flat in _components(high, backend):
        if flat.size < min_cells:
            break  # components come largest first
        top = _summit(world, flat)
        x, y = top % world.width, top // world.width
        build.add(
            "range",
            (x, y),
            cells=_xy(world, flat),
            area_km2=flat.size * cell_km2,
            elevation_m=float(world.elevation_m[y, x]),
            summit=build.peak(top),
        )


def _lakes(world: World, config: Config, build: _Builder) -> dict[Cell, int]:
    """Add lake features; return a map from every named-lake cell to its feature id."""
    min_area = float(config.get("geography.min_named_lake_km2"))
    lake_at: dict[Cell, int] = {}
    for lake in sorted(world.lakes, key=lambda lk: (-lk.area, lk.id)):
        if lake.area_km2 < min_area:
            continue
        anchor = min(lake.tiles, key=lambda c: (c[1], c[0]))
        feature = build.add("lake", anchor, ref=lake.id, cells=list(lake.tiles), area_km2=lake.area_km2)
        for cell in lake.tiles:
            lake_at[cell] = feature.id
    return lake_at


def _seas(world: World, config: Config, build: _Builder, land: np.ndarray) -> list[GeoFeature]:
    g = config.section("geography")
    backend = config.get("compute.backend")
    sampling = world.scale.sampling
    sea = world.water_type == int(WaterType.SALT)
    offshore = geo.distance_to(land, backend=backend, sampling=sampling)
    eligible = sea & (offshore >= float(g.get("sea_min_offshore_km")))
    flat = np.flatnonzero(eligible.ravel())
    # Farthest from land first; the stable sort keeps row-major order among equal distances.
    order = flat[np.argsort(-offshore.ravel()[flat], kind="stable")]
    spacing = float(g.get("sea_spacing_km"))
    radius = float(g.get("sea_depth_radius_km"))
    ys, xs = np.indices((world.height, world.width))
    seas: list[GeoFeature] = []
    for index in order.tolist():
        if len(seas) >= int(g.get("max_seas")):
            break
        x, y = index % world.width, index // world.width
        if any(world.scale.distance_km(x, y, *s.anchor) <= spacing for s in seas):
            continue
        near = sea & (np.hypot((xs - x) * world.km_per_col, (ys - y) * world.km_per_row) <= radius)
        seas.append(build.add("sea", (x, y), elevation_m=float(world.elevation_m[near].min())))
    return seas


def _rivers(world: World, config: Config, build: _Builder, lake_at: dict[Cell, int], seas: list[GeoFeature]) -> None:
    g = config.section("geography")
    candidates = sorted(
        world.rivers,
        key=lambda r: (-float(world.flow_accum[r.path[-1][1], r.path[-1][0]]), r.id),
    )
    named = 0
    for river in candidates:
        if named >= int(g.get("max_named_rivers")):
            break
        if river.length_km < float(g.get("min_river_km")):
            continue
        end = river.mouth if river.mouth is not None else river.path[-1]
        into = lake_at.get(end, -1)
        if into < 0 and seas:
            into = min(seas, key=lambda s: (world.scale.distance_km(end[0], end[1], *s.anchor), s.id)).id
        build.add("river", end, ref=river.id, length_km=river.length_km, into=into)
        named += 1


def run(world: World, config: Config, seed: int) -> None:
    """Fill ``landmass_id`` and ``features`` in place (``seed`` is unused: the stage draws nothing)."""
    backend = str(config.get("compute.backend"))
    land = world.water_type != int(WaterType.SALT)
    solid = land & (world.biome != int(Biome.LAKE)) & ~_lake_cells(world)
    build = _Builder(world)
    _landmasses(world, config, build, solid, backend)
    _ranges(world, config, build, solid, backend)
    lake_at = _lakes(world, config, build)
    seas = _seas(world, config, build, land)
    _rivers(world, config, build, lake_at, seas)
    world.features = build.features


def _lake_cells(world: World) -> np.ndarray:
    """Return every hydrology lake cell (frozen lakes included, whose biome is sea ice)."""
    mask = np.zeros((world.height, world.width), dtype=bool)
    for lake in world.lakes:
        for x, y in lake.tiles:
            mask[y, x] = True
    return mask
