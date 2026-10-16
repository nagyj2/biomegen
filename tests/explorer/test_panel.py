"""Tests for the explorer info panel and help overlay."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.explorer.panel import build_panel, controls_line, draw_help, view_label
from biomegen.explorer.state import MODE_ONE_TO_ONE, ViewState
from biomegen.render.grid import CellGrid
from biomegen.render.layers import Seen
from biomegen.sampling.detail import SCALE_LOCAL, SCALE_ZOOM
from biomegen.world.entities import POI, Realm
from biomegen.world.tile import Biome, Cell, WaterType
from tests.render.conftest import make_world


def _lines(grid: CellGrid) -> list[str]:
    return ["".join(row) for row in grid.glyph.tolist()]


def _panel(world, config: Config, state: ViewState | None = None, seen: Seen | None = None, width=100, height=12):
    world.island_name = "Testland"
    state = state or ViewState(cx=2, cy=1)
    return _lines(build_panel(world, config, state, "terrain", seen or Seen(), width, height))


def test_panel_has_the_requested_size(config: Config) -> None:
    grid = build_panel(make_world(6, 3), config, ViewState(), "terrain", Seen(), 80, 10)
    assert (grid.rows, grid.cols) == (10, 80)


def test_island_line_names_the_island_seed_view_and_floor(config: Config) -> None:
    line = _panel(make_world(6, 3), config)[1]
    assert "Testland" in line and "seed 1" in line and "view FIT / terrain" in line and "floor 0" in line


def test_cursor_line_gives_coordinates_and_biome(config: Config) -> None:
    line = _panel(make_world(6, 3, Biome.FOREST), config)[2]
    assert "cursor (2,1)" in line and "biome forest" in line and "elev 100 m" in line


def test_unclaimed_land_has_no_realm(config: Config) -> None:
    assert "none (wild land)" in _panel(make_world(6, 3), config)[3]


def test_water_has_no_realm(config: Config) -> None:
    world = make_world(6, 3)
    world.water_type[:] = int(WaterType.SALT)
    assert "open water" in _panel(world, config)[3]


def test_realm_line_names_the_realm_its_ruler_and_size(config: Config) -> None:
    world = make_world(6, 3, Biome.FOREST)
    world.realms.append(
        Realm(id=0, kind="major", name="Kingdom of Aldor", ruler="Queen Mara", area_km2=12000.0, pop=345678)
    )
    world.realm_id[:] = 0
    lines = _panel(world, config)
    assert "Kingdom of Aldor" in lines[3] and "Queen Mara" in lines[3] and "12,000 km2, pop. ~345,678" in lines[4]


def test_poi_line_names_the_poi_under_the_cursor(config: Config) -> None:
    world = make_world(6, 3)
    world.pois.append(POI(kind="tower", x=2, y=1, interior_seed=1, name="Grey Spire"))
    world.poi_index[1, 2] = 0
    assert "Grey Spire (tower)" in _panel(world, config)[5]


def test_poi_line_is_empty_off_a_poi(config: Config) -> None:
    assert _panel(make_world(6, 3), config)[5].strip() == "POI: -"


def test_legend_lists_the_biomes_on_screen(config: Config) -> None:
    text = "\n".join(_panel(make_world(6, 3), config, seen=Seen(biomes={int(Biome.GRASS), int(Biome.FOREST)})))
    assert "Grassland" in text and "Temperate forest" in text and "Desert" not in text


def test_legend_lists_interior_items_but_not_void(config: Config) -> None:
    text = "\n".join(_panel(make_world(6, 3), config, seen=Seen(cells={int(Cell.VOID), int(Cell.TABLE)})))
    assert "table" in text and "void" not in text


def test_legend_can_be_switched_off() -> None:
    config = load_config(None)
    config.data["render"]["show_legend"] = False
    text = "\n".join(_panel(make_world(6, 3), config, seen=Seen(biomes={int(Biome.GRASS)})))
    assert "legend" not in text


def test_controls_follow_rebound_keys() -> None:
    config = load_config(None)
    config.data["keys"]["zoom"] = "x"
    assert "[x] zoom" in controls_line(config)


def test_controls_show_space_by_name(config: Config) -> None:
    assert "[space] zoom" in controls_line(config)


def test_latest_message_sits_at_the_end_of_the_controls_row(config: Config) -> None:
    state = ViewState(cx=0, cy=0)
    state.notify("scale: zoom")
    assert _panel(make_world(6, 3), config, state)[-1].rstrip().endswith("scale: zoom")


def test_a_very_narrow_panel_clips_instead_of_failing(config: Config) -> None:
    assert len(_panel(make_world(6, 3), config, seen=Seen(biomes={int(Biome.GRASS)}), width=12)) == 12


@pytest.mark.parametrize(
    ("state", "label"),
    [
        (ViewState(), "FIT"),
        (ViewState(mode=MODE_ONE_TO_ONE), "1:1"),
        (ViewState(scale=SCALE_ZOOM), "ZOOM"),
        (ViewState(scale=SCALE_LOCAL), "LOCAL"),
    ],
)
def test_view_label_names_the_scale(state: ViewState, label: str) -> None:
    assert view_label(state) == label


def test_help_lists_the_keys(config: Config) -> None:
    screen = CellGrid(20, 90)
    draw_help(screen, config)
    text = "\n".join(_lines(screen))
    assert "step out" in text and "fit-to-screen" in text and "8 tiles" in text


def test_help_follows_rebinding() -> None:
    config = load_config(None)
    config.data["keys"]["quit"] = "x"
    screen = CellGrid(20, 90)
    draw_help(screen, config)
    assert "x or Esc" in "\n".join(_lines(screen))


def test_help_fits_a_tiny_screen_without_error(config: Config) -> None:
    draw_help(CellGrid(4, 20), config)


def test_poi_line_gives_the_style_of_a_homestead(config: Config) -> None:
    world = make_world(6, 3)
    world.pois.append(POI(kind="homestead", x=2, y=1, interior_seed=1, name="Oak Farm", style="farm"))
    world.poi_index[1, 2] = 0
    assert "Oak Farm (homestead, farm)" in _panel(world, config)[5]


def test_legend_names_a_building_kind_roof_by_its_label(config: Config) -> None:
    from biomegen.sites.kinds import roof_cell

    seen = Seen(cells={roof_cell(config, "cathedral")})
    text = "\n".join(_panel(make_world(6, 3), config, seen=seen))
    assert "cathedral" in text


def test_legend_names_a_dress_variant_by_its_label(config: Config) -> None:
    from biomegen.sites.dress import variant_cell

    seen = Seen(cells={variant_cell(config, "field", "dead")})
    assert "dead field" in "\n".join(_panel(make_world(6, 3), config, seen=seen))
