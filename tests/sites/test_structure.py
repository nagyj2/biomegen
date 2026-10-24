"""Tests for tower, ruin and dungeon layouts: tapering floors, aligned stairs, roofs, breaches and rock."""

from __future__ import annotations

import copy

import numpy as np

from biomegen.config.model import Config
from biomegen.sites import site_plan
from biomegen.sites.kinds import roof_cell
from biomegen.world.tile import Cell
from tests.sites.conftest import add_poi, flat_world

VOID, FLOOR, WALL, DOOR = (int(c) for c in (Cell.VOID, Cell.FLOOR, Cell.WALL, Cell.DOOR))
UP, DOWN, STONE, RUBBLE, SOLID = (
    int(c) for c in (Cell.STAIRS_UP, Cell.STAIRS_DOWN, Cell.STONE, Cell.RUBBLE, Cell.SOLID)
)


def _floor_plans(config: Config, kind: str, **fields):
    world = flat_world(14, 10)
    poi = add_poi(world, kind, 7, 5, **fields)
    plans = [
        site_plan(poi, floor, config, world) for floor in range(poi.lowest_floor, poi.lowest_floor + poi.floor_count)
    ]
    assert all(plan is not None for plan in plans)
    return poi, plans


def _footprint(cells: np.ndarray, roof: int) -> int:
    """The cells of the floor's own room: not bare ground, not the ``roof`` of the floors below."""
    ground = [VOID, roof, int(Cell.PATH), int(Cell.TREE), int(Cell.BUSH)]
    return int((~np.isin(cells, ground)).sum())


def test_each_tower_floor_is_smaller_than_the_one_below(config: Config) -> None:
    _poi, plans = _floor_plans(config, "tower", floor_count=3)
    sizes = [_footprint(plan.cells, roof_cell(config, "tower")) for plan in plans]
    assert sizes == sorted(sizes, reverse=True) and sizes[0] > sizes[-1]


def test_tower_stairs_climb_in_the_same_column_on_every_floor(config: Config) -> None:
    # The up stairs of one floor sit where the down stairs of the next one begin.
    _poi, plans = _floor_plans(config, "tower", floor_count=3)
    ups = [set(zip(*np.nonzero(plan.cells == UP), strict=True)) for plan in plans[:-1]]
    downs = [set(zip(*np.nonzero(plan.cells == DOWN), strict=True)) for plan in plans[1:]]
    assert all(up == down and up for up, down in zip(ups, downs, strict=True))


def test_the_top_of_a_tower_has_no_way_further_up(config: Config) -> None:
    _poi, plans = _floor_plans(config, "tower", floor_count=3)
    assert UP not in plans[-1].cells and DOWN in plans[-1].cells


def test_a_tower_is_a_single_room(config: Config) -> None:
    # Every wall cell lies on the outline (touches void); an inner partition would have no void neighbour.
    _poi, plans = _floor_plans(config, "tower", floor_count=2)
    cells = np.pad(plans[0].cells, 1, constant_values=VOID)
    void = cells == VOID
    touches_void = void[:-2, 1:-1] | void[2:, 1:-1] | void[1:-1, :-2] | void[1:-1, 2:]
    walls = plans[0].cells == WALL
    assert walls.any() and touches_void[walls].all()


def test_a_tower_seen_from_outside_is_a_roof(config: Config) -> None:
    _poi, plans = _floor_plans(config, "tower", floor_count=2)
    assert roof_cell(config, "tower") in plans[0].outside


def test_an_upper_tower_floor_is_hidden_from_outside(config: Config) -> None:
    _poi, plans = _floor_plans(config, "tower", floor_count=2)
    assert (plans[1].outside == VOID).all()


def test_a_ruin_has_standing_roofs_and_stone_walls_from_outside(config: Config) -> None:
    _poi, plans = _floor_plans(config, "ruin", floor_count=1)
    outside = plans[0].outside
    assert roof_cell(config, "ruin") in outside and STONE in outside


def test_a_ruin_is_strewn_with_rubble(config: Config) -> None:
    _poi, plans = _floor_plans(config, "ruin", floor_count=1)
    assert RUBBLE in plans[0].cells


