"""Tests for the camp layout: clearing, tents (a roof outside, bedrolls inside), wagon, supplies and the road track."""

from __future__ import annotations

import numpy as np

from biomegen.config.model import Config
from biomegen.sites import read_patch, site_geometry, site_plan, site_roof_floor
from biomegen.sites.kinds import roof_cell
from biomegen.world.tile import Biome, Cell, WaterType
from tests.sites.conftest import add_poi, flat_world

VOID, BED, FIRE = (int(c) for c in (Cell.VOID, Cell.BED, Cell.CAMPFIRE))


def _camp(config: Config, world=None):
    world = world or flat_world(14, 10)
    poi = add_poi(world, "camp", 7, 5)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    return poi, world, plan


def test_a_camp_has_one_campfire(config: Config) -> None:
    _poi, _world, plan = _camp(config)
    assert int((plan.cells == FIRE).sum()) == 1


def test_the_campfire_is_near_the_middle_of_the_clearing(config: Config) -> None:
    _poi, _world, plan = _camp(config)
    ys, xs = np.nonzero(plan.cells != VOID)
    fy, fx = (int(v[0]) for v in np.nonzero(plan.cells == FIRE))
    assert abs(fx - (xs.min() + xs.max()) / 2) <= 3 and abs(fy - (ys.min() + ys.max()) / 2) <= 3


def test_a_camp_has_at_least_the_minimum_tents(config: Config) -> None:
    # Tents are separate blobs of TENT cells; overlapping pitches may merge, so count cells instead of blobs.
    _poi, _world, plan = _camp(config)
    assert int((plan.outside == roof_cell(config, "tent")).sum()) >= int(config.get("sites.camp.min_tents")) * 4


def test_the_clearing_is_bare_ground_outside_the_plan_edge(config: Config) -> None:
    # The clearing is an ellipse: the corners of the plan stay void so terrain shows through.
    _poi, _world, plan = _camp(config)
    assert plan.cells[0, 0] == VOID and plan.cells[-1, -1] == VOID


def test_a_camp_has_no_walls(config: Config) -> None:
    _poi, _world, plan = _camp(config)
    assert int(Cell.WALL) not in plan.cells


def test_a_camp_is_open_air_but_for_its_tents(config: Config) -> None:
    # The sky view differs from the inside only where a tent's roof covers it.
    _poi, _world, plan = _camp(config)
    assert (plan.cells != plan.outside).any() and (
        plan.outside[plan.cells != plan.outside] == roof_cell(config, "tent")
    ).all()


def _founding_camp(config: Config, seed: int):
    """A founding camp (one tent) for a seed: its plan, so the bedding of a single tent can be read on its own."""
    world = flat_world(14, 10)
    poi = add_poi(world, "camp", 7, 5, purpose="founding", interior_seed=seed)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None and len(plan.buildings) == 1
    return plan


def _bedding_box(plan) -> tuple[int, int, int, int, int, int]:
    """Return ``(tent width, tent height, bedding left, top, width, height)`` of the plan's one tent."""
    tent = plan.buildings[0]
    bed = plan.cells[tent.y : tent.y + tent.height, tent.x : tent.x + tent.width] == BED
    ys, xs = np.nonzero(bed)
    return (
        tent.width,
        tent.height,
        int(xs.min()),
        int(ys.min()),
        int(xs.max() - xs.min() + 1),
        int(ys.max() - ys.min() + 1),
    )


def test_the_bedding_of_a_tent_never_reaches_its_edge(config: Config) -> None:
    # A margin of at least one cell is left on every side between the bedrolls and the tent's edge.
    for seed in range(12):
        width, height, left, top, bed_w, bed_h = _bedding_box(_founding_camp(config, seed))
        assert left >= 1 and top >= 1 and left + bed_w <= width - 1 and top + bed_h <= height - 1


def test_the_bedding_is_not_always_one_smaller_than_the_tent(config: Config) -> None:
    # Its size varies: across seeds the room left round it takes more than one value.
    margins = set()
    for seed in range(12):
        width, height, _left, _top, bed_w, bed_h = _bedding_box(_founding_camp(config, seed))
        margins.add((width - bed_w, height - bed_h))
    assert len(margins) > 1


def test_gear_lies_on_the_bare_floor_of_a_tent(config: Config) -> None:
    # Some gear lies under a roof, and every cell under a tent roof is a support, bedding, floor or gear.
    world = flat_world(14, 10)
    poi = add_poi(world, "camp", 7, 5, purpose="army", interior_seed=9)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    under = plan.cells[plan.outside == roof_cell(config, "tent")]
    gear = [int(Cell.CHEST), int(Cell.CRATE), int(Cell.BARREL), int(Cell.SHELF)]
    supports = [int(Cell.POST), int(Cell.TARP), int(Cell.TARP_LIFT)]
    assert np.isin(under, gear).any() and np.isin(under, [BED, int(Cell.FLOOR), *supports, *gear]).all()


def test_a_camp_has_a_roof_level_that_shows_its_tents_as_roofs(config: Config) -> None:
    poi, world, plan = _camp(config)
    roof = site_plan(poi, site_roof_floor(poi, config), config, world)
    assert roof is not None and np.array_equal(roof.cells, plan.outside) and (roof.cells == FIRE).any()


