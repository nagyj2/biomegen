"""Tests for settlement plans: streets, lots, walls, roofs and gates, on flat test worlds."""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sites import clear_cache, site_plan
from biomegen.world.tile import Biome, Cell, WaterType
from tests.sites.conftest import HOUSE_ROOF, add_poi, flat_world, roofs

VOID, FLOOR, WALL, DOOR, PATH = (int(c) for c in (Cell.VOID, Cell.FLOOR, Cell.WALL, Cell.DOOR, Cell.PATH))
STONE, TREE, BUSH = (int(c) for c in (Cell.STONE, Cell.TREE, Cell.BUSH))


def _plan(config: Config, kind: str, world=None, pop: int = 2000):
    world = world or flat_world(16, 12)
    poi = add_poi(world, kind, 8, 6, pop=pop)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    return plan


def test_a_village_has_a_plaza_and_streets(config: Config) -> None:
    plan = _plan(config, "village", pop=500)
    assert int((plan.cells == PATH).sum()) > 30


def test_a_village_has_buildings(config: Config) -> None:
    plan = _plan(config, "village", pop=500)
    assert DOOR in plan.cells and WALL in plan.cells


def test_the_streets_are_one_connected_network(config: Config) -> None:
    plan = _plan(config, "town")
    _labels, count = ndimage.label(np.isin(plan.cells, (PATH, int(Cell.BRIDGE))))
    assert count == 1


