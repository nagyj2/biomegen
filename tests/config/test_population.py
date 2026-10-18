"""Tests for the population scale: one knob, applied after every draw."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.population import pop_scale, scaled_people, tier_pop_range


def test_the_default_scale_raises_the_numbers() -> None:
    assert pop_scale(load_config(None)) > 1.0


def test_a_scale_of_one_leaves_the_numbers_as_the_tables_give_them() -> None:
    config = load_config(None)
    config.data["settlements"]["pop_scale"] = 1.0
    assert (scaled_people(config, 80), tier_pop_range(config, "village")) == (80, (80, 1200))


def test_a_population_is_the_draw_times_the_scale_rounded_half_up() -> None:
    config = load_config(None)
    config.data["settlements"]["pop_scale"] = 1.5
    assert [scaled_people(config, n) for n in (10, 11, 3)] == [15, 17, 5]


def test_the_scale_never_reorders_two_whole_populations() -> None:
    config = load_config(None)
    config.data["settlements"]["pop_scale"] = 1.5
    scaled = [scaled_people(config, n) for n in range(2000)]
    assert all(a < b for a, b in zip(scaled, scaled[1:], strict=False))


def test_the_scaled_range_of_a_tier_is_its_table_range_times_the_scale() -> None:
    config = load_config(None)
    config.data["settlements"]["pop_scale"] = 2.0
    assert tier_pop_range(config, "town") == (3000, 16000)


@pytest.mark.parametrize("seed", [42, 7])
def test_scaling_the_people_changes_no_part_of_the_world(seed: int) -> None:
    # Populations are drawn on the table ranges and scaled afterwards, so the map is the same at any scale.
    plain = load_config(None)
    plain.data["settlements"]["pop_scale"] = 1.0
    scaled = load_config(None)
    scaled.data["settlements"]["pop_scale"] = 2.5
    assert pipeline.generate(plain, seed).fingerprint() == pipeline.generate(scaled, seed).fingerprint()


def test_every_population_of_a_world_follows_the_scale() -> None:
    plain = load_config(None)
    plain.data["settlements"]["pop_scale"] = 1.0
    doubled = load_config(None)
    doubled.data["settlements"]["pop_scale"] = 2.0
    base, twice = pipeline.generate(plain, 42), pipeline.generate(doubled, 42)
    assert [p.pop * 2 for p in base.pois] == [p.pop for p in twice.pois]
