"""Tests for the pure episode functions generation and a simulation share (``pipeline/story/episodes.py``)."""

from __future__ import annotations

from biomegen.config import load_config
from biomegen.pipeline.story import episodes

CONFIG = load_config(None)
NEUTRAL = {name: 0.5 for name in ("aggression", "greed", "trust", "expansionism", "caution")}
WARLIKE = {**NEUTRAL, "aggression": 1.0, "caution": 0.0}
GENTLE = {**NEUTRAL, "aggression": 0.0, "caution": 1.0}
GREEDY = {**NEUTRAL, "greed": 1.0, "trust": 0.8}


def test_tilt_of_neutral_rulers_is_one() -> None:
    assert episodes.tilt(CONFIG, {"aggression": 2.0, "greed": -1.0}, NEUTRAL, NEUTRAL) == 1.0


def test_tilt_follows_the_mean_of_the_two_rulers() -> None:
    # Aggression 1.0 and 0.0 average to the neutral 0.5, so the pair has no tilt.
    assert episodes.tilt(CONFIG, {"aggression": 2.0}, WARLIKE, GENTLE) == 1.0


def test_tilt_never_falls_below_the_floor() -> None:
    floor = float(CONFIG.get("history.episodes.tilt_floor"))
    assert episodes.tilt(CONFIG, {"aggression": -10.0}, WARLIKE, WARLIKE) == floor


def test_a_missing_ruler_counts_as_neutral() -> None:
    assert episodes.tilt(CONFIG, {"aggression": 5.0}, {}, {}) == 1.0


def test_pair_class_is_major_only_for_two_majors() -> None:
    assert [episodes.pair_class("major", "major"), episodes.pair_class("major", "tribal")] == [
        "major_pair",
        "other_pair",
    ]


def test_war_pull_grows_with_the_border() -> None:
    assert episodes.war_pull(CONFIG, 800.0, 1.0, 1.0) > episodes.war_pull(CONFIG, 200.0, 1.0, 1.0)


def test_war_pull_grows_with_the_strength_gap() -> None:
    assert episodes.war_pull(CONFIG, 400.0, 3.0, 1.0) > episodes.war_pull(CONFIG, 400.0, 1.0, 1.0)


def test_war_pull_keeps_the_border_within_its_range() -> None:
    assert episodes.war_pull(CONFIG, 1e9, 1.0, 1.0) == float(CONFIG.get("history.episodes.border_range")[1])


def test_only_a_bordering_pair_can_fight() -> None:
    weights = episodes.kind_weights(CONFIG, "major_pair", NEUTRAL, NEUTRAL, bordering=False)
    assert weights["war"] == 0.0


def test_a_pair_with_no_wars_left_cannot_fight() -> None:
    weights = episodes.kind_weights(CONFIG, "major_pair", NEUTRAL, NEUTRAL, bordering=True, wars_left=0)
    assert weights["war"] == 0.0


def test_aggressive_rulers_make_war_likelier_than_cautious_ones() -> None:
    warlike = episodes.kind_weights(CONFIG, "major_pair", WARLIKE, WARLIKE, bordering=True)["war"]
    gentle = episodes.kind_weights(CONFIG, "major_pair", GENTLE, GENTLE, bordering=True)["war"]
    assert warlike > gentle


def test_greedy_trusting_rulers_make_trade_likelier() -> None:
    greedy = episodes.kind_weights(CONFIG, "major_pair", GREEDY, GREEDY, bordering=True)["trade"]
    plain = episodes.kind_weights(CONFIG, "major_pair", NEUTRAL, NEUTRAL, bordering=True)["trade"]
    assert greedy > plain


def test_draw_kind_follows_the_weights() -> None:
    # The first half of the roll's range falls on the first weighted kind, the rest on the second.
    weights = {"war": 1.0, "rivalry": 0.0, "alliance": 1.0, "trade": 0.0}
    assert [episodes.draw_kind(weights, 0.25), episodes.draw_kind(weights, 0.75)] == ["war", "alliance"]


def test_draw_kind_with_no_weight_is_none() -> None:
    assert episodes.draw_kind({"war": 0.0, "trade": 0.0}, 0.5) is None


def test_episode_years_stay_in_the_row_range() -> None:
    low, high = CONFIG.get("tables.episode_kinds.alliance.years")
    years = [episodes.episode_years(CONFIG, "alliance", NEUTRAL, NEUTRAL, roll / 10) for roll in range(10)]
    assert low <= min(years) and max(years) <= high