def test_a_vertical_street_is_as_thick_as_a_horizontal_one(config: Config) -> None:
    # The axis through the plaza runs up and down: it is two columns wide, one row wide where it runs across.
    plan = _plan(config, "town")
    path = plan.cells == PATH
    row = path[plan.cells.shape[0] // 2]
    column = path[:, plan.cells.shape[1] // 2 - 1 : plan.cells.shape[1] // 2 + 2]
    assert row.sum() > 10 and column.any(axis=0).sum() >= 2


def test_every_building_is_under_a_roof_seen_from_outside(config: Config) -> None:
    # Wherever the inside has a wall of a building (not the city wall), the outside is a roof or the stone wall.
    plan = _plan(config, "town")
    # The one exception is a front door, which shows as the street it opens onto.
    interior = np.isin(plan.cells, (FLOOR, int(Cell.TABLE), int(Cell.BED)))
    assert roofs(plan.outside[interior]).all()


def test_streets_are_the_same_inside_and_outside(config: Config) -> None:
    plan = _plan(config, "town")
    # Front doors aside (the street shows over the door gap from outside), the two views agree on the streets.
    doors = plan.cells == DOOR
    assert np.array_equal((plan.cells == PATH) & ~doors, (plan.outside == PATH) & ~doors)


def test_a_capital_is_walled_with_stone_seen_from_outside(config: Config) -> None:
    plan = _plan(config, "capital", pop=80000)
    assert STONE in plan.outside and WALL in plan.cells


def test_a_village_has_no_wall_round_it(config: Config) -> None:
    plan = _plan(config, "village", pop=500)
    assert STONE not in plan.outside


def test_a_walled_settlement_has_a_gate_where_a_street_crosses_the_wall(config: Config) -> None:
    # A road arrives from the east: the wall is broken there by a gate (a door cell in the wall line).
    world = flat_world(16, 12)
    world.road[6, 8:14] = 1
    plan = _plan(config, "capital", world, pop=80000)
    east = plan.cells[:, -12:]
    assert (east == DOOR).any() and (east == WALL).any()


def test_a_road_gate_is_joined_to_the_plaza_by_a_street(config: Config) -> None:
    world = flat_world(16, 12)
    world.road[6, 9:14] = 1
    plan = _plan(config, "town", world)
    row = plan.cells[plan.cells.shape[0] // 2]
    assert (row[-8:] == PATH).any()


def test_trees_grow_on_free_ground(config: Config) -> None:
    plan = _plan(config, "town")
    assert int(np.isin(plan.cells, (TREE, BUSH)).sum()) > 0


def test_trees_keep_off_the_streets_and_buildings(config: Config) -> None:
    plan = _plan(config, "town")
    near = ndimage.binary_dilation(np.isin(plan.cells, (PATH, FLOOR, WALL, DOOR)), iterations=1)
    trees = np.isin(plan.cells, (TREE, BUSH))
    assert not (trees & near & ~np.isin(plan.cells, (TREE, BUSH))).any() and trees.any()


def test_a_settlement_beside_the_sea_builds_only_on_land(config: Config) -> None:
    world = flat_world(16, 12)
    world.biome[:, :8] = int(Biome.DEEP)
    world.water_type[:, :8] = int(WaterType.SALT)
    plan = _plan(config, "town", world)
    sea = plan.cells[:, : plan.cells.shape[1] // 4]
    assert not np.isin(sea, (FLOOR, WALL, DOOR, TREE)).any()


def test_bigger_tiers_have_bigger_sites(config: Config) -> None:
    sizes = [
        _plan(config, kind, pop=hi).cells.size for kind, hi in (("village", 1000), ("town", 5000), ("city", 20000))
    ]
    assert sizes == sorted(sizes)


def test_a_capital_is_not_a_rectangle(config: Config) -> None:
    # The wall follows a wobbling outline: it leaves much of its bounding box empty.
    plan = _plan(config, "capital", pop=80000)
    ys, xs = np.nonzero(plan.outside != VOID)
    box = (ys.max() - ys.min() + 1) * (xs.max() - xs.min() + 1)
    assert int((plan.outside != VOID).sum()) < 0.8 * box


def test_the_wall_is_not_a_rectangle_of_the_extent_edge(config: Config) -> None:
    # A wall hugging a rectangle would have every cell on the outer rows and columns of its own bounding box.
    plan = _plan(config, "capital", pop=80000)
    ys, xs = np.nonzero(plan.cells == WALL)
    inner = (ys > ys.min()) & (ys < ys.max()) & (xs > xs.min()) & (xs < xs.max())
    assert int(inner.sum()) > len(ys) // 4


def test_a_town_has_streets_on_many_rows(config: Config) -> None:
    # A grid of axes would put its streets on a handful of rows; a grown network spreads over the plan.
    plan = _plan(config, "town")
    assert int((plan.cells == PATH).any(axis=1).sum()) >= 8


def test_two_towns_of_different_seeds_have_different_outlines(config: Config) -> None:
    world = flat_world(16, 12)
    plans = [site_plan(add_poi(world, "town", 8, 6, pop=2000, interior_seed=seed), 0, config, world) for seed in (3, 4)]
    assert plans[0] is not None and plans[1] is not None and not np.array_equal(plans[0].outside, plans[1].outside)


def test_the_streets_still_reach_every_building_door(config: Config) -> None:
    # Each door on a building's outside wall has street (or the road) directly outside: nothing is stranded.
    plan = _plan(config, "town")
    labels, _count = ndimage.label(np.isin(plan.cells, (PATH, int(Cell.BRIDGE))))
    doors = np.argwhere(plan.cells == DOOR)
    reached = 0
    for y, x in doors.tolist():
        around = [(y + dy, x + dx) for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        reached += any(
            0 <= cy < plan.cells.shape[0] and 0 <= cx < plan.cells.shape[1] and labels[cy, cx] > 0 for cy, cx in around
        )
    assert doors.size and reached >= len(doors) // 2


def _floors(config: Config, kind: str, count: int, pop: int):
    world = flat_world(16, 12)
    poi = add_poi(world, kind, 8, 6, pop=pop, floor_count=count)
    plans = [site_plan(poi, floor, config, world) for floor in range(count)]
    assert all(plan is not None for plan in plans)
    return plans


def test_a_tall_settlement_has_stairs_up_on_the_ground_floor(config: Config) -> None:
    plans = _floors(config, "city", 3, 12000)
    assert int(Cell.STAIRS_UP) in plans[0].cells


def test_the_upper_floor_has_stairs_down_and_keeps_the_streets(config: Config) -> None:
    plans = _floors(config, "city", 3, 12000)
    assert int(Cell.STAIRS_DOWN) in plans[1].cells and PATH in plans[1].cells


def test_the_stairs_of_one_floor_meet_the_floor_above(config: Config) -> None:
    # Each staircase up on floor 0 stands where the stairs down are on floor 1.
    plans = _floors(config, "city", 3, 12000)
    up = set(zip(*np.nonzero(plans[0].cells == int(Cell.STAIRS_UP)), strict=True))
    down = set(zip(*np.nonzero(plans[1].cells == int(Cell.STAIRS_DOWN)), strict=True))
    assert down and down <= up


def test_an_upper_floor_keeps_the_ground_outside_the_buildings(config: Config) -> None:
    # Streets, trees and the wall are as they are on the ground floor: only the buildings change.
    plans = _floors(config, "city", 3, 12000)
    outside = ~roofs(plans[0].outside)
    assert np.array_equal(plans[1].cells[outside], plans[0].cells[outside])


def test_an_upper_storey_stands_inside_the_ground_footprint(config: Config) -> None:
    # Every cell that differs from the ground floor lies under a roof seen from outside.
    plans = _floors(config, "city", 3, 12000)
    changed = plans[1].cells != plans[0].cells
    assert changed.any() and roofs(plans[0].outside[changed]).all()


def test_a_single_floor_settlement_has_no_stairs(config: Config) -> None:
    plans = _floors(config, "village", 1, 500)
    assert int(Cell.STAIRS_UP) not in plans[0].cells


def test_the_ground_floor_is_the_same_whichever_floor_is_asked_first(config: Config) -> None:
    # A floor rebuilds the same ground plan: asking for floor 1 first does not change floor 0.
    world = flat_world(16, 12)
    poi = add_poi(world, "city", 8, 6, pop=12000, floor_count=3)
    first = site_plan(poi, 0, config, world)
    clear_cache()
    site_plan(poi, 1, config, world)
    clear_cache()
    again = site_plan(poi, 0, config, world)
    assert first is not None and again is not None and np.array_equal(first.cells, again.cells)


# --- upper floors: roofs ---------------------------------------------------------------------


def test_a_building_without_a_storey_this_high_shows_its_roof(config: Config) -> None:
    # Every ground-floor footprint is covered at an upper floor: by its storey or, where it ends below, by its roof.
    plans = _floors(config, "city", 3, 12000)
    footprint = roofs(plans[0].outside)
    assert footprint.any() and (plans[2].cells[footprint] != VOID).all()


def test_an_upper_floor_has_roofs_over_the_shorter_buildings(config: Config) -> None:
    plans = _floors(config, "city", 3, 12000)
    assert roofs(plans[2].cells).any() and roofs(plans[1].cells).sum() < roofs(plans[2].cells).sum()


def test_the_building_that_reaches_the_top_floor_has_no_roof_there(config: Config) -> None:
    # The tallest building is roofed on no floor below its top: at the top floor some storey cells are not roof.
    plans = _floors(config, "city", 3, 12000)
    assert FLOOR in plans[2].cells


def test_the_ground_floor_has_no_roofs_inside(config: Config) -> None:
    assert not roofs(_floors(config, "city", 3, 12000)[0].cells).any()


def _coast(config: Config, tags: tuple[str, ...], water_from: int = 6):
    """A town at (5, 6) with open sea from column ``water_from`` on; returns the world and the plan."""
    world = flat_world(16, 12)
    world.biome[:, water_from:] = int(Biome.DEEP)
    world.water_type[:, water_from:] = int(WaterType.SALT)
    poi = add_poi(world, "town", 5, 6, pop=2000, tags=tags)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    return world, plan


def _riverside(config: Config, tags: tuple[str, ...], column: int = 7):
    """A town at (6, 6) with a one-tile river down column ``column``."""
    world = flat_world(16, 12)
    world.water_type[:, column] = int(WaterType.FRESH)
    poi = add_poi(world, "town", 6, 6, pop=2000, tags=tags)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    return world, plan


def test_a_port_builds_a_pier_into_open_water(config: Config) -> None:
    _, plan = _coast(config, ("port",))
    assert int(Cell.BRIDGE) in plan.cells


def test_a_town_without_the_port_tag_builds_no_pier(config: Config) -> None:
    _, plan = _coast(config, ())
    assert int(Cell.BRIDGE) not in plan.cells


def test_a_port_with_no_open_water_in_its_extent_builds_no_pier(config: Config) -> None:
    _, plan = _coast(config, ("port",), water_from=12)
    assert int(Cell.BRIDGE) not in plan.cells


def test_a_pier_stands_over_the_water_and_starts_on_the_shore(config: Config) -> None:
    from biomegen.sites import read_patch, site_geometry

    world, plan = _coast(config, ("port",))
    patch = read_patch(world.pois[0], site_geometry(world.pois[0], config), world, config)
    deck = plan.cells == int(Cell.BRIDGE)
    landing = np.argwhere(deck & ~patch.still)
    assert (deck & patch.still).any() and len(landing) <= 1 + (deck & ~patch.still).sum()


def test_a_pier_is_joined_to_the_plaza_by_a_street(config: Config) -> None:
    # Walking the path and deck cells from the pier reaches every street cell: the harbour is not cut off.
    _, plan = _coast(config, ("port",))
    walkable = np.isin(plan.cells, [PATH, int(Cell.BRIDGE)])
    labels, _ = ndimage.label(walkable)
    pier = labels[plan.cells == int(Cell.BRIDGE)]
    streets = labels[plan.cells == PATH]
    assert set(pier.tolist()) <= set(streets.tolist())


def test_a_port_moors_boats_beside_its_pier(config: Config) -> None:
    _, plan = _coast(config, ("port",))
    assert int(Cell.HULL) in plan.cells


def test_moored_boats_lie_on_open_water(config: Config) -> None:
    from biomegen.sites import read_patch, site_geometry

    world, plan = _coast(config, ("port",))
    patch = read_patch(world.pois[0], site_geometry(world.pois[0], config), world, config)
    boat = np.isin(plan.cells, [int(Cell.HULL), int(Cell.CARGO)])
    assert boat.any() and patch.still[boat].all()


WHEEL = int(Cell.WHEEL)
AXLES = [int(Cell.AXLE_H), int(Cell.AXLE_V)]


def _wheel_parts(config: Config):
    world, plan = _riverside(config, ("river",))
    from biomegen.sites import read_patch, site_geometry

    patch = read_patch(world.pois[0], site_geometry(world.pois[0], config), world, config)
    return plan, patch


def test_a_river_settlement_builds_a_wheel_of_many_cells_in_the_river(config: Config) -> None:
    plan, patch = _wheel_parts(config)
    wheel = plan.cells == WHEEL
    assert wheel.sum() >= 8 and patch.river[wheel].all()


def test_the_axle_ends_at_the_hub_in_the_middle_of_the_wheel(config: Config) -> None:
    # Along the axle's own direction its far end lies inside the wheel's span, not short of it and not past it.
    plan, _ = _wheel_parts(config)
    wheel = np.argwhere(plan.cells == WHEEL)
    axle = np.argwhere(np.isin(plan.cells, AXLES))
    axis = 1 if (plan.cells == int(Cell.AXLE_H)).any() else 0
    along = axle[:, axis]
    far = (
        along.max()
        if abs(along.max() - wheel[:, axis].mean()) < abs(along.min() - wheel[:, axis].mean())
        else along.min()
    )
    assert wheel[:, axis].min() < far < wheel[:, axis].max()


def test_the_wheel_stands_a_cell_out_in_the_water(config: Config) -> None:
    # Every neighbour of a wheel cell is river: it is not on the bank.
    plan, patch = _wheel_parts(config)
    wheel = plan.cells == WHEEL
    near = ndimage.binary_dilation(wheel, structure=np.ones((3, 3), bool))
    assert patch.river[near].all()


def test_an_axle_joins_the_wheel_to_a_wall_of_the_mill(config: Config) -> None:
    # The axle and the wheel are one piece, and the axle's far end touches a wall cell of a building.
    plan, _ = _wheel_parts(config)
    parts = np.isin(plan.cells, AXLES + [WHEEL])
    labels, _ = ndimage.label(parts)
    wheel_label = labels[plan.cells == WHEEL][0]
    piece = labels == wheel_label
    axle = piece & np.isin(plan.cells, AXLES)
    touching = ndimage.binary_dilation(axle, structure=ndimage.generate_binary_structure(2, 1)) & (plan.cells == WALL)
    assert axle.any() and touching.any() and set(labels[plan.cells == WHEEL].tolist()) == {int(wheel_label)}


def test_the_axle_runs_straight(config: Config) -> None:
    # An axle is one row (east-west) or one column (north-south) of cells, never both kinds.
    plan, _ = _wheel_parts(config)
    horizontal, vertical = plan.cells == int(Cell.AXLE_H), plan.cells == int(Cell.AXLE_V)
    assert horizontal.any() != vertical.any()
    cells = horizontal if horizontal.any() else vertical
    ys, xs = np.nonzero(cells)
    assert (len(set(ys.tolist())) == 1) if horizontal.any() else (len(set(xs.tolist())) == 1)


def test_a_settlement_without_the_river_tag_has_no_wheel(config: Config) -> None:
    _, plan = _riverside(config, ())
    assert WHEEL not in plan.cells and not np.isin(plan.cells, AXLES).any()


def test_no_wheel_without_a_river_in_the_extent(config: Config) -> None:
    _, plan = _riverside(config, ("river",), column=10)
    assert WHEEL not in plan.cells


def test_the_mill_door_opens_onto_a_street(config: Config) -> None:
    _, plan = _riverside(config, ("river",))
    wheel = np.argwhere(np.isin(plan.cells, AXLES))[0]
    doors = np.argwhere(plan.cells[max(0, wheel[0] - 8) : wheel[0] + 9, max(0, wheel[1] - 16) : wheel[1] + 17] == DOOR)
    assert len(doors) > 0
    padded = np.pad(plan.cells == PATH, 1)
    window_y, window_x = max(0, wheel[0] - 8), max(0, wheel[1] - 16)
    assert any(
        padded[window_y + y + 1 + dy, window_x + x + 1 + dx]
        for y, x in doors.tolist()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))
    )


def test_tags_change_the_plan_even_for_one_poi_and_seed(config: Config) -> None:
    # The plan cache is keyed on the tags, so tagging a POI does not return the plan cached for it untagged.
    world = flat_world(16, 12)
    world.biome[:, 6:] = int(Biome.DEEP)
    world.water_type[:, 6:] = int(WaterType.SALT)
    poi = add_poi(world, "town", 5, 6, pop=2000)
    plain = site_plan(poi, 0, config, world)
    poi.tags = ("port",)
    ported = site_plan(poi, 0, config, world)
    assert plain is not None and ported is not None and not np.array_equal(plain.cells, ported.cells)


def test_harbour_and_mill_are_deterministic(config: Config) -> None:
    _, first = _coast(config, ("port",))
    clear_cache()
    _, second = _coast(config, ("port",))
    assert np.array_equal(first.cells, second.cells)


# --- streets that meet the world road -------------------------------------------------------------------------------


def _strip(rows: int = 9, cols: int = 30) -> tuple[np.ndarray, np.ndarray]:
    return np.zeros((rows, cols), dtype=np.uint8), np.ones((rows, cols), dtype=bool)


def test_a_one_row_sliver_between_two_streets_is_paved() -> None:
    from biomegen.sites.settlement import _close_slivers

    grid, dry = _strip()
    grid[2, :], grid[4, :] = PATH, PATH
    _close_slivers(grid, dry)
    assert (grid[3, :] == PATH).all()


def test_a_one_column_sliver_between_two_streets_is_paved() -> None:
    from biomegen.sites.settlement import _close_slivers

    grid, dry = _strip()
    grid[:, 5], grid[:, 7] = PATH, PATH
    _close_slivers(grid, dry)
    assert (grid[:, 6] == PATH).all()


def test_a_two_row_strip_between_streets_is_not_paved() -> None:
    from biomegen.sites.settlement import _close_slivers

    grid, dry = _strip()
    grid[2, :], grid[5, :] = PATH, PATH
    _close_slivers(grid, dry)
    assert (grid[3:5, :] == VOID).all()


def test_the_inside_of_a_street_corner_is_left_alone() -> None:
    from biomegen.sites.settlement import _close_slivers

    grid, dry = _strip()
    grid[2, 2:10], grid[2:8, 2] = PATH, PATH
    _close_slivers(grid, dry)
    assert grid[3, 3] == VOID


def test_slivers_are_not_paved_over_water_or_buildings() -> None:
    from biomegen.sites.settlement import _close_slivers

    grid, dry = _strip()
    grid[2, :], grid[4, :] = PATH, PATH
    dry[3, 4] = False
    grid[3, 8] = WALL
    _close_slivers(grid, dry)
    assert grid[3, 4] == VOID and grid[3, 8] == WALL


def test_a_street_running_beside_the_road_is_joined_to_it() -> None:
    from biomegen.sites.settlement import _join_roads

    grid, dry = _strip(rows=12)
    road = np.zeros(grid.shape, dtype=bool)
    road[2, :] = True
    grid[road] = PATH  # the road is laid into the grid as street
    grid[5, 4:20] = PATH  # a lane three rows away
    _join_roads(grid, dry, road, aspect=2.0, reach=3.0)
    assert (grid[3:5, 4:20] == PATH).all()


def test_a_street_far_from_the_road_is_left_alone() -> None:
    from biomegen.sites.settlement import _join_roads

    grid, dry = _strip(rows=12)
    road = np.zeros(grid.shape, dtype=bool)
    road[2, :] = True
    grid[road] = PATH
    grid[8, 4:20] = PATH
    _join_roads(grid, dry, road, aspect=2.0, reach=3.0)
    assert (grid[3:8, :] == VOID).all()


def test_a_street_already_touching_the_road_adds_nothing() -> None:
    from biomegen.sites.settlement import _join_roads

    grid, dry = _strip(rows=12)
    road = np.zeros(grid.shape, dtype=bool)
    road[2, :] = True
    grid[road] = PATH
    grid[3, 4:20] = PATH
    before = grid.copy()
    _join_roads(grid, dry, road, aspect=2.0, reach=3.0)
    assert np.array_equal(grid, before)


def test_a_join_does_not_pave_water_or_buildings() -> None:
    from biomegen.sites.settlement import _join_roads

    grid, dry = _strip(rows=12)
    road = np.zeros(grid.shape, dtype=bool)
    road[2, :] = True
    grid[road] = PATH
    grid[5, 4:20] = PATH
    dry[3, 10] = False
    grid[4, 12] = WALL
    _join_roads(grid, dry, road, aspect=2.0, reach=3.0)
    assert grid[3, 10] == VOID and grid[4, 12] == WALL


def test_joining_can_be_switched_off_with_a_zero_reach() -> None:
    from biomegen.sites.settlement import _join_roads

    grid, dry = _strip(rows=12)
    road = np.zeros(grid.shape, dtype=bool)
    road[2, :] = True
    grid[road] = PATH
    grid[5, 4:20] = PATH
    _join_roads(grid, dry, road, aspect=2.0, reach=0.0)
    assert (grid[3:5, :] == VOID).all()


def test_a_settlement_on_a_road_has_less_bare_ground_beside_its_streets_with_joining(config: Config) -> None:
    # Bare cells that lie close to the road and touch a street that is not the road are the strips the ground shows
    # through; joining the streets to the road leaves fewer of them.
    import copy

    from scipy import ndimage as nd

    from biomegen.sites import read_patch, site_geometry

    def bare(cfg: Config) -> int:
        total = 0
        for seed in range(6):
            clear_cache()
            world = flat_world(16, 12)
            world.road[6, :] = 1
            poi = add_poi(world, "city", 8, 6, pop=12000, floor_count=1, interior_seed=100 + seed)
            plan = site_plan(poi, 0, cfg, world)
            assert plan is not None
            patch = read_patch(poi, site_geometry(poi, cfg), world, cfg)
            road = patch.road & patch.dry
            street = (plan.cells == PATH) & ~road
            near = nd.distance_transform_edt(~road, sampling=(1.0, 1.0 / 2.0)) <= 3.0
            void = (plan.cells == VOID) & patch.dry & ~road
            total += int((void & near & nd.binary_dilation(street, structure=np.ones((3, 3), bool))).sum())
        return total

    off = copy.deepcopy(config)
    off.data["sites"]["settlement"]["road_join_rows"] = 0.0
    assert bare(config) < bare(off)


def test_a_hamlet_builds_at_least_one_house(config: Config) -> None:
    # The hamlet row is a settlement layout smaller than a village; its plan still has a building.
    world = flat_world(14, 10)
    plan = site_plan(add_poi(world, "hamlet", 7, 5, civilized=True, pop=40), 0, config, world)
    assert plan is not None and bool(roofs(plan.outside).any())


# --- the housing kind -------------------------------------------------------------------------------------------------


def test_a_settlement_draws_no_plain_roof_only_its_kinds(config: Config) -> None:
    # Every building seen from outside is a roof of its kind: the plain ROOF cell (towers, old ruins) never appears.
    plan = _plan(config, "town")
    assert int(Cell.ROOF) not in plan.outside and HOUSE_ROOF in plan.outside


def test_an_upper_floor_shows_the_kind_roof_not_the_plain_one(config: Config) -> None:
    plans = _floors(config, "city", 3, 12000)
    assert int(Cell.ROOF) not in plans[2].cells and HOUSE_ROOF in plans[2].cells


def test_a_house_row_sets_the_height_of_a_settlement_lot(config: Config) -> None:
    # The house kind's `rows` is the lot height range: no roof is taller than its tallest allowed house.
    tall = _plan(config, "city", pop=12000)
    short_config = load_config(None)
    short_config.data["sites"]["size_jitter"] = 0.0
    short_config.data["sites"]["pop_scale"] = [1.0, 1.0]
    short_config.data["tables"]["buildings"]["house"]["rows"] = [5, 5]

    def tallest(plan) -> int:
        labels, _count = ndimage.label(plan.outside == HOUSE_ROOF)
        return max(int(box[0].stop - box[0].start) for box in ndimage.find_objects(labels))

    assert tallest(_plan(short_config, "city", pop=12000)) <= 5 < tallest(tall)


def test_a_settlement_plan_is_deterministic(config: Config) -> None:
    first = _plan(config, "town")
    clear_cache()
    second = _plan(config, "town")
    assert np.array_equal(first.cells, second.cells) and np.array_equal(first.outside, second.outside)


# --- the roof level -----------------------------------------------------------------------------------------------


def test_a_settlement_has_a_roof_level_above_its_top_storey(config: Config) -> None:
    from biomegen.sites import site_floor_range, site_roof_floor

    world = flat_world(16, 12)
    poi = add_poi(world, "city", 8, 6, pop=12000, floor_count=3)
    assert (site_floor_range(poi, config), site_roof_floor(poi, config)) == ((0, 3), 3)


def test_a_homestead_and_a_dungeon_have_a_roof_level_but_a_camp_has_none(config: Config) -> None:
    from biomegen.sites import site_roof_floor

    world = flat_world(16, 12)
    assert site_roof_floor(add_poi(world, "homestead", 7, 5), config) == 1
    assert site_roof_floor(add_poi(world, "dungeon", 3, 3, floor_count=2, lowest_floor=-1), config) == 1
    assert site_roof_floor(add_poi(world, "camp", 5, 5), config) is None


def test_the_roof_level_of_a_dungeon_is_its_surface_view(config: Config) -> None:
    # Above the top floor a dungeon is seen from outside: its roof cells, not the gatehouse rooms.
    world = flat_world(16, 12)
    poi = add_poi(world, "dungeon", 8, 6, floor_count=2, lowest_floor=-1)
    roof, ground = site_plan(poi, 1, config, world), site_plan(poi, 0, config, world)
    assert roof is not None and ground is not None and np.array_equal(roof.cells, ground.outside)


def _ground_and_roofs(config: Config, kind: str, count: int, pop: int):
    """The ground floor and the roof level (one above the top storey) of a settlement with ``count`` storeys."""
    world = flat_world(16, 12)
    poi = add_poi(world, kind, 8, 6, pop=pop, floor_count=count)
    ground, roof = site_plan(poi, 0, config, world), site_plan(poi, count, config, world)
    assert ground is not None and roof is not None and roof.floor == count
    return ground, roof


def test_the_roof_level_shows_every_building_as_its_kind_roof(config: Config) -> None:
    # No building is hidden by a taller neighbour or a storey: the roofs are exactly those seen from outside.
    ground, roof = _ground_and_roofs(config, "city", 3, 12000)
    assert np.array_equal(roofs(roof.cells), roofs(ground.outside))


def test_the_roof_level_keeps_the_kind_of_each_roof(config: Config) -> None:
    ground, roof = _ground_and_roofs(config, "city", 3, 12000)
    assert np.array_equal(roof.cells[roofs(roof.cells)], ground.outside[roofs(ground.outside)])


def test_the_roof_level_has_no_rooms(config: Config) -> None:
    ground, roof = _ground_and_roofs(config, "city", 3, 12000)
    assert not (roof.cells[roofs(ground.outside)] == FLOOR).any()


def test_a_village_roof_level_is_its_outside_roofs(config: Config) -> None:
    ground, roof = _ground_and_roofs(config, "village", 1, 800)
    assert np.array_equal(roofs(roof.cells), roofs(ground.outside))


def test_asking_past_the_roof_level_gives_the_roof_level(config: Config) -> None:
    world = flat_world(16, 12)
    poi = add_poi(world, "town", 8, 6, pop=3000, floor_count=2)
    roof, beyond = site_plan(poi, 2, config, world), site_plan(poi, 9, config, world)
    assert roof is not None and beyond is not None and beyond.floor == 2 and np.array_equal(roof.cells, beyond.cells)


# --- upper storeys are cut back ------------------------------------------------------------------------------------


def _storey_cells(cells: np.ndarray, plan) -> np.ndarray:
    """The cells under a building's roof that hold a storey (not bare, not the roof of a lower storey)."""
    inside = np.zeros(cells.shape, dtype=bool)
    for building in plan.buildings:
        rows, cols = slice(building.y, building.y + building.height), slice(building.x, building.x + building.width)
        inside[rows, cols] |= building.footprint
    return inside & (cells != VOID) & ~roofs(cells)


def test_a_tall_building_loses_part_of_its_floor_plan_above(config: Config) -> None:
    # Some building has a storey on the top floor and, beside it, the roof of the lower storey it was cut back from.
    plans = _floors(config, "city", 3, 12000)
    top = plans[2]
    cut = [
        b
        for b in top.buildings
        if _storey_cells(top.cells, top)[b.y : b.y + b.height, b.x : b.x + b.width].any()
        and (roofs(top.cells[b.y : b.y + b.height, b.x : b.x + b.width]) & b.footprint).any()
    ]
    assert cut


def test_an_upper_storey_never_reaches_beyond_the_one_below(config: Config) -> None:
    plans = _floors(config, "city", 3, 12000)
    below, above = _storey_cells(plans[1].cells, plans[1]), _storey_cells(plans[2].cells, plans[2])
    assert not (above & ~below).any()
