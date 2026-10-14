"""Tests for Phase 6: SVG/PNG export (colour resolution, document validity, determinism)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np
import pytest

from biomegen import export, pipeline
from biomegen.config import load_config
from biomegen.export import png, svg
from biomegen.export.colors import ExportPalette, contrast_rgb
from biomegen.render.state import SCALE_ZOOM, ViewState
from biomegen.world.tile import INTERIOR_COLOR_BASE, Biome, Cell


@pytest.fixture(scope="module")
def cfg():
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg):
    # Seed 1 reliably produces regions, roads and several POIs (shared with the interior tests).
    return pipeline.generate(cfg, 1)


# --------------------------------------------------------------------------- colour resolver


def test_biome_rgb_matches_palette_config(cfg, world):
    # The exporter's biome colours are the exact render.palette numbers (TUI and image agree).
    pal = ExportPalette(cfg, world)
    palette_cfg = cfg.get("render.palette")
    assert pal.biome_rgb(int(Biome.FOREST)) == tuple(palette_cfg["forest"])
    assert pal.biome_rgb(int(Biome.DESERT)) == tuple(palette_cfg["desert"])


def test_tile_rgb_ocean_uses_ocean_colour(cfg, world):
    # An ocean tile resolves to the ocean palette colour, not a region colour.
    pal = ExportPalette(cfg, world)
    ys, xs = np.nonzero(world.biome == int(Biome.OCEAN))
    y, x = int(ys[0]), int(xs[0])
    assert pal.tile_rgb(world, x, y) == tuple(cfg.get("render.palette")["ocean"])


def test_tile_rgb_land_uses_region_base_color(cfg, world):
    # A land tile takes its region's base_color (the per-region jittered hue). Coastal-ocean tiles a
    # region claims for naming still render as ocean (tile_attr checks the OCEAN biome first), so pick
    # a genuinely dry tile of the region here.
    pal = ExportPalette(cfg, world)
    region = world.regions[0]
    ys, xs = np.nonzero((world.region_id == region.id) & (world.biome != int(Biome.OCEAN)))
    y, x = int(ys[0]), int(xs[0])
    assert pal.tile_rgb(world, x, y) == tuple(region.base_color)


def test_zoom_rgb_decodes_interior_colour(cfg, world):
    # Ids >= INTERIOR_COLOR_BASE decode to interior Cell colours; below, to biome colours.
    pal = ExportPalette(cfg, world)
    wall_id = INTERIOR_COLOR_BASE + int(Cell.WALL)
    assert pal.zoom_rgb(wall_id) == tuple(cfg.get("render.interior_palette")["wall"])
    assert pal.zoom_rgb(int(Biome.SNOW)) == pal.biome_rgb(int(Biome.SNOW))


def test_void_interior_cell_has_no_colour(cfg, world):
    # VOID is never drawn (terrain shows through), so it resolves to None.
    pal = ExportPalette(cfg, world)
    assert pal.interior_rgb(int(Cell.VOID)) is None


def test_contrast_rgb_flips_on_luma():
    # Dark glyph on a light fill, light glyph on a dark fill - so glyphs stay legible.
    assert contrast_rgb((250, 250, 250)) == (20, 20, 20)
    assert contrast_rgb((10, 20, 30)) == (236, 236, 236)


# --------------------------------------------------------------------------- SVG document


def test_grid_to_svg_is_well_formed_xml():
    # A tiny grid renders to a parseable <svg> with a background plus one fill rect.
    grid = [[((100, 150, 200), "f", (0, 0, 0), False)]]
    doc = svg.grid_to_svg(grid, cell_px=12, background=(0, 0, 0))
    root = ET.fromstring(doc)
    assert root.tag.endswith("svg")
    assert root.attrib["width"] == "12" and root.attrib["height"] == "12"
    rects = root.iter("{http://www.w3.org/2000/svg}rect")
    assert sum(1 for _ in rects) >= 2  # background + the cell


def test_svg_escapes_xml_special_glyphs():
    # A glyph that is XML-sensitive (e.g. '<') must be escaped, not break the document.
    grid = [[((100, 100, 100), "<", (255, 255, 255), False)]]
    doc = svg.grid_to_svg(grid, cell_px=10, background=(0, 0, 0))
    assert "&lt;" in doc
    ET.fromstring(doc)  # still parses


def test_export_world_writes_valid_svg(cfg, world, tmp_path):
    cfg.data["export"]["dir"] = str(tmp_path)
    cfg.data["export"]["png"] = False  # SVG-only path here; PNG covered separately
    paths = export.export_world(world, cfg)
    svgs = [p for p in paths if p.endswith(".svg")]
    assert len(svgs) == 1
    root = ET.parse(svgs[0]).getroot()
    assert root.tag.endswith("svg")


def test_export_world_is_deterministic(cfg, world, tmp_path):
    # Same seed -> byte-identical SVG (the export analogue of the golden-world fingerprint).
    cfg.data["export"]["dir"] = str(tmp_path)
    cfg.data["export"]["png"] = False
    first = export.export_world(world, cfg)[0]
    data1 = open(first, encoding="utf-8").read()
    export.export_world(world, cfg)  # overwrites the same path
    data2 = open(first, encoding="utf-8").read()
    assert data1 == data2


def test_export_view_detail_scale(cfg, world, tmp_path):
    # A zoom-scale view export names the file by its scale and writes a valid SVG.
    cfg.data["export"]["dir"] = str(tmp_path)
    cfg.data["export"]["png"] = False
    poi = next(p for p in world.pois if p.footprint[0] > 0)
    vs = ViewState(cx=poi.x, cy=poi.y, scale=SCALE_ZOOM, cam_x=max(0, poi.x - 8), cam_y=max(0, poi.y - 5))
    paths = export.export_view(world, cfg, vs, area_w=100, area_h=40)
    assert any(p.endswith("_zoom.svg") for p in paths)
    ET.parse(paths[0]).getroot()


# --------------------------------------------------------------------------- filenames


def test_filename_pattern_resolves_and_sanitizes(cfg, world):
    # {name}/{seed}/{view} substitute; spaces and punctuation collapse to single underscores.
    world.island_name = "Isle of  Mist!"
    base = export._base_name(cfg, world, "world")
    assert base == "Isle_of_Mist_1_world"


# --------------------------------------------------------------------------- PNG (optional)


@pytest.mark.skipif(not png.pillow_available(), reason="Pillow not installed")
def test_export_world_writes_png_when_pillow_present(cfg, world, tmp_path):
    cfg.data["export"]["dir"] = str(tmp_path)
    cfg.data["export"]["png"] = True
    paths = export.export_world(world, cfg)
    pngs = [p for p in paths if p.endswith(".png")]
    assert len(pngs) == 1
    assert open(pngs[0], "rb").read(8) == b"\x89PNG\r\n\x1a\n"  # PNG magic number


def test_grid_to_png_reports_false_without_pillow(monkeypatch, tmp_path):
    # When Pillow is unimportable the rasterizer degrades gracefully (no crash, returns False).
    import builtins

    real_import = builtins.__import__

    def _no_pillow(name, *args, **kwargs):
        if name.startswith("PIL"):
            raise ImportError("Pillow disabled for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pillow)
    grid = [[((10, 10, 10), "f", (255, 255, 255), False)]]
    assert png.grid_to_png(grid, 8, (0, 0, 0), str(tmp_path / "x.png")) is False
