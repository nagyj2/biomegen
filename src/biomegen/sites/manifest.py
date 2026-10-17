"""The manifest of a settlement today: what stands in its plan, worked out from its tier and population.

A site plan is drawn for the settlement's potential and reads only a :class:`~biomegen.world.manifest.SiteManifest`
(which lots are built, which centre stands, whether the wall does). This module is the one place that reads the
settlement's *tier* and *population*: :func:`site_manifest` turns them into the manifest of a generated world, and a
later simulation hands the plan its own manifest instead. :func:`manifest_buildings` lists what a manifest says stands,
without building a plan.
"""

from __future__ import annotations

from typing import Optional

from ..config.model import Config
from ..world.entities import POI
from ..world.manifest import SiteManifest
from ..world.world import World
from .kinds import tier_centre
from .surroundings import settlement_kinds, specialized_slots


def settlement_tier(config: Config, poi: POI) -> str:
    """Return the settlement tier ``poi`` is (a ruin: the tier it was), or an empty string when it is no settlement."""
    tier = poi.ruin_of if poi.kind == "ruin" else poi.kind
    return tier if tier and config.get(f"tables.sites.{tier}.houses", None) is not None else ""


def _pop_share(config: Config, tier: str, pop: int) -> float:
    """Return where ``pop`` lies in ``tier``'s population range, from 0 (its smallest) to 1 (its largest)."""
    low, high = (int(v) for v in config.get(f"tables.tiers.{tier}.pop"))
    return 0.0 if high <= low else min(1.0, max(0.0, (pop - low) / (high - low)))


def site_manifest(config: Config, poi: POI) -> Optional[SiteManifest]:
    """Return the manifest of ``poi`` as its tier and population make it, or None for a POI with no settlement plan.

    ``houses`` is the tier's ``sites.<tier>.houses`` range by the population's place in the tier's range, and
    ``specialized`` the same for its ``specialized`` range; the wall stands when the tier's site row has one. A ruin is
    read as the tier it was, at its peak population. Pure.
    """
    tier = settlement_tier(config, poi)
    if not tier:
        return None
    share = _pop_share(config, tier, poi.pop)
    low, high = (int(v) for v in config.get(f"tables.sites.{tier}.houses"))
    return SiteManifest(
        tier=tier,
        houses=low + round((high - low) * share),
        specialized=specialized_slots(config, tier, poi.pop),
        walled=bool(config.get(f"tables.sites.{tier}.walled", False)),
    )


def manifest_buildings(world: World, config: Config, poi: POI, manifest: SiteManifest) -> list[tuple[str, int]]:
    """Return ``(kind, how many)`` of the buildings ``manifest`` says stand at ``poi``.

    The centre comes first, then each specialized kind (in the order the settlement is chosen to have them, as many as
    ``manifest.specialized`` allows), then the houses. A kind that repeats is counted once, at the place of its first.
    Computed from the manifest alone, so it needs no plan: a plan that cannot place a lot (no room) draws fewer.
    """
    counts: dict[str, int] = {tier_centre(config, manifest.tier): 1}
    for kind in settlement_kinds(world, config, poi)[: manifest.specialized]:
        counts[kind] = counts.get(kind, 0) + 1
    if manifest.houses:
        counts["house"] = counts.get("house", 0) + manifest.houses
    return list(counts.items())
