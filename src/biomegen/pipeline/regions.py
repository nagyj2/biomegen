"""Stage 6: region segmentation + per-region colour.

Tiles are grouped into named **regions**: contiguous runs of *similar* biome (not necessarily
identical - e.g. forest/jungle/taiga/swamp count as one "woodland" family, configurable). This is the
standard image-segmentation recipe: relabel each tile by its similarity group, take connected
components, then merge sub-threshold components into their best neighbour so the map is not shattered
into thousands of single-tile specks. The ocean is excluded (region id -1).

Each region is given a deterministic colour = its dominant biome's palette colour perturbed by a
per-region jitter, so adjacent same-biome regions are still distinguishable in SVG/PNG export and in
the curses ``init_color`` attempt. Names and lore are added later by the naming stage.
"""

from __future__ import annotations

import math
from collections import Counter, deque
from typing import Tuple, cast

import numpy as np

from ..config.model import Config
from ..util import geometry as geo
from ..util import rng
from ..world.entities import Region
from ..world.tile import BIOME_NAME, Biome, biome_from_name
from ..world.world import World

_OFFSETS4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _group_lookup(config: Config) -> np.ndarray:
    """Build a lookup array ``biome_int -> group_id`` from the configured similarity groups.

    Biomes that appear in a similarity group share that group's id; any biome not listed gets its own
    unique group, so it only ever merges with its own kind.
    """
    group_of: dict[int, int] = {}
    gid = 0
    for grp in config.get("regions.similarity_groups"):
        for name in grp:
            group_of[int(biome_from_name(name))] = gid
        gid += 1
    for biome in Biome:
        if int(biome) not in group_of:
            group_of[int(biome)] = gid
            gid += 1
    lut = np.zeros(max(int(b) for b in Biome) + 1, dtype=np.int32)
    for bint, g in group_of.items():
        lut[bint] = g
    return lut


def _largest_adjacent(labels: np.ndarray, target: int, ocean_labels: set, sizes: np.ndarray) -> int:
    """Return the non-ocean neighbour label sharing the most border with ``target`` (or -1)."""
    h, w = labels.shape
    ys, xs = np.nonzero(labels == target)
    border: Counter[int] = Counter()
    for x, y in zip(xs.tolist(), ys.tolist(), strict=True):
        for dx, dy in _OFFSETS4:
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                other = int(labels[ny, nx])
                if other != target and other not in ocean_labels:
                    border[other] += 1
    if not border:
        return -1
    # Prefer the longest shared border; break ties toward the larger region for stability.
    return max(border, key=lambda lab: (border[lab], int(sizes[lab])))


def _farthest_point_seeds(tiles_yx: np.ndarray, k: int) -> list[tuple[int, int]]:
    """Pick k spatially separated tiles using farthest-point sampling.

    Starts from the first tile (top-left after sort) and iteratively adds the tile
    that is farthest from all already-chosen seeds. O(n*k) — much better spatial
    separation than evenly-spaced index sampling for irregular blob shapes.
    """
    indices = [0]
    dist_sq = np.full(len(tiles_yx), np.inf)
    for _ in range(k - 1):
        last = tiles_yx[indices[-1]]
        d = np.sum((tiles_yx - last) ** 2, axis=1).astype(float)
        np.minimum(dist_sq, d, out=dist_sq)
        indices.append(int(np.argmax(dist_sq)))
    return [tuple(tiles_yx[i].tolist()) for i in indices]


def _split_large_regions(labels: np.ndarray, ocean_labels: set, max_size: int) -> tuple[np.ndarray, int]:
    """Voronoi-BFS split of any non-ocean region exceeding max_size tiles.

    Seeds are chosen by farthest-point sampling for good spatial separation. Runs
    iteratively until all non-ocean regions are at or below max_size.
    """
    for _pass in range(32):  # cap on iteration count; terminates when nothing changes
        n = int(labels.max()) + 1
        next_label = n
        split_any = False

        for lab in range(n):
            if lab in ocean_labels:
                continue
            ys, xs = np.nonzero(labels == lab)
            size = len(ys)
            if size <= max_size:
                continue

            split_any = True
            k = math.ceil(size / max_size)
            tiles_yx = np.column_stack([ys, xs])  # shape (N, 2)
            # Sort for determinism before farthest-point sampling.
            order = np.lexsort((tiles_yx[:, 1], tiles_yx[:, 0]))
            tiles_yx = tiles_yx[order]
            seeds = _farthest_point_seeds(tiles_yx, k)
            seed_labels = [lab] + list(range(next_label, next_label + k - 1))
            next_label += k - 1

            tile_set = {(int(r[0]), int(r[1])) for r in tiles_yx}
            assigned: dict = {}
            queue: deque = deque()
            for sl, (sy, sx) in zip(seed_labels, seeds, strict=True):
                assigned[(sy, sx)] = sl
                queue.append((sy, sx, sl))

            while queue:
                y, x, lbl = queue.popleft()
                for dy, dx in _OFFSETS4:
                    ny, nx = y + dy, x + dx
                    if (ny, nx) in tile_set and (ny, nx) not in assigned:
                        assigned[(ny, nx)] = lbl
                        queue.append((ny, nx, lbl))

            for (ty, tx), lbl in assigned.items():
                labels[ty, tx] = lbl

        if not split_any:
            break

    return labels, int(labels.max()) + 1


