"""Shared builders for the site tests: tiny hand-made worlds so each layout is checked on its own."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sites.kinds import roof_cell
from biomegen.world.entities import POI
from biomegen.world.tile import Biome
from biomegen.world.world import World
from tests.render.conftest import make_world

_DEFAULTS = load_config(None)
HOUSE_ROOF = roof_cell(_DEFAULTS, "house")  # the roof cell of a settlement house seen from outside
ROOF_CELLS = sorted(roof_cell(_DEFAULTS, kind) for kind in _DEFAULTS.get("tables.buildings"))  # every kind's roof cell


def roofs(cells: np.ndarray) -> np.ndarray:
    """Return which of ``cells`` are the roof of some building kind."""
    return np.isin(cells, ROOF_CELLS)


@pytest.fixture(scope="module")
def config() -> Config:
    """Defaults with the extent jitter off, so sites have their nominal size."""
    cfg = load_config(None)
    cfg.data["sites"]["size_jitter"] = 0.0
    cfg.data["sites"]["pop_scale"] = [1.0, 1.0]
    return cfg


def flat_world(width: int = 14, height: int = 10, biome: Biome = Biome.GRASS) -> World:
    """A flat land world of one biome."""
    return make_world(width, height, biome)


def add_poi(world: World, kind: str, x: int, y: int, **fields: object) -> POI:
    """Append a POI of ``kind`` at ``(x, y)`` and mark its anchor in ``poi_index``."""
    fields.setdefault("interior_seed", 11 + x * 31 + y)
    poi = POI(kind=kind, x=x, y=y, **fields)  # type: ignore[arg-type]
    world.poi_index[y, x] = len(world.pois)
    world.pois.append(poi)
    return poi