def test_a_present_episode_is_drawn_from_the_age_range() -> None:
    low, high = CONFIG.get("tables.episode_kinds.war.present_age")
    age = episodes.episode_years(CONFIG, "war", NEUTRAL, NEUTRAL, 0.99, present=True)
    assert low <= age <= high


def test_cautious_rulers_shorten_a_war() -> None:
    long = episodes.episode_years(CONFIG, "war", WARLIKE, WARLIKE, 0.5)
    short = episodes.episode_years(CONFIG, "war", GENTLE, GENTLE, 0.5)
    assert short < long


def test_a_near_equal_peace_is_a_truce() -> None:
    assert episodes.truce_terms(CONFIG, 1.0, 0.9) == "truce"


def test_a_lopsided_peace_is_a_peace() -> None:
    assert episodes.truce_terms(CONFIG, 3.0, 1.0) == "peace"


def test_a_war_of_two_small_powers_is_minor() -> None:
    assert episodes.war_salience(CONFIG, "tribal", "city_state") == "minor"


def test_a_war_with_a_major_realm_is_major() -> None:
    assert episodes.war_salience(CONFIG, "major", "tribal") == "major"


def test_a_lasting_relation_is_never_a_one_off_purchase() -> None:
    assert episodes.deal_weights(CONFIG, NEUTRAL, NEUTRAL, lasting=True)["buy_once"] == 0.0


def test_a_past_trade_may_be_a_one_off_purchase() -> None:
    assert episodes.deal_weights(CONFIG, NEUTRAL, NEUTRAL, lasting=False)["buy_once"] > 0.0


def test_draw_deal_falls_back_to_a_swap() -> None:
    assert episodes.draw_deal({"swap": 0.0, "buy_once": 0.0, "buy_ongoing": 0.0}, 0.5) == "swap"


SUPPLY_RICH_IN_WOOD = {"food": 0.2, "wood": 0.7, "stone": 0.0, "metal": 0.0, "luxury": 0.0}
SUPPLY_RICH_IN_METAL = {"food": 0.2, "wood": 0.0, "stone": 0.0, "metal": 0.6, "luxury": 0.1}


def test_a_swap_gives_each_side_its_own_surplus() -> None:
    goods = episodes.pact_goods(CONFIG, 0, 1, SUPPLY_RICH_IN_WOOD, SUPPLY_RICH_IN_METAL, "swap")
    assert (goods.give, goods.get) == ("wood", "metal")


def test_a_swap_never_trades_a_resource_for_itself() -> None:
    same = {"food": 0.5, "wood": 0.1, "stone": 0.1, "metal": 0.1, "luxury": 0.1}
    goods = episodes.pact_goods(CONFIG, 0, 1, same, same, "swap")
    assert goods.give != goods.get


def test_a_swap_never_trades_money() -> None:
    goods = episodes.pact_goods(CONFIG, 0, 1, SUPPLY_RICH_IN_WOOD, SUPPLY_RICH_IN_METAL, "swap")
    assert "money" not in (goods.give, goods.get)


def test_a_purchase_is_made_by_the_side_that_lacks_the_good() -> None:
    # Realm 1 is the one with the metal, so realm 0 buys it.
    goods = episodes.pact_goods(CONFIG, 0, 1, SUPPLY_RICH_IN_WOOD, SUPPLY_RICH_IN_METAL, "buy_once")
    assert (goods.give, goods.buyer) == ("wood", 1)


def test_a_swap_has_no_buyer() -> None:
    goods = episodes.pact_goods(CONFIG, 0, 1, SUPPLY_RICH_IN_WOOD, SUPPLY_RICH_IN_METAL, "swap")
    assert goods.buyer == -1


def test_a_good_match_makes_a_larger_deal() -> None:
    small = episodes.deal_volume(CONFIG, "swap", 0.1, NEUTRAL, NEUTRAL)
    large = episodes.deal_volume(CONFIG, "swap", 0.9, NEUTRAL, NEUTRAL)
    assert (small, large) == ("small", "large")


def test_greedy_rulers_strike_a_larger_deal() -> None:
    plain = episodes.deal_volume(CONFIG, "swap", 0.4, NEUTRAL, NEUTRAL)
    greedy = episodes.deal_volume(CONFIG, "swap", 0.4, GREEDY, GREEDY)
    assert (plain, greedy) == ("steady", "large")
