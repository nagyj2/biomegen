"""Tests for the building kinds' plan cells (the reserved roof block)."""

from __future__ import annotations

from biomegen.config import load_config
from biomegen.sites.cells import OUTSIDE_PRIORITY
from biomegen.sites.kinds import cell_name, kind_of_cell, kind_row, roof_cell
from biomegen.world.tile import KIND_ROOF_BASE, KIND_ROOF_SLOTS, Cell

_CONFIG = load_config(None)
_KINDS = sorted(_CONFIG.get("tables.buildings"))


def test_a_kinds_roof_cell_is_the_block_base_plus_its_rank() -> None:
    assert [roof_cell(_CONFIG, kind) for kind in _KINDS] == [
        KIND_ROOF_BASE + kind_row(_CONFIG, kind)["rank"] for kind in _KINDS
    ]


def test_every_roof_cell_lies_in_the_block_clear_of_the_cell_enum() -> None:
    cells = [roof_cell(_CONFIG, kind) for kind in _KINDS]
    assert all(max(int(c) for c in Cell) < cell < KIND_ROOF_BASE + KIND_ROOF_SLOTS for cell in cells)


def test_a_roof_cell_names_its_kind_back() -> None:
    assert [kind_of_cell(_CONFIG, roof_cell(_CONFIG, kind)) for kind in _KINDS] == _KINDS


def test_a_cell_outside_the_block_is_no_kind() -> None:
    assert kind_of_cell(_CONFIG, int(Cell.ROOF)) is None


def test_an_unused_block_cell_is_no_kind() -> None:
    assert kind_of_cell(_CONFIG, KIND_ROOF_BASE + KIND_ROOF_SLOTS - 1) is None


def test_the_legend_names_a_kind_by_its_label_and_an_enum_cell_by_its_name() -> None:
    assert (cell_name(_CONFIG, roof_cell(_CONFIG, "gathering_point")), cell_name(_CONFIG, int(Cell.TABLE))) == (
        "gathering point",
        "table",
    )


def test_a_kind_roof_draws_over_a_street_and_ties_with_the_plain_roof() -> None:
    # A roof of any kind beats a street when a plan is drawn smaller, as the plain roof does.
    house = OUTSIDE_PRIORITY[roof_cell(_CONFIG, "house")]
    assert house == OUTSIDE_PRIORITY[int(Cell.ROOF)] > OUTSIDE_PRIORITY[int(Cell.PATH)]