def run(world: World, config: Config, seed: int) -> None:
    """Segment the island into regions, fill ``region_id``, and build Region entities."""
    backend = config.get("compute.backend")
    min_size = int(config.get("regions.min_region_size"))
    jitter = int(config.get("regions.color_jitter"))
    palette = config.get("render.palette")

    # 1. Connected components of equal similarity-group.
    group_grid = _group_lookup(config)[world.biome]
    labels, n = geo.label_by_value(group_grid, connectivity=4, backend=backend)

    ocean = world.biome == int(Biome.OCEAN)
    ocean_labels = set(np.unique(labels[ocean]).tolist()) if ocean.any() else set()

    # 2. Merge sub-threshold non-ocean components into their best neighbour, iterating to stability.
    for _ in range(64):  # generous cap; merges monotonically reduce the small-region count
        sizes = np.bincount(labels.ravel(), minlength=n)
        merged_any = False
        # Process small regions smallest-first so slivers dissolve into substance.
        small = sorted(
            (lab for lab in range(n) if lab not in ocean_labels and 0 < sizes[lab] < min_size),
            key=lambda lab: int(sizes[lab]),
        )
        for lab in small:
            if sizes[lab] == 0:  # already absorbed earlier this pass
                continue
            target = _largest_adjacent(labels, lab, ocean_labels, sizes)
            if target >= 0:
                labels[labels == lab] = target
                sizes[target] += sizes[lab]
                sizes[lab] = 0
                merged_any = True
        if not merged_any:
            break

    # 2b. Split oversized non-ocean regions into approximately max_region_size sub-regions.
    max_size = int(config.get("regions.max_region_size", 0))
    if max_size > 0:
        labels, n = _split_large_regions(labels, ocean_labels, max_size)

    # 3. Renumber the surviving non-ocean components to a contiguous 0..R-1; ocean -> -1.
    region_id = np.full(labels.shape, -1, dtype=np.int32)
    final_ids: dict[int, int] = {}
    world.regions = []
    for lab in sorted(int(v) for v in np.unique(labels)):
        if lab in ocean_labels:
            continue
        mask = labels == lab
        if not mask.any():
            continue
        rid = len(world.regions)
        final_ids[lab] = rid
        region_id[mask] = rid

        ys, xs = np.nonzero(mask)
        # Dominant biome of the region (most frequent tile biome).
        dominant = int(Counter(world.biome[mask].tolist()).most_common(1)[0][0])
        base = palette.get(BIOME_NAME[dominant], [128, 128, 128])
        rgen = rng.derive(seed, "regions", rid)
        color = tuple(int(np.clip(base[i] + rgen.randint(-jitter, jitter), 0, 255)) for i in range(3))
        world.regions.append(
            Region(
                id=rid,
                biome_class=dominant,
                size=int(mask.sum()),
                base_color=cast(Tuple[int, int, int], color),
                bbox=(int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())),
                centroid=(float(xs.mean()), float(ys.mean())),
            )
        )

    world.region_id = region_id  # type: ignore[assignment]

    # 4. Extend coastal land regions into shallow ocean via multi-source BFS (Voronoi).
    #    Each ocean tile within coastal_ocean_depth steps of land is absorbed into whichever
    #    land region reaches it first (nearest-region assignment). Deeper tiles stay at -1.
    coastal_depth = int(config.get("regions.coastal_ocean_depth", 0))
    if coastal_depth > 0 and ocean_labels:
        ocean_mask = world.biome == int(Biome.OCEAN)
        h, w = region_id.shape  # type: ignore[misc]
        land_ys, land_xs = np.nonzero(region_id >= 0)
        queue: deque = deque((int(y), int(x), 0) for y, x in zip(land_ys.tolist(), land_xs.tolist(), strict=True))
        while queue:
            y, x, depth = queue.popleft()
            if depth >= coastal_depth:
                continue
            for dy, dx in _OFFSETS4:
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and ocean_mask[ny, nx] and region_id[ny, nx] == -1:
                    region_id[ny, nx] = region_id[y, x]
                    queue.append((ny, nx, depth + 1))

        world.region_id = region_id  # type: ignore[assignment]
