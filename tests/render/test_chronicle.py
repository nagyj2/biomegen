"""Tests for the coloured chronicle document: columns, kind colours and name colours."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.render.backends.plain import to_plain
from biomegen.render.chronicle import chronicle_document, legible
from biomegen.world.chronicle import chronicle_text
from biomegen.world.entities import ChronicleEvent, Realm
from biomegen.world.world import World


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module")
def generated(cfg: Config) -> World:
    return pipeline.generate(cfg, 42)


def _tiny() -> World:
    world = World(4, 4, 9)
    world.island_name = "Testisle"
    world.year = 500
    world.realms = [Realm(id=0, kind="major", name="Kingdom of A", color=(200, 20, 20))]
    event = ChronicleEvent(0, 100, "founding", [0], text="Kingdom of A is founded.", refs=[(0, 12, "realm", 0)])
    world.chronicle = [event]
    return world


def test_the_plain_text_of_the_document_is_the_plain_output(generated: World, cfg: Config) -> None:
    # Colour only decorates: stripped of it, the document is the same text.
    assert to_plain(chronicle_document(generated, cfg)) == chronicle_text(generated).rstrip()


def test_the_year_column_is_right_aligned_to_five(cfg: Config) -> None:
    row = chronicle_document(_tiny(), cfg)[2]
    assert row[0].text == "  100"


def test_the_kind_has_its_colour(cfg: Config) -> None:
    row = chronicle_document(_tiny(), cfg)[2]
    assert (row[2].text.strip(), row[2].fg) == ("founding", tuple(cfg.get("history.colors.founding")))


def test_a_realm_name_takes_the_realms_own_colour(cfg: Config) -> None:
    row = chronicle_document(_tiny(), cfg)[2]
    name = next(span for span in row if span.text == "Kingdom of A")
    assert name.fg == legible((200, 20, 20))


def test_text_outside_a_name_is_uncoloured(cfg: Config) -> None:
    row = chronicle_document(_tiny(), cfg)[2]
    assert row[-1].text == " is founded." and row[-1].fg is None


def test_a_dark_realm_colour_is_lifted_to_be_legible() -> None:
    red, green, blue = legible((20, 20, 60))
    assert 0.299 * red + 0.587 * green + 0.114 * blue >= 129


def test_a_light_realm_colour_is_unchanged() -> None:
    assert legible((240, 200, 100)) == (240, 200, 100)


def test_other_names_use_the_fixed_colour_of_their_kind(cfg: Config) -> None:
    world = _tiny()
    world.chronicle[0].refs = [(0, 12, "poi", 0)]
    name = next(span for span in chronicle_document(world, cfg)[2] if span.text == "Kingdom of A")
    assert name.fg == tuple(cfg.get("history.colors.poi"))


def test_every_event_is_a_row_under_the_title(generated: World, cfg: Config) -> None:
    assert len(chronicle_document(generated, cfg)) == 2 + len(generated.chronicle)
