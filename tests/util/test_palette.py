"""Tests for the distinct-colour helpers: CIELAB distance, bright hue candidates and the farthest pick."""

from __future__ import annotations

import pytest

from biomegen.util import palette


def test_white_is_lightness_100() -> None:
    assert palette.lab((255, 255, 255))[0] == pytest.approx(100.0, abs=0.1)


def test_black_is_lightness_0() -> None:
    assert palette.lab((0, 0, 0))[0] == pytest.approx(0.0, abs=0.1)


def test_a_colour_is_no_distance_from_itself() -> None:
    assert palette.distance((200, 40, 40), (200, 40, 40)) == 0.0


def test_distance_is_symmetric() -> None:
    assert palette.distance((200, 40, 40), (40, 40, 200)) == pytest.approx(
        palette.distance((40, 40, 200), (200, 40, 40))
    )


def test_red_is_further_from_green_than_from_a_slightly_different_red() -> None:
    assert palette.distance((200, 40, 40), (40, 200, 40)) > palette.distance((200, 40, 40), (210, 50, 50))


def test_candidates_are_bright_enough() -> None:
    colours = palette.hue_candidates(0.9, 0.95, 72, 0.0, 130.0)
    assert colours and all(palette.luma(c) >= 130.0 for c in colours)


def test_a_dark_hue_is_dropped_from_the_candidates() -> None:
    # Pure blue at this saturation is too dark to read, so fewer than all the hues survive.
    assert len(palette.hue_candidates(0.9, 0.95, 72, 0.0, 130.0)) < 72


def test_the_candidates_start_at_the_given_hue() -> None:
    assert palette.hue_candidates(1.0, 1.0, 4, 0.0, 0.0)[0] == (255, 0, 0)


def test_the_farthest_candidate_is_the_one_least_like_what_is_taken() -> None:
    assert palette.farthest([(250, 20, 20), (20, 250, 20)], [(240, 30, 30)]) == (20, 250, 20)


def test_with_nothing_taken_the_first_candidate_is_picked() -> None:
    assert palette.farthest([(1, 2, 3), (4, 5, 6)], []) == (1, 2, 3)


def test_farthest_picks_are_repeatable() -> None:
    candidates = palette.hue_candidates(0.8, 0.9, 36, 0.1, 100.0)
    taken = [(128, 128, 128)]
    assert palette.farthest(candidates, taken) == palette.farthest(candidates, taken)