def test_every_tent_of_a_camp_is_a_listed_building(config: Config) -> None:
    _poi, _world, plan = _camp(config)
    assert plan.buildings and {building.kind for building in plan.buildings} == {"tent"}


def test_a_camp_keeps_off_water(config: Config) -> None:
    world = flat_world(14, 10, Biome.GRASS)
    world.biome[:, :6] = int(Biome.SHALLOW)
    world.water_type[:, :6] = int(WaterType.SALT)
    poi, world, plan = _camp(config, world)
    patch = read_patch(poi, site_geometry(poi, config), world, config)
    assert not ((plan.cells != VOID) & patch.water).any()


def test_a_road_runs_through_the_camp_clear_of_the_tents(config: Config) -> None:
    # The road arrives from the east and runs on to the fire: the plan leaves its cells void and pitches no tent on it.
    world = flat_world(14, 10)
    world.road[5, 7:14] = 1
    poi, _world, plan = _camp(config, world)
    patch = read_patch(poi, site_geometry(poi, config), world, config)
    assert patch.gates and not (patch.road & (plan.outside == roof_cell(config, "tent"))).any()


def test_a_camp_without_a_road_has_no_gate(config: Config) -> None:
    poi, world, _plan = _camp(config)
    assert read_patch(poi, site_geometry(poi, config), world, config).gates == ()


def test_a_purpose_selects_its_own_site_row(config: Config) -> None:
    # An army camp's row (camp_army) is larger than the plain camp row, so its site spans more of the window.
    world = flat_world(14, 10)
    plain, army = add_poi(world, "camp", 3, 5), add_poi(world, "camp", 10, 5, purpose="army")
    first, second = site_geometry(plain, config), site_geometry(army, config)
    assert (
        first is not None
        and second is not None
        and second.extent[2] - second.extent[0] > first.extent[2] - first.extent[0]
    )


def test_a_purpose_without_a_row_falls_back_to_the_plain_kind(config: Config) -> None:
    world = flat_world(14, 10)
    odd, plain = add_poi(world, "camp", 3, 5, purpose="picnic"), add_poi(world, "camp", 3, 5)
    assert site_geometry(odd, config) == site_geometry(plain, config)


def test_every_camp_purpose_row_builds_a_plan(config: Config) -> None:
    for purpose in ("founding", "bandit", "army"):
        world = flat_world(14, 10)
        assert site_plan(add_poi(world, "camp", 7, 5, purpose=purpose), 0, config, world) is not None


def test_an_army_camp_pitches_more_tents_than_a_bandit_camp(config: Config) -> None:
    # Same site seed, so only the purpose row differs.
    world = flat_world(14, 10)
    counts = {}
    for purpose in ("army", "bandit"):
        poi = add_poi(world, "camp", 7, 5, purpose=purpose, interior_seed=9)
        plan = site_plan(poi, 0, config, world)
        assert plan is not None
        counts[purpose] = int((plan.outside == roof_cell(config, "tent")).sum())
        world.poi_index[5, 7] = -1
        world.pois.pop()
    assert counts["army"] > counts["bandit"]


def test_a_founding_camp_keeps_fewer_tents_than_a_bandit_camp(config: Config) -> None:
    world = flat_world(14, 10)
    counts = {}
    for purpose in ("founding", "bandit"):
        poi = add_poi(world, "camp", 7, 5, purpose=purpose, interior_seed=9)
        plan = site_plan(poi, 0, config, world)
        assert plan is not None
        counts[purpose] = int((plan.outside == roof_cell(config, "tent")).sum())
        world.poi_index[5, 7] = -1
        world.pois.pop()
    assert counts["founding"] < counts["bandit"]


# --- how a tent's canopy meets the ground -----------------------------------------------------------------------


def _supports_of(height: int, width: int, seed: int = 0, **settings):
    """The ``(posts, tarp, lift)`` masks of a tent, from the default camp settings with ``settings`` overriding."""
    import random

    from biomegen.config import load_config
    from biomegen.sites.camp import _supports

    merged = {**load_config(None).get("sites.camp"), **settings}
    return _supports(height, width, random.Random(seed), merged)


def _ring_labels(height: int, width: int, masks) -> str:
    """Label the edge cells clockwise: T tarp, L lift, P post, O open."""
    from biomegen.sites.camp import _ring

    posts, tarp, lift = masks
    return "".join("P" if posts[c] else "T" if tarp[c] else "L" if lift[c] else "O" for c in _ring(height, width))


TENTS = ((3, 6), (4, 6), (3, 8), (4, 8))


def _open_runs(labels: str) -> list[tuple[str, int, str]]:
    """Return ``(label before, length, label after)`` of each run of open cells round the edge."""
    start = next(index for index, label in enumerate(labels) if label != "O")
    turned = labels[start:] + labels[:start]
    runs, index = [], 0
    while index < len(turned):
        if turned[index] != "O":
            index += 1
            continue
        end = index
        while end < len(turned) and turned[end] == "O":
            end += 1
        runs.append((turned[index - 1], end - index, turned[end % len(turned)]))
        index = end
    return runs


