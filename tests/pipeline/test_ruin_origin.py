"""Tests for ``pois.ruin_origin``: the tier a ruin was and the population it peaked at."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.config.population import tier_pop_range
from biomegen.pipeline import pois

SEED = 11


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


def test_the_same_cell_gives_the_same_origin(cfg: Config) -> None:
    assert pois.ruin_origin(cfg, SEED, 5, 6) == pois.ruin_origin(cfg, SEED, 5, 6)


def test_a_fixed_tier_is_the_origin(cfg: Config) -> None:
    assert pois.ruin_origin(cfg, SEED, 5, 6, tier="capital")[0] == "capital"


def test_the_origins_follow_their_weights(cfg: Config) -> None:
    # Hamlets and villages weigh 7 of 10.5, cities and capitals 1.5 of 10.5 in the default row.
    origins = [pois.ruin_origin(cfg, SEED, x, 0)[0] for x in range(600)]
    small = sum(o in ("hamlet", "village") for o in origins) / len(origins)
    big = sum(o in ("city", "capital") for o in origins) / len(origins)
    assert 0.58 < small < 0.75 and 0.08 < big < 0.2


def test_the_holding_weights_never_draw_a_capital_or_hamlet(cfg: Config) -> None:
    origins = {pois.ruin_origin(cfg, SEED, x, 0, weights="holding_origins")[0] for x in range(200)}
    assert origins == {"village", "town", "city"}


def test_the_population_comes_from_the_tiers_range(cfg: Config) -> None:
    lo, hi = tier_pop_range(cfg, "capital")
    assert all(lo <= pois.ruin_origin(cfg, SEED, x, 1, tier="capital")[1] <= hi for x in range(50))
