"""Shared builders for render tests: tiny hand-made worlds so each layer is checked on its own."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.world.tile import Biome
from biomegen.world.world import World


@pytest.fixture(scope="module")
def config() -> Config:
    return load_config(None)


def make_world(width: int = 6, height: int = 3, biome: Biome = Biome.GRASS, elevation_m: float = 100.0) -> World:
    """Return a ``width x height`` world of one biome at one elevation (seed 1)."""
    world = World(width, height, 1)
    world.biome[:] = int(biome)
    world.elevation_m[:] = elevation_m
    return world