def test_a_ruin_has_fewer_walls_than_the_same_building_intact(config: Config) -> None:
    # Raising the erosion to zero must keep every wall a breach would have knocked down.
    world = flat_world(14, 10)
    poi = add_poi(world, "ruin", 7, 5, floor_count=1)
    eroded = site_plan(poi, 0, config, world)
    intact_config = copy.deepcopy(config)
    intact_config.data["tables"]["sites"]["ruin"]["ruin_erosion"] = 0.0
    intact_config.data["sites"]["ruin_erosion"] = 0.0
    intact = site_plan(poi, 0, intact_config, world)
    assert eroded is not None and intact is not None
    assert int((eroded.cells == WALL).sum()) < int((intact.cells == WALL).sum())


def test_a_dungeon_has_rock_below_ground(config: Config) -> None:
    _poi, plans = _floor_plans(config, "dungeon", floor_count=3, lowest_floor=-2)
    assert SOLID in plans[0].cells


def test_the_dungeon_surface_is_a_gatehouse_with_stairs_down(config: Config) -> None:
    _poi, plans = _floor_plans(config, "dungeon", floor_count=3, lowest_floor=-2)
    surface = plans[-1]
    assert DOWN in surface.cells and SOLID not in surface.cells


def test_dungeon_stairs_meet_between_floors(config: Config) -> None:
    # Where one floor goes down the floor below comes up, at the same cell.
    _poi, plans = _floor_plans(config, "dungeon", floor_count=3, lowest_floor=-2)
    for below, above in zip(plans[:-1], plans[1:], strict=True):
        assert set(zip(*np.nonzero(above.cells == DOWN), strict=True)) == set(
            zip(*np.nonzero(below.cells == UP), strict=True)
        )


def test_no_tree_walls_a_ruin_door_in(config: Config) -> None:
    # Trees and bushes grow only where they leave every door of the ruin reachable from the others (40 ruin seeds).
    from scipy import ndimage

    from biomegen.sites import PASSABLE

    passable = np.array(sorted(PASSABLE))
    split = []
    for index in range(40):
        world = flat_world(14, 10)
        poi = add_poi(world, "ruin", 7, 5, floor_count=1, interior_seed=1000 + index)
        plan = site_plan(poi, 0, config, world)
        labels, _ = ndimage.label(np.isin(plan.cells, passable))
        doors = {int(labels[y, x]) for y, x in np.argwhere(plan.cells == DOOR).tolist()}
        if len(doors - {0}) > 1:
            split.append(index)
    assert split == []


def test_an_upper_tower_floor_shows_the_floor_below_as_a_roof(config: Config) -> None:
    # Where the floor below is wider, its outline shows round the smaller floor as a roof.
    _poi, plans = _floor_plans(config, "tower", floor_count=3)
    roof = roof_cell(config, "tower")
    own = ~np.isin(plans[1].cells, [VOID, roof, int(Cell.PATH), int(Cell.TREE), int(Cell.BUSH)])
    ring = (plans[0].outside == roof) & ~own
    assert ring.any() and (plans[1].cells[ring] == roof).all()


def test_the_ground_floor_of_a_tower_has_no_roofs_inside(config: Config) -> None:
    _poi, plans = _floor_plans(config, "tower", floor_count=3)
    assert roof_cell(config, "tower") not in plans[0].cells


# --- ruin erosion by age ----------------------------------------------------------------------------------


def _ruin_walls(config: Config, fell: int | None, year: int = 1200) -> int:
    """The wall cells a ruin that fell in year ``fell`` still has (the same site seed for every age)."""
    world = flat_world(14, 10)
    world.year = year
    poi = add_poi(world, "ruin", 7, 5, fell=fell, interior_seed=3)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    return int((plan.cells == WALL).sum())


def test_a_young_ruin_keeps_more_of_its_walls_than_an_old_one(config: Config) -> None:
    assert _ruin_walls(config, fell=1190) > _ruin_walls(config, fell=400)


def test_an_undated_ruin_is_as_eroded_as_a_very_old_one(config: Config) -> None:
    assert _ruin_walls(config, fell=None) == _ruin_walls(config, fell=0)


def test_erosion_stops_growing_after_the_rows_years(config: Config) -> None:
    years = int(config.get("sites.ruin_erosion_years"))
    assert _ruin_walls(config, fell=1200 - years) == _ruin_walls(config, fell=1200 - 2 * years)
