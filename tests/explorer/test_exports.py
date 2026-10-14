"""Tests for the explorer's SVG / PNG exports."""

from __future__ import annotations

from pathlib import Path

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.explorer.exports import base_name, export_screen, export_world, write_grid
from biomegen.render.backends.png import pillow_available
from biomegen.render.grid import CellGrid
from biomegen.world.tile import Biome
from tests.render.conftest import make_world


def _config(tmp_path: Path, **export) -> Config:
    config = load_config(None)
    config.data["export"].update({"dir": str(tmp_path / "out"), "png": False, **export})
    return config


def _world():
    world = make_world(8, 4, Biome.GRASS)
    world.island_name = "Test Land!"
    return world


def test_name_is_sanitized_and_follows_the_pattern(tmp_path: Path) -> None:
    assert base_name(_config(tmp_path), _world(), "world") == "Test_Land_1_world"


def test_custom_pattern_is_honoured(tmp_path: Path) -> None:
    config = _config(tmp_path, filename_pattern="{view}-{seed}")
    assert base_name(config, _world(), "zoom") == "zoom-1"


def test_unnamed_island_gets_a_default_name(tmp_path: Path) -> None:
    world = make_world(4, 4)
    assert base_name(_config(tmp_path), world, "world").startswith("island_")


def test_world_export_writes_an_svg(tmp_path: Path) -> None:
    paths = export_world(_world(), _config(tmp_path))
    assert [Path(p).suffix for p in paths] == [".svg"] and Path(paths[0]).read_text(encoding="utf-8").startswith("<svg")


def test_world_export_is_one_cell_per_tile(tmp_path: Path) -> None:
    # An 8 x 4 world at 12 px per cell is 96 x 48 pixels.
    text = Path(export_world(_world(), _config(tmp_path))[0]).read_text(encoding="utf-8")
    assert 'width="96"' in text and 'height="48"' in text


def test_export_directory_is_created(tmp_path: Path) -> None:
    config = _config(tmp_path)
    export_world(_world(), config)
    assert (tmp_path / "out").is_dir()


def test_screen_export_is_labelled_with_the_scale(tmp_path: Path) -> None:
    paths = export_screen(_world(), _config(tmp_path), CellGrid(3, 5), "zoom", "terrain")
    assert Path(paths[0]).name == "Test_Land_1_zoom.svg"


def test_screen_export_labels_a_data_view(tmp_path: Path) -> None:
    paths = export_screen(_world(), _config(tmp_path), CellGrid(3, 5), "local", "elevation")
    assert Path(paths[0]).name == "Test_Land_1_local-elevation.svg"


def test_world_export_labels_a_data_view(tmp_path: Path) -> None:
    assert Path(export_world(_world(), _config(tmp_path), "rainfall")[0]).name.endswith("world-rainfall.svg")


def test_png_is_skipped_when_disabled(tmp_path: Path) -> None:
    assert len(write_grid(CellGrid(2, 2), _config(tmp_path, png=False), _world(), "x")) == 1


@pytest.mark.skipif(not pillow_available(), reason="Pillow is not installed")
def test_png_is_written_next_to_the_svg(tmp_path: Path) -> None:
    paths = write_grid(CellGrid(2, 2), _config(tmp_path, png=True), _world(), "x")
    assert [Path(p).suffix for p in paths] == [".svg", ".png"]
