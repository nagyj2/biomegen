"""Tests for resolving views from config."""

from __future__ import annotations

import pytest

from biomegen.render.views import resolve_view, view_names


def test_resolve_view_reads_layers_and_tint(config) -> None:
    view = resolve_view(config, "elevation")
    assert view.layers[0] == "terrain" and view.tint == "elevation"


def test_unknown_view_lists_the_valid_names(config) -> None:
    with pytest.raises(KeyError, match="terrain"):
        resolve_view(config, "nope")


def test_view_names_follow_config_order(config) -> None:
    assert view_names(config)[0] == "terrain"
