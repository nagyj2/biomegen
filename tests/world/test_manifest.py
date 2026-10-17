"""Tests for the site manifest: the state of one settlement's plan."""

from __future__ import annotations

import dataclasses

import pytest

from biomegen.world.manifest import SiteManifest


def test_a_manifest_does_not_change_once_made() -> None:
    manifest = SiteManifest("village", 5, 1, False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        manifest.houses = 6  # type: ignore[misc]


def test_a_settlement_that_was_never_a_homestead_has_no_origin() -> None:
    assert SiteManifest("village", 5, 1, False).grown_from == ""
