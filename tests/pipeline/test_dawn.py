"""Tests for the dawn start (history.start = "dawn"): a young world at year 0 with nothing settled."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from biomegen import cli, pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.explorer.app import compose_frame, run
from biomegen.explorer.exports import export_world
from biomegen.explorer.state import ViewState
from biomegen.render.static import render_detail, render_static
from biomegen.sampling.detail import SCALE_LOCAL, SCALE_ZOOM
from biomegen.world.overlay import Overlay
from biomegen.world.world import World
from tests.explorer.replay import RecordingOut
from tests.explorer.test_app import ScriptedKeys


def _dawn_config() -> Config:
    config = load_config(None)
    config.data["history"]["start"] = "dawn"
    return config


@pytest.fixture(scope="module")
def config() -> Config:
    return _dawn_config()


@pytest.fixture(scope="module")
def dawn(config: Config) -> World:
    return pipeline.generate(config, 42)


def test_dawn_is_year_zero(dawn: World) -> None:
    assert dawn.year == 0


def test_dawn_has_no_history(dawn: World) -> None:
    assert (dawn.chronicle, dawn.fallen_realms) == ([], [])


def test_dawn_has_no_realms_or_relations(dawn: World) -> None:
    assert (dawn.realms, dawn.relations) == ([], [])


def test_dawn_has_no_settlements_or_pois(dawn: World) -> None:
    assert dawn.pois == [] and (dawn.poi_index == -1).all()


def test_dawn_has_no_roads_or_fronts(dawn: World) -> None:
    assert not dawn.road.any() and not dawn.front.any()


def test_dawn_land_is_unclaimed(dawn: World) -> None:
    assert (dawn.realm_id == -1).all()


def test_dawn_keeps_the_physical_world(dawn: World, config: Config) -> None:
    # The land is the present start's: the stages before settlements are untouched by the start mode.
    present = pipeline.generate(load_config(None), 42)
    assert np.array_equal(dawn.elevation_m, present.elevation_m) and np.array_equal(dawn.biome, present.biome)


def test_dawn_keeps_rivers_and_features(dawn: World) -> None:
    assert dawn.rivers and dawn.features


def test_dawn_names_its_island_and_features(dawn: World) -> None:
    assert dawn.island_name and all(f.name for f in dawn.features)


def test_dawn_is_deterministic(config: Config) -> None:
    assert pipeline.generate(config, 42).fingerprint() == pipeline.generate(config, 42).fingerprint()


def test_dawn_differs_from_the_present_start(dawn: World) -> None:
    assert dawn.fingerprint() != pipeline.generate(load_config(None), 42).fingerprint()


def test_dawn_skips_the_political_stages() -> None:
    timings: dict[str, float] = {}
    pipeline.generate(_dawn_config(), 42, timings)
    assert not set(timings) & pipeline.DAWN_SKIPPED and "naming" in timings


def test_dawn_stats_count_nothing_political(dawn: World) -> None:
    stats = pipeline.stats(dawn)
    assert (stats["realms"], stats["events"], stats["pois"], stats["road_tiles"]) == (0, 0, 0, 0)


@pytest.mark.parametrize("view", ["terrain", "political", "elevation", "temperature", "rainfall"])
def test_dawn_draws_every_view(dawn: World, config: Config, view: str) -> None:
    assert render_static(dawn, config, view).document


@pytest.mark.parametrize("scale", [SCALE_ZOOM, SCALE_LOCAL])
def test_dawn_draws_the_detail_scales(dawn: World, config: Config, scale: str) -> None:
    assert render_detail(dawn, config, scale, "political", at=(100, 30)).document


def test_dawn_composes_an_explorer_frame(dawn: World, config: Config) -> None:
    frame = compose_frame(dawn, config, ViewState(cx=100, cy=30), Overlay(), (100, 40))
    assert (frame.screen.cols, frame.screen.rows) == (100, 40)


def test_the_explorer_runs_on_a_dawn_world(dawn: World, config: Config) -> None:
    # Move, cycle the view and zoom in on a world with nothing in it, then quit.
    out = RecordingOut(40, 100)
    run(dawn, config, "none", reader=ScriptedKeys("right", "v", "enter", "q"), out=out, get_size=lambda: (100, 40))
    assert out.frames


def test_start_flag_overrides_the_config(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--seed", "3", "--width", "64", "--height", "32", "--start", "dawn", "--headless"]) == 0
    assert "realms=0" in capsys.readouterr().out


def test_chronicle_of_a_dawn_world_is_just_the_title(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--seed", "3", "--width", "64", "--height", "32", "--start", "dawn", "--chronicle"]) == 0
    assert capsys.readouterr().out.strip().endswith("(year 0)")


def test_a_dawn_world_exports_to_svg(dawn: World, config: Config, tmp_path: Path) -> None:
    exporting = load_config(None)
    exporting.data["export"]["dir"] = str(tmp_path)
    exporting.data["export"]["png"] = False
    paths = export_world(dawn, exporting)
    assert paths and Path(paths[0]).read_text(encoding="utf-8").startswith("<svg")
