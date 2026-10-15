"""The legend and gazetteer printed under a static map: swatches, the data-ramp bar, geography and climate."""

from __future__ import annotations

import textwrap
from typing import Optional

import numpy as np

from ...config.model import Config
from ...world.tile import BIOME_NAME, WaterType
from ...world.world import World
from ..colors import biome_style, mix_colors
from ..grid import RGB, Document, Span
from ..poi_style import poi_marker
from ..views import View

_Swatch = tuple[str, Optional[RGB], Optional[RGB], str]  # glyph, fg, bg, label


def _color(value: list) -> RGB:
    return (int(value[0]), int(value[1]), int(value[2]))


class _Text:
    """Accumulates legend lines in the configured colours."""

    def __init__(self, config: Config, width: int) -> None:
        cfg = config.get("render.legend")
        self.header_fg = _color(cfg["header_fg"])
        self.text_fg = _color(cfg["text_fg"])
        self.dim_fg = _color(cfg["dim_fg"])
        self.width = width
        self.lines: Document = []

    def header(self, text: str) -> None:
        self.lines.append([Span("")])
        self.lines.append([Span(text, self.header_fg, None, True)])

    def para(self, text: str, fg: Optional[RGB] = None, indent: int = 2) -> None:
        for line in textwrap.wrap(text, max(20, self.width - indent), subsequent_indent="   "):
            self.lines.append([Span(" " * indent + line, fg or self.text_fg)])


def _degrees(ascii_only: bool) -> str:
    return "" if ascii_only else "°"


def _latitude(value: float, ascii_only: bool) -> str:
    return f"{abs(value):.1f}{_degrees(ascii_only)}{'N' if value >= 0 else 'S'}"


def _longitude(value: float, ascii_only: bool) -> str:
    return f"{abs(value):.1f}{_degrees(ascii_only)}{'E' if value >= 0 else 'W'}"


def _position(world: World, x: int, y: int, ascii_only: bool) -> str:
    return f"{_latitude(world.scale.lat_of_row(y), ascii_only)} {_longitude(world.scale.lon_of_col(x), ascii_only)}"


def _area(km2: float, ascii_only: bool) -> str:
    unit = "km2" if ascii_only else "km²"
    if km2 >= 1e6:
        return f"{km2 / 1e6:.1f} million {unit}"
    return f"{km2:,.0f} {unit}"


def _swatches(world: World, config: Config, view: View, ascii_only: bool) -> list[_Swatch]:
    """Return the legend swatches for what this view of this world actually shows."""
    items: list[_Swatch] = []
    biome_rows = config.get("tables.biomes")
    glyph_key = "ascii" if ascii_only else "glyph"
    if not view.tint:
        for biome in sorted(int(b) for b in np.unique(world.biome)):
            row = biome_rows[BIOME_NAME[biome]]
            items.append((row[glyph_key] or " ", _color(row["fg"]), _color(row["bg"]), row["label"]))
    water = config.get("render.water")
    land = ~biome_style(config).water[world.biome]
    if (land & (world.water_type == int(WaterType.FRESH))).any():
        items.append(
            (
                water["river_ascii" if ascii_only else "river_glyph"],
                _color(water["river_fg"]),
                _color(water["river_mix"]),
                "River",
            )
        )
    shows_relief = not view.ramp or config.get(f"render.ramps.{view.ramp}.keep_relief", False)
    if shows_relief:
        tints = config.get("render.relief_tints")
        for relief in sorted(int(r) for r in np.unique(world.relief) if r):
            name = ("none", "hills", "mountain", "peak", "volcano")[relief]
            row = config.get(f"tables.relief.{name}")
            fill = tints.get(name, {}).get("bg") or tints["mountain"]["mix"]
            low = row.get("min_elevation_m")
            label = f"{row['label']} {low:,.0f}+ m" if low else row["label"]
            items.append((row[glyph_key], _color(row["fg"]), _color(fill), label))
    if world.road.any():
        roads = config.get("render.roads")
        items.append((roads["ascii" if ascii_only else "glyphs"][10], _color(roads["fg"]), None, "Road"))
    for kind in sorted({poi.kind for poi in world.pois}):
        glyph, fg, bg = poi_marker(config, kind, ascii_only)
        items.append((glyph, fg, bg, kind.title()))
    return items


