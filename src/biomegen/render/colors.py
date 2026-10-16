"""Colour maths and the per-biome / per-relief lookup arrays the layers index with.

Everything here is vectorised: colours are ``[..., 3]`` arrays and the lookups are indexed by the
:class:`~biomegen.world.tile.Biome` / :class:`~biomegen.world.tile.Relief` integer, so a layer styles a
whole grid with one fancy-index. Glyphs, colours and the ``sparse`` flag come from the ``tables.biomes``
and ``tables.relief`` rows (``data/biomes.toml``), never from literals here.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Callable

import numpy as np

from ..config.model import Config
from ..world.tile import BIOME_NAME, DRESS_BASE, KIND_ROOF_BASE, Biome, Cell, Relief

RGB = tuple[int, int, int]


def as_colors(value: np.ndarray | RGB) -> np.ndarray:
    """Return ``value`` as a float array (``[..., 3]``) ready for arithmetic."""
    return np.asarray(value, dtype=np.float64)


def to_uint8(colors: np.ndarray) -> np.ndarray:
    """Round and clamp a float colour array into ``uint8``."""
    return np.clip(np.rint(colors), 0, 255).astype(np.uint8)


def scale_colors(colors: np.ndarray | RGB, factor: np.ndarray | float) -> np.ndarray:
    """Multiply colours by ``factor`` (one value per cell or a scalar); returns ``uint8``."""
    factor_array = np.asarray(factor, dtype=np.float64)
    return to_uint8(as_colors(colors) * factor_array[..., np.newaxis])


def mix_colors(a: np.ndarray | RGB, b: np.ndarray | RGB, t: np.ndarray | float) -> np.ndarray:
    """Blend ``a`` toward ``b`` by ``t`` in [0, 1] (per cell or scalar); returns ``uint8``."""
    t_array = np.asarray(t, dtype=np.float64)[..., np.newaxis]
    return to_uint8(as_colors(a) * (1.0 - t_array) + as_colors(b) * t_array)


def ramp_colors(stops: list, values: np.ndarray) -> np.ndarray:
    """Map ``values`` through ``[[value, [r, g, b]], ...]`` stops (ascending), blending linearly.

    Values outside the stops take the first or last colour. Returns ``uint8`` ``[..., 3]``.
    """
    positions = np.array([stop[0] for stop in stops], dtype=np.float64)
    colors = np.array([stop[1] for stop in stops], dtype=np.float64)
    channels = [np.interp(values, positions, colors[:, channel]) for channel in range(3)]
    return to_uint8(np.stack(channels, axis=-1))


@dataclass(frozen=True)
class BiomeStyle:
    """Per-biome arrays indexed by the biome integer."""

    glyph: np.ndarray  # U1 [n]
    fg: np.ndarray  # uint8 [n, 3]
    bg: np.ndarray  # uint8 [n, 3]
    sparse: np.ndarray  # bool [n]: draw the glyph on only some cells
    water: np.ndarray  # bool [n]


@dataclass(frozen=True)
class ReliefStyle:
    """Per-relief arrays indexed by the relief integer (``NONE`` has a blank glyph)."""

    glyph: np.ndarray  # U1 [n]
    fg: np.ndarray  # uint8 [n, 3]


def _glyph(row: dict, ascii_only: bool) -> str:
    text = row["ascii" if ascii_only else "glyph"]
    return text if text else " "


def _build_biome_style(config: Config, ascii_only: bool = False) -> BiomeStyle:
    """Build the biome lookup arrays from ``tables.biomes``."""
    rows = config.get("tables.biomes")
    count = max(int(b) for b in Biome) + 1
    glyph = np.full(count, " ", dtype="U1")
    fg = np.zeros((count, 3), dtype=np.uint8)
    bg = np.zeros((count, 3), dtype=np.uint8)
    sparse = np.zeros(count, dtype=bool)
    water = np.zeros(count, dtype=bool)
    for biome in Biome:
        row = rows[BIOME_NAME[int(biome)]]
        index = int(biome)
        glyph[index] = _glyph(row, ascii_only)
        fg[index] = row["fg"]
        bg[index] = row["bg"]
        sparse[index] = bool(row["sparse"])
        water[index] = bool(row["water"])
    return BiomeStyle(glyph, fg, bg, sparse, water)


def _build_relief_style(config: Config, ascii_only: bool = False) -> ReliefStyle:
    """Build the relief lookup arrays from ``tables.relief``."""
    rows = config.get("tables.relief")
    count = max(int(r) for r in Relief) + 1
    glyph = np.full(count, " ", dtype="U1")
    fg = np.zeros((count, 3), dtype=np.uint8)
    for relief in Relief:
        row = rows[relief.name.lower()]
        index = int(relief)
        glyph[index] = _glyph(row, ascii_only)
        fg[index] = row["fg"]
    return ReliefStyle(glyph, fg)


FACTOR_CODE = {"none": 0, "moisture": 1, "elevation": 2}


@dataclass(frozen=True)
class DetailStyle:
    """Detail-scale floor and clutter lookups (``tables.detail`` and ``tables.detail_relief``).

    Clutter rows are indexed by a *row*: a biome's integer, or ``biome_count + relief`` for a relief class whose
    rocky floor replaces the biome's whole row.

    Attributes:
        floor: Floor glyph per biome (U1 ``[biomes]``).
        relief_floor: Rocky floor glyph per relief class (U1 ``[reliefs]``), blank where there is none.
        relief_rocky: Whether the relief class replaces the biome's detail row (bool ``[reliefs]``).
        clutter_chars: Clutter glyphs per row, padded with blanks (U1 ``[rows, longest]``).
        clutter_len: How many glyphs of ``clutter_chars`` each row uses (int ``[rows]``).
        density: Share of cells carrying clutter per row, before the factor (float ``[rows]``).
        factor: Code of what scales the density per row, see :data:`FACTOR_CODE` (int ``[rows]``).
        biome_count: Number of biomes, the offset of the relief rows.
    """

    floor: np.ndarray
    relief_floor: np.ndarray
    relief_rocky: np.ndarray
    clutter_chars: np.ndarray
    clutter_len: np.ndarray
    density: np.ndarray
    factor: np.ndarray
    biome_count: int


def _build_detail_style(config: Config, ascii_only: bool = False) -> DetailStyle:
    """Build the detail lookup arrays from ``tables.detail`` and ``tables.detail_relief``."""
    suffix = "_ascii" if ascii_only else ""
    biome_rows = config.get("tables.detail")
    relief_rows = config.get("tables.detail_relief")
    biome_count = max(int(b) for b in Biome) + 1
    rows = [biome_rows[BIOME_NAME[int(b)]] for b in sorted(Biome)] + [
        relief_rows[r.name.lower()] for r in sorted(Relief)
    ]
    longest = max(1, max(len(row["clutter" + suffix]) for row in rows))
    clutter_chars = np.full((len(rows), longest), " ", dtype="U1")
    clutter_len = np.zeros(len(rows), dtype=np.int64)
    for index, row in enumerate(rows):
        text = row["clutter" + suffix]
        clutter_chars[index, : len(text)] = list(text)
        clutter_len[index] = len(text)
    floor = np.array([row["floor" + suffix] for row in rows[:biome_count]], dtype="U1")
    relief_floor = np.array([row["floor" + suffix] or " " for row in rows[biome_count:]], dtype="U1")
    relief_rocky = np.array([bool(row["floor" + suffix]) for row in rows[biome_count:]], dtype=bool)
    return DetailStyle(
        floor,
        relief_floor,
        relief_rocky,
        clutter_chars,
        clutter_len,
        np.array([float(row["density"]) for row in rows], dtype=np.float64),
        np.array([FACTOR_CODE[row["factor"]] for row in rows], dtype=np.int64),
        biome_count,
    )


@dataclass(frozen=True)
class InteriorStyle:
    """Per-cell lookups for POI interiors, indexed by the :class:`~biomegen.world.tile.Cell` integer.

    Attributes:
        glyph: Glyph per cell (U1 ``[cells]``), from ``render.interior_glyphs``.
        fg: Glyph colour per cell (uint8 ``[cells, 3]``): the cell colour lightened by ``render.interior_fg_scale``.
        bg: Fill per cell (uint8 ``[cells, 3]``): ``render.interior_palette``, with the bridge cells taking the
            deck and wall colours of ``render.detail_colors``.
    """

    glyph: np.ndarray
    fg: np.ndarray
    bg: np.ndarray


def _build_wall_glyph_table(config: Config, ascii_only: bool = False) -> np.ndarray:
    """Return the 16 line glyphs a thin wall draws, indexed by its wall-neighbour mask (``render.interior_walls``)."""
    table = config.get("render.interior_walls")
    return np.array(table["ascii" if ascii_only else "glyphs"], dtype="U1")


def _build_interior_style(config: Config, ascii_only: bool = False) -> InteriorStyle:
    """Build the interior lookup arrays from ``render.interior_glyphs`` and ``render.interior_palette``.

    Cells named in ``render.interior_subtle`` (rubble and small clutter) take the floor colour, so they barely show;
    those in ``render.interior_on_floor`` (bones) take the floor fill but keep their own colour for the glyph.

    A building kind's roof cell (``KIND_ROOF_BASE`` plus its rank) takes the glyph and colour of its building row, and a
    dress variant with a look of its own (``DRESS_BASE`` plus its rank) those of its ``tables.dress`` variant.

    With ``ascii_only``, ``render.interior_glyphs_ascii`` replaces the glyphs that are not 7-bit (a roof its ``ascii``).
    """
    glyphs = dict(config.get("render.interior_glyphs"))
    if ascii_only:
        glyphs.update(config.get("render.interior_glyphs_ascii"))
    palette = config.get("render.interior_palette")
    detail = config.get("render.detail_colors")
    count = 256  # a plan cell is a uint8: the enum, then the reserved blocks (a kind's roof)
    glyph = np.full(count, "?", dtype="U1")
    fg = np.zeros((count, 3), dtype=np.uint8)
    bg = np.zeros((count, 3), dtype=np.uint8)
    boost = float(config.get("render.interior_fg_scale"))
    subtle = set(config.get("render.interior_subtle"))
    quiet = float(config.get("render.interior_subtle_fg_scale"))
    on_floor = set(config.get("render.interior_on_floor"))
    for cell in Cell:
        name = cell.name.lower()
        index = int(cell)
        glyph[index] = glyphs.get(name, "?")
        if cell == Cell.BRIDGE:
            bg[index], fg[index] = detail["deck_bg"], detail["deck_fg"]
        elif cell == Cell.BRIDGE_WALL:
            bg[index], fg[index] = detail["wall_bg"], detail["wall_fg"]
        elif name in subtle:
            bg[index] = palette["floor"]
            fg[index] = scale_colors(palette["floor"], quiet)
        elif name in on_floor and name in palette:
            bg[index], fg[index] = palette["floor"], palette[name]
        elif name in palette:
            bg[index] = palette[name]
            fg[index] = scale_colors(palette[name], boost)
    for _kind, row in sorted(config.get("tables.buildings").items()):  # a kind's roof cell (see sites/kinds.py)
        index = KIND_ROOF_BASE + int(row["rank"])
        roof = row["roof"]
        glyph[index] = roof["ascii" if ascii_only else "glyph"]
        bg[index] = roof["color"]
        fg[index] = scale_colors(roof["color"], boost)
    for _dress, rows in sorted(config.get("tables.dress").items()):  # a dress variant with a look of its own
        for _name, variant in sorted(rows.get("variants", {}).items()):
            if "cell" in variant:
                continue
            index = DRESS_BASE + int(variant["rank"])
            glyph[index] = variant["ascii" if ascii_only else "glyph"]
            bg[index] = variant["color"]
            fg[index] = scale_colors(variant["color"], boost)
    return InteriorStyle(glyph, fg, bg)


def _read_only(value: Any) -> Any:
    """Mark every array of a cached lookup read-only, so a caller cannot change it under the other frames."""
    arrays = [value] if isinstance(value, np.ndarray) else [getattr(value, f.name) for f in fields(value)]
    for array in arrays:
        if isinstance(array, np.ndarray):
            array.flags.writeable = False
    return value


def _cached(config: Config, name: str, ascii_only: bool, build: Callable[[Config, bool], Any]) -> Any:
    return config.cached((__name__, name, bool(ascii_only)), lambda: _read_only(build(config, ascii_only)))


def biome_style(config: Config, ascii_only: bool = False) -> BiomeStyle:
    """The biome lookup arrays from ``tables.biomes`` (built once per config; read-only)."""
    return _cached(config, "biome_style", ascii_only, _build_biome_style)


def relief_style(config: Config, ascii_only: bool = False) -> ReliefStyle:
    """The relief lookup arrays from ``tables.relief`` (built once per config; read-only)."""
    return _cached(config, "relief_style", ascii_only, _build_relief_style)


def detail_style(config: Config, ascii_only: bool = False) -> DetailStyle:
    """The detail floor and clutter lookups (built once per config; read-only)."""
    return _cached(config, "detail_style", ascii_only, _build_detail_style)


def interior_style(config: Config, ascii_only: bool = False) -> InteriorStyle:
    """The interior lookup arrays (built once per config; read-only)."""
    return _cached(config, "interior_style", ascii_only, _build_interior_style)


def wall_glyph_table(config: Config, ascii_only: bool = False) -> np.ndarray:
    """The 16 thin-wall line glyphs (built once per config; read-only)."""
    return _cached(config, "wall_glyph_table", ascii_only, _build_wall_glyph_table)
