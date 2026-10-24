"""Tests for the ``sim`` config section: its defaults and the validation of the numbers the schedule divides by."""

from __future__ import annotations

from typing import Any

import pytest

from biomegen.config.defaults import get_defaults
from biomegen.config.validate import ConfigError, validate
from biomegen.util import rng


def _with(**changes: Any) -> dict[str, Any]:
    config = get_defaults()
    config["sim"].update(changes)
    return config


def test_shipped_sim_defaults_validate() -> None:
    validate(get_defaults())


def test_the_sim_rng_label_is_registered() -> None:
    assert "sim" in rng.LABELS


def test_the_two_cadences_are_economy_and_strategy() -> None:
    assert set(get_defaults()["sim"]["cadence"]) == {"economy", "strategy"}


@pytest.mark.parametrize("value", [0, -3, 2.5, True])
def test_ticks_per_month_must_be_a_whole_number_of_at_least_one(value: Any) -> None:
    with pytest.raises(ConfigError, match=r"sim\.ticks_per_month"):
        validate(_with(ticks_per_month=value))


def test_a_cadence_jitter_must_be_shorter_than_its_period() -> None:
    # A jitter as long as the period could put the next check at or before the last one.
    config = get_defaults()
    config["sim"]["cadence"]["economy"]["jitter_ticks"] = config["sim"]["ticks_per_month"]
    with pytest.raises(ConfigError, match=r"sim\.cadence\.economy\.jitter_ticks"):
        validate(config)


def test_a_cadence_period_must_be_at_least_one_month() -> None:
    config = get_defaults()
    config["sim"]["cadence"]["strategy"]["months"] = 0
    with pytest.raises(ConfigError, match=r"sim\.cadence\.strategy"):
        validate(config)


@pytest.mark.parametrize("value", [0, -0.1, 1.5])
def test_max_check_share_must_be_in_zero_to_one(value: float) -> None:
    with pytest.raises(ConfigError, match=r"sim\.max_check_share"):
        validate(_with(max_check_share=value))


@pytest.mark.parametrize("key", ["ticks_per_second", "max_frame_seconds"])
def test_playback_numbers_must_be_positive(key: str) -> None:
    config = get_defaults()
    config["sim"]["playback"][key] = 0
    with pytest.raises(ConfigError, match=rf"sim\.playback\.{key}"):
        validate(config)


def test_series_years_must_be_at_least_one() -> None:
    config = get_defaults()
    config["sim"]["series"]["every_years"] = 0
    with pytest.raises(ConfigError, match=r"sim\.series\.every_years"):
        validate(config)