def _ramp_bar(text: _Text, config: Config, view: View, ascii_only: bool) -> None:
    ramp = config.get(f"render.ramps.{view.ramp}")
    stops = ramp["stops"]
    unit = ramp.get("unit_ascii", ramp.get("unit", "")) if ascii_only else ramp.get("unit", "")
    segment = max(4, min(10, (text.width - 10) // len(stops)))
    bar: list[Span] = [Span("  ")]
    labels = "  "
    for index, (value, color) in enumerate(stops):
        following = stops[index + 1][1] if index + 1 < len(stops) else color
        for step in range(segment):
            fill = mix_colors(np.array(color, dtype=np.float64), np.array(following, dtype=np.float64), step / segment)
            bar.append(Span(" ", None, _color(fill.tolist())))
        labels += f"{value:,}".ljust(segment)
    text.header(f"{ramp['label'].upper()} ({unit})")
    text.lines.append(bar)
    text.lines.append([Span(labels, text.dim_fg)])


def _geography(text: _Text, world: World, config: Config, ascii_only: bool) -> None:
    cfg = config.get("render.legend")
    scale = world.scale
    km_w, km_h = world.width * scale.km_per_col, world.height * scale.km_per_row
    text.header("GEOGRAPHY")
    south = _latitude(scale.lat_of_row(world.height - 1), ascii_only)
    north = _latitude(scale.lat_of_row(0), ascii_only)
    west = _longitude(scale.lon_of_col(0), ascii_only)
    east = _longitude(scale.lon_of_col(world.width - 1), ascii_only)
    text.para(
        f"Extent {km_w:,.0f} km E-W x {km_h:,.0f} km N-S, from {south} to {north} and {west} to {east}. "
        f"One map cell = {scale.km_per_col:.0f} x {scale.km_per_row:.0f} km.",
        text.dim_fg,
    )
    features = {feature.id: feature for feature in world.features}

    def by_area(kind: str) -> list:
        named = [f for f in world.features if f.kind == kind and f.name]
        return sorted(named, key=lambda f: (-f.area_km2, f.id))

    bullet = "-" if ascii_only else "•"

    def summit(feature) -> str:
        peak = features.get(feature.summit)
        return f"; highest point {peak.name} ({peak.elevation_m:,.0f} m)" if peak and peak.name else ""

    for landmass in by_area("landmass")[: int(cfg["max_landmasses"])]:
        kind = "continent" if landmass.area_km2 > float(cfg["continent_km2"]) else "island"
        text.para(f"{bullet} {landmass.name} - {kind}, {_area(landmass.area_km2, ascii_only)}{summit(landmass)}")
    for mountains in by_area("range")[: int(cfg["max_ranges"])]:
        text.para(f"{bullet} {mountains.name} - {_area(mountains.area_km2, ascii_only)}{summit(mountains)}")
    for river in sorted((f for f in world.features if f.kind == "river" and f.name), key=lambda f: f.id):
        mouth = features.get(river.into)
        into = f" and flows into {mouth.name}" if mouth and mouth.name else ""
        text.para(f"{bullet} {river.name} - {river.length_km:,.0f} km{into}")
    for lake in by_area("lake")[: int(cfg["max_lakes"])]:
        text.para(f"{bullet} {lake.name} - {_area(lake.area_km2, ascii_only)}")
    for sea in sorted((f for f in world.features if f.kind == "sea" and f.name), key=lambda f: f.id):
        text.para(f"{bullet} {sea.name} - depths to {abs(sea.elevation_m):,.0f} m")


def _climate(text: _Text, world: World, config: Config, ascii_only: bool) -> None:
    land = ~biome_style(config).water[world.biome]
    if not land.any():
        return
    unit = "degC" if ascii_only else "°C"

    def at(field: np.ndarray, which: str) -> tuple[int, int]:
        values = np.where(land, field, np.inf if which == "min" else -np.inf)
        flat = int(np.argmin(values) if which == "min" else np.argmax(values))
        return flat % world.width, flat // world.width

    cold, hot = at(world.temperature_c, "min"), at(world.temperature_c, "max")
    dry, wet = at(world.rain_mm, "min"), at(world.rain_mm, "max")

    def biome_label(cell: tuple[int, int]) -> str:
        return config.get(f"tables.biomes.{BIOME_NAME[int(world.biome[cell[1], cell[0]])]}.label").lower()

    text.header("CLIMATE (mean annual)")
    text.para(
        f"Temperature {world.temperature_c[cold[1], cold[0]]:.0f} {unit} ({_position(world, *cold, ascii_only)}, "
        f"{world.elevation_m[cold[1], cold[0]]:,.0f} m) to {world.temperature_c[hot[1], hot[0]]:.0f} {unit} "
        f"({_position(world, *hot, ascii_only)}). Rainfall {world.rain_mm[dry[1], dry[0]]:,.0f} mm/yr "
        f"({biome_label(dry)}) to {world.rain_mm[wet[1], wet[0]]:,.0f} mm/yr ({biome_label(wet)})."
    )


def build_legend(world: World, config: Config, view: View, width: int, ascii_only: bool = False) -> Document:
    """Return the legend and gazetteer for ``view`` of ``world``, wrapped to ``width`` columns."""
    text = _Text(config, width)
    text.header("LEGEND")
    column = int(config.get("render.legend.column_width"))
    per_line = max(1, width // column)
    swatches = _swatches(world, config, view, ascii_only)
    for start in range(0, len(swatches), per_line):
        line: list[Span] = []
        for glyph, fg, bg, label in swatches[start : start + per_line]:
            line += [Span(" "), Span(glyph, fg, bg, True), Span(" " + label.ljust(column - 3), text.text_fg)]
        text.lines.append(line)
    if view.ramp:
        _ramp_bar(text, config, view, ascii_only)
    _geography(text, world, config, ascii_only)
    _climate(text, world, config, ascii_only)
    return text.lines
