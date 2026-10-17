"""Tests for the site patch: terrain read through the renderer's sampler, and the gates where roads arrive."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sites.geometry import SiteGeometry, site_geometry
from biomegen.sites.patch import read_patch
from biomegen.world.entities import POI
from biomegen.world.tile import Biome, WaterType
from tests.render.conftest import make_world


@pytest.fixture(scope="module")
def cfg() -> Config:
    config = load_config(None)
    config.data["sites"]["size_jitter"] = 0.0
    return config


def _village(world, config, x: int = 4, y: int = 3) -> tuple[POI, SiteGeometry]:
    poi = POI(kind="village", x=x, y=y, interior_seed=3, pop=500)
    world.pois.append(poi)
    geometry = site_geometry(poi, config)
    assert geometry is not None
    return poi, geometry


def test_dry_land_patch_is_all_dry(cfg: Config) -> None:
    world = make_world(9, 7, Biome.GRASS)
    poi, geometry = _village(world, cfg)
    patch = read_patch(poi, geometry, world, cfg)
    assert patch.dry.all() and not patch.water.any()


def test_patch_is_cropped_to_the_extent_box(cfg: Config) -> None:
    world = make_world(9, 7, Biome.GRASS)
    poi, geometry = _village(world, cfg)
    patch = read_patch(poi, geometry, world, cfg)
    assert (patch.rows, patch.cols) == (geometry.box_rows, geometry.box_cols)


def test_a_lake_beside_the_village_is_water_in_the_patch(cfg: Config) -> None:
    # With the biome warp off the lake edge is straight, so the box's last column is water and its first is dry.
    crisp = load_config(None)
    crisp.data["sites"].update(cfg.data["sites"])
    crisp.data["render"]["blend_strength"] = 0.0
    cfg = crisp
    world = make_world(9, 7, Biome.GRASS)
    world.biome[:, 5:] = int(Biome.LAKE)
    world.water_type[:, 5:] = int(WaterType.FRESH)
    poi, geometry = _village(world, cfg)
    patch = read_patch(poi, geometry, world, cfg)
    assert patch.water[:, -1].all() and patch.dry[:, 0].all()


def test_a_river_tile_is_water_not_dry(cfg: Config) -> None:
    # A river keeps its land biome but is fresh water: the patch must not offer it as dry ground.
    world = make_world(9, 7, Biome.GRASS)
    world.water_type[:, 4] = int(WaterType.FRESH)
    poi, geometry = _village(world, cfg)
    patch = read_patch(poi, geometry, world, cfg)
    assert patch.water[patch.rows // 2, patch.cols // 2]


def test_water_and_dry_never_overlap(cfg: Config) -> None:
    world = make_world(9, 7, Biome.GRASS)
    world.water_type[:, 4] = int(WaterType.FRESH)
    poi, geometry = _village(world, cfg)
    patch = read_patch(poi, geometry, world, cfg)
    assert not (patch.water & patch.dry).any()


def test_a_road_from_the_north_makes_a_gate_on_the_top_edge(cfg: Config) -> None:
    world = make_world(9, 7, Biome.GRASS)
    world.road[0:4, 4] = 1  # the anchor's tile is road too: roads end at a POI
    poi, geometry = _village(world, cfg)
    gates = read_patch(poi, geometry, world, cfg).gates
    assert [(g.dx, g.dy, g.row) for g in gates] == [(0, -1, 0)]


def test_a_road_from_the_east_makes_a_gate_on_the_right_edge(cfg: Config) -> None:
    world = make_world(9, 7, Biome.GRASS)
    world.road[3, 4:9] = 1
    poi, geometry = _village(world, cfg)
    gates = read_patch(poi, geometry, world, cfg).gates
    assert [(g.dx, g.dy, g.col) for g in gates] == [(1, 0, geometry.box_cols - 1)]


def test_roads_inside_the_extent_make_no_gate(cfg: Config) -> None:
    world = make_world(9, 7, Biome.GRASS)
    world.road[3, 4] = 1
    poi, geometry = _village(world, cfg)
    assert read_patch(poi, geometry, world, cfg).gates == ()


def test_no_more_gates_than_max_gates(cfg: Config) -> None:
    world = make_world(11, 9, Biome.GRASS)
    world.road[0, :] = world.road[8, :] = 1
    world.road[:, 0] = world.road[:, 10] = 1
    poi, geometry = _village(world, cfg, 5, 4)
    assert len(read_patch(poi, geometry, world, cfg).gates) <= int(cfg.get("sites.max_gates"))


def test_gate_cells_lie_on_the_box_perimeter(cfg: Config) -> None:
    world = make_world(9, 7, Biome.GRASS)
    world.road[0:4, 4] = 1
    world.road[3, 4:9] = 1
    poi, geometry = _village(world, cfg)
    for gate in read_patch(poi, geometry, world, cfg).gates:
        assert gate.col in (0, geometry.box_cols - 1) or gate.row in (0, geometry.box_rows - 1)


def test_elevation_is_read_from_the_world(cfg: Config) -> None:
    world = make_world(9, 7, Biome.GRASS, elevation_m=250.0)
    poi, geometry = _village(world, cfg)
    assert np.allclose(read_patch(poi, geometry, world, cfg).elevation_m, 250.0)


def test_a_gate_is_where_the_road_link_crosses_the_edge(cfg: Config) -> None:
    # The link from the village's tile (4, 3) to the road tile (5, 3) crosses the extent's east edge at x = 4.625, a
    # little past the middle of the box's height, on the box's last column.
    world = make_world(9, 7, Biome.GRASS)
    world.road[3, 4:6] = 1
    poi, geometry = _village(world, cfg)
    (gate,) = read_patch(poi, geometry, world, cfg).gates
    assert (gate.col, gate.dx, gate.dy) == (geometry.box_cols - 1, 1, 0) and abs(gate.row - geometry.box_rows // 2) <= 1


def test_a_diagonal_road_link_makes_a_gate_on_the_corner_side(cfg: Config) -> None:
    world = make_world(9, 7, Biome.GRASS)
    world.road[2, 5] = world.road[3, 4] = 1  # a link from the anchor up and to the right
    poi, geometry = _village(world, cfg)
    (gate,) = read_patch(poi, geometry, world, cfg).gates
    assert gate.row < geometry.box_rows // 2 and gate.col > geometry.box_cols // 2


def test_road_tiles_not_linked_to_the_anchor_make_no_gate(cfg: Config) -> None:
    # A road tile two away with a gap between it and the anchor is not a link into the site.
    world = make_world(9, 7, Biome.GRASS)
    world.road[3, 6] = 1
    poi, geometry = _village(world, cfg)
    assert read_patch(poi, geometry, world, cfg).gates == ()


def test_a_road_passing_beside_the_site_makes_no_gate(cfg: Config) -> None:
    world = make_world(9, 7, Biome.GRASS)
    world.road[0, :] = 1
    poi, geometry = _village(world, cfg)
    assert read_patch(poi, geometry, world, cfg).gates == ()
