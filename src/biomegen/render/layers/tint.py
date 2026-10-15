"""The tint layer: recolours the fill from a data ramp (elevation, temperature, rainfall, ...) or by realm."""

from __future__ import annotations

import numpy as np

from ...world.tile import Relief
from ..colors import mix_colors, ramp_colors, scale_colors
from ..grid import CellGrid
from . import LAYERS, LayerContext


def realm_colors(ctx: LayerContext) -> np.ndarray:
    """Realm colours as ``uint8 [n + 1, 3]``, indexed by realm id; index -1 (wild) is mid grey."""
    colors = [realm.color for realm in ctx.world.realms] + [(128, 128, 128)]
    return np.array(colors, dtype=np.uint8)


def _realm_tint(ctx: LayerContext, grid: CellGrid) -> None:
    """Mix each land cell toward its realm's colour (``render.realm_tint``) and flatten unclaimed land to a dull grey.

    Water keeps the terrain's colours; glyphs (relief, clutter) are left as they are.
    """
    cfg = ctx.config.get("render.realm_tint")
    realm = ctx.realm
    grey = grid.bg.astype(np.float64).mean(axis=-1, keepdims=True)
    muted = mix_colors(grid.bg, np.broadcast_to(grey, grid.bg.shape), float(cfg["desaturate"]))
    claimed = ctx.land & (realm >= 0)
    wild = ctx.land & (realm < 0)
    dull = np.clip(grey * float(cfg["wild_scale"]) + float(cfg["wild_offset"]), 0, 255)
    grid.put(claimed, bg=mix_colors(muted, realm_colors(ctx)[realm], float(cfg["mix"])))
    grid.put(wild, bg=np.broadcast_to(np.rint(dull).astype(np.uint8), grid.bg.shape))


@LAYERS.register("tint")
def tint_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Replace the fill with the colour of the view's ramp (``render.ramps.<view.tint>``).

    The ramp's options decide the rest: ``shade`` hillshades land, ``water_scale`` / ``water_color`` restyle water
    cells, and glyphs are blanked unless ``keep_relief`` keeps the relief glyphs or ``keep_clutter`` (zoom and local
    only) keeps the clutter glyphs, both dimmed against the new fill. A realm-tinted (political) view mixes realm
    colours into the land instead and keeps the glyphs. A view with no tint leaves the grid unchanged.
    """
    if not ctx.view.tint:
        return
    if ctx.view.political:
        _realm_tint(ctx, grid)
        return
    ramp = ctx.config.get(f"render.ramps.{ctx.view.tint}")
    inside = ctx.sampler.inside
    values = ctx.sampler.bilinear(getattr(ctx.world, ramp["field"]).astype(np.float64))
    bg = ramp_colors(ramp["stops"], values)
    water = inside & ~ctx.land
    if ramp.get("shade"):
        bg = np.where(ctx.land[..., np.newaxis], scale_colors(bg, ctx.shade), bg)
    if "water_scale" in ramp:
        bg = np.where(water[..., np.newaxis], scale_colors(bg, float(ramp["water_scale"])), bg)
    if "water_color" in ramp:
        bg = np.where(water[..., np.newaxis], np.asarray(ramp["water_color"], dtype=np.uint8), bg)

    kept = ctx.land & (ctx.relief != int(Relief.NONE)) if ramp.get("keep_relief") else np.zeros_like(inside)
    if ramp.get("keep_clutter") and ctx.sampler.detailed:
        kept = kept | (ctx.land & (grid.glyph != ctx.detail_floor) & (grid.glyph != " "))
    glyph = np.where(kept, grid.glyph, " ")
    fg = np.where(kept[..., np.newaxis], scale_colors(bg, float(ctx.config.get("render.tint_relief_fg"))), grid.fg)
    grid.put(inside, glyph=glyph, fg=fg, bg=bg)
