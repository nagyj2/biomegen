"""Views: an ordered layer list plus an optional tint ramp, read from ``render.views``."""

from __future__ import annotations

from dataclasses import dataclass

from ..config.model import Config


@dataclass(frozen=True)
class View:
    """One way of drawing the world.

    Attributes:
        name: The view's key in ``render.views``.
        layers: Layer names, bottom to top (each must be registered in ``render.layers.LAYERS``).
        tint: The ``render.ramps`` entry the ``tint`` layer applies, or ``""`` for none.
    """

    name: str
    layers: tuple[str, ...]
    tint: str = ""


def view_names(config: Config) -> list[str]:
    """Return the configured view names in config order (the order ``v`` cycles through them)."""
    return list(config.get("render.views"))


def resolve_view(config: Config, name: str) -> View:
    """Build the :class:`View` called ``name``; raise ``KeyError`` listing the valid names if unknown."""
    views = config.get("render.views")
    if name not in views:
        raise KeyError(f"unknown view {name!r}; available: {', '.join(views)}")
    row = views[name]
    return View(name, tuple(row["layers"]), row.get("tint", ""))
