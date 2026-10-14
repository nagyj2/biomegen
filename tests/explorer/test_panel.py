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
from biomegen.world.entities import POI, Region
from biomegen.world.tile import Biome, Cell
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


def test_open_ocean_when_there_is_no_region(config: Config) -> None:
    assert "open ocean" in _panel(make_world(6, 3), config)[3]


def test_region_line_names_the_region_and_its_lore(config: Config) -> None:
    world = make_world(6, 3, Biome.FOREST)
    world.regions.append(Region(id=0, biome_class=int(Biome.FOREST), size=18, name="Greenwood", lore=["Old trees."]))
    world.region_id[:] = 0
    lines = _panel(world, config)
    assert "Greenwood" in lines[3] and "18 tiles" in lines[3] and "Old trees." in lines[4]


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
