"""Views: ordered layer lists (one per scale family) plus an optional tint ramp, read from ``render.views``."""

from __future__ import annotations

from dataclasses import dataclass

from ..config.model import Config
from ..config.validate import REALM_TINT


@dataclass(frozen=True)
class View:
    """One way of drawing the world.

    Attributes:
        name: The view's key in ``render.views``.
        layers: Layer names for the map scale, bottom to top (each must be registered in
            ``render.layers.LAYERS``).
        tint: The ``render.ramps`` entry the ``tint`` layer applies, ``"realm"`` for realm colours, or ``""`` for none.
        detail_layers: Layer names for the zoom and local scales; empty means the map list is used there too.
    """

    name: str
    layers: tuple[str, ...]
    tint: str = ""
    detail_layers: tuple[str, ...] = ()

    @property
    def ramp(self) -> str:
        """The ``render.ramps`` entry of a data view, or ``""`` when the view has none (untinted or realm-tinted)."""
        return "" if self.tint == REALM_TINT else self.tint

    @property
    def political(self) -> bool:
        """Whether the view tints land by realm."""
        return self.tint == REALM_TINT

    def layers_for(self, detailed: bool) -> tuple[str, ...]:
        """Return the layer list for a detail scale (``detailed``) or the map scale."""
        return self.detail_layers if detailed and self.detail_layers else self.layers


def view_names(config: Config) -> list[str]:
    """Return the configured view names in config order (the order ``v`` cycles through them)."""
    return list(config.get("render.views"))


def resolve_view(config: Config, name: str) -> View:
    """Build the :class:`View` called ``name``; raise ``KeyError`` listing the valid names if unknown."""
    views = config.get("render.views")
    if name not in views:
        raise KeyError(f"unknown view {name!r}; available: {', '.join(views)}")
    row = views[name]
    return View(name, tuple(row["layers"]), row.get("tint", ""), tuple(row.get("detail_layers", ())))