def test_a_tent_with_no_tarp_hangs_from_posts_at_its_corners() -> None:
    # Roof only: every side is open, so each corner has a pole and nothing touches the ground.
    posts, tarp, lift = _supports_of(3, 6, tent_tarp_sides=[1, 0, 0, 0])
    assert not (tarp | lift).any() and posts[0, 0] and posts[0, 5] and posts[2, 0] and posts[2, 5]


def test_one_tarp_side_needs_only_two_poles() -> None:
    # A lean-to: the tarp side and its two corners touch the ground, so only the far corners hold the canopy up.
    for seed in range(10):
        posts, tarp, _lift = _supports_of(3, 6, seed, tent_tarp_sides=[0, 1, 0, 0], tent_taper=0.0)
        assert int(posts.sum()) == 2 and int(tarp.sum()) in (6, 3)


def test_a_tarp_never_touches_all_four_sides() -> None:
    # A tent keeps an open side, so a pole holds the canopy up; with up to three sides it still has a tarp.
    for seed in range(40):
        for height, width in TENTS:
            labels = _ring_labels(height, width, _supports_of(height, width, seed, tent_tarp_sides=[0, 1, 1, 1]))
            assert "T" in labels and "P" in labels


def test_every_tent_has_a_post() -> None:
    assert all(_supports_of(h, w, seed)[0].any() for seed in range(60) for h, w in TENTS)


def test_a_tarp_side_runs_the_whole_side_when_it_is_not_tapered() -> None:
    # A tarp touches the ground over several cells, not at a point: a side is wholly tarp or has none.
    for seed in range(30):
        _posts, tarp, _lift = _supports_of(3, 8, seed, tent_taper=0.0)
        for row in (0, 2):
            run = tarp[row, 1:-1]
            assert run.all() or not run.any()


def test_a_post_corner_has_no_tarp_beside_it() -> None:
    # A corner is a post only between two open sides, so no tarp touches it.
    for seed in range(40):
        posts, tarp, lift = _supports_of(4, 6, seed)
        for (y, x), (ny, nx) in (((0, 0), (0, 1)), ((0, 5), (0, 4)), ((3, 0), (3, 1)), ((3, 5), (3, 4))):
            if posts[y, x]:
                assert not (tarp[y, x] or tarp[ny, nx] or lift[ny, nx])


def test_an_open_stretch_held_by_the_ground_at_both_ends_gets_a_pole() -> None:
    # Poles make sense: a run of open cells with tarp (or a lifted end) at each end would hang from nothing.
    for seed in range(60):
        for height, width in TENTS:
            runs = _open_runs(_ring_labels(height, width, _supports_of(height, width, seed)))
            assert not any(before in "TL" and after in "TL" for before, _length, after in runs)


def test_no_open_stretch_is_longer_than_the_post_gap() -> None:
    for seed in range(60):
        for height, width in TENTS:
            runs = _open_runs(_ring_labels(height, width, _supports_of(height, width, seed)))
            assert all(length <= 5 for _before, length, _after in runs)


def test_a_tarp_end_can_lift_off_the_ground() -> None:
    # With the taper certain, the end of a tarp that meets a long enough open side runs on as a half-touching cell.
    lifted = [
        bool(_supports_of(3, 8, seed, tent_tarp_sides=[0, 0, 1, 0], tent_taper=1.0)[2].any()) for seed in range(20)
    ]
    assert any(lifted)


def test_a_lift_is_beside_a_tarp_and_never_the_last_open_cell() -> None:
    # The lift sits on the end of a tarp, and the stretch it shortens keeps a pole.
    for seed in range(60):
        for height, width in TENTS:
            posts, tarp, lift = _supports_of(height, width, seed, tent_taper=1.0)
            from biomegen.sites.camp import _ring

            ring = _ring(height, width)
            for index, cell in enumerate(ring):
                if lift[cell]:
                    neighbours = (ring[index - 1], ring[(index + 1) % len(ring)])
                    assert any(tarp[n] for n in neighbours)
            assert posts.any()


def test_a_long_open_side_gets_a_post_between_its_corners() -> None:
    # Open sides longer than the gap are not left to hang from just their ends.
    posts, _tarp, _lift = _supports_of(3, 9, tent_tarp_sides=[1, 0, 0, 0], tent_post_gap=5)
    assert int(posts[0].sum()) > 2


def test_posts_and_tarp_show_on_the_ground_view_under_the_tent_roof(config: Config) -> None:
    # Across a field of tents, both supports appear on the inside, only under tent roofs.
    world = flat_world(14, 10)
    poi = add_poi(world, "camp", 7, 5, purpose="army", interior_seed=9)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    roofed = plan.outside == roof_cell(config, "tent")
    posts, tarp, lift = (plan.cells == int(c) for c in (Cell.POST, Cell.TARP, Cell.TARP_LIFT))
    assert posts.any() and tarp.any() and lift.any() and not ((posts | tarp | lift) & ~roofed).any()
