"""A tiny, generic name->implementation registry.

This is the mechanism that makes every core algorithm **swappable and obvious**. Each family of
interchangeable algorithms (noise backends, biome classifiers, flow models, POI samplers,
pathfinders, interior partitioners, compute backends) owns one ``Registry`` instance. Concrete
implementations attach themselves with the ``@registry.register("name")`` decorator, and callers
look one up by the string they read out of the TOML config, e.g.::

    NOISE_BACKENDS = Registry("noise_backend")

    @NOISE_BACKENDS.register("perlin")
    def perlin_field(...): ...

    backend = NOISE_BACKENDS.get(config.get("terrain.noise_backend"))

Because selection is data-driven, adding a new algorithm never requires editing a call-site: drop a
new function/class, decorate it, and reference its name in config. The algorithm's identity and a
literature reference belong in the implementation's own docstring so it stays self-documenting.
"""

from __future__ import annotations

from typing import Callable, Dict, Generic, Iterable, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    """A named collection of interchangeable implementations keyed by a short string.

    Parameters
    ----------
    family:
        Human-readable name of the algorithm family (used only in error messages), e.g.
        ``"noise_backend"`` or ``"pathfinder"``.
    """

    def __init__(self, family: str) -> None:
        self.family = family
        # Maps the public selector string (as it appears in config) to its implementation.
        self._items: Dict[str, T] = {}

    def register(self, name: str) -> Callable[[T], T]:
        """Return a decorator that records ``impl`` under ``name`` and returns it unchanged.

        Registering the same ``name`` twice is a programming error (two implementations claiming the
        same selector) and raises immediately so the collision is caught at import time.
        """

        def _decorator(impl: T) -> T:
            if name in self._items:
                raise ValueError(f"{self.family!r} registry already has an implementation named {name!r}")
            self._items[name] = impl
            return impl

        return _decorator

    def add(self, name: str, impl: T) -> None:
        """Imperatively register ``impl`` under ``name`` (for when a decorator is inconvenient)."""
        if name in self._items:
            raise ValueError(f"{self.family!r} registry already has an implementation named {name!r}")
        self._items[name] = impl

    def get(self, name: str) -> T:
        """Look up an implementation by ``name``; raise a helpful error if it is unknown."""
        try:
            return self._items[name]
        except KeyError:
            available = ", ".join(sorted(self._items)) or "<none registered>"
            raise KeyError(f"unknown {self.family} {name!r}; available: {available}") from None

    def has(self, name: str) -> bool:
        """Return whether ``name`` is registered (used to gracefully skip optional backends)."""
        return name in self._items

    def names(self) -> Iterable[str]:
        """Return the registered selector strings in sorted order (stable for display/tests)."""
        return sorted(self._items)
