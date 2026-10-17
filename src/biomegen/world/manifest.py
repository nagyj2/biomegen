"""What stands in a settlement's site plan: the part of a plan that growth changes.

A site plan is the settlement's ground: streets, plaza, outline, wall and an ordered list of lots, drawn for its
*potential* (see ``POI.potential``) and never for its tier or population. A :class:`SiteManifest` says which of those
lots are built and which centre building stands, so adding a building only fills the next lot and a promotion only
swaps the centre in its reserved plot. Plain data in ``world/``: ``sites/`` reads it and a later simulation writes it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SiteManifest:
    """The state of one settlement's plan.

    Attributes:
        tier: The settlement tier that stands now (a ``tables.tiers`` row); its ``centre`` is the building at the plaza.
        houses: How many house lots are built: the first ``houses`` of the plan's ordered lots.
        specialized: How many specialized slots are built: the first ``specialized`` kinds of the plan's list.
        walled: Whether the wall of the plan's outline stands.
        grown_from: The homestead style (a ``tables.poi_styles`` row) it grew from, whose building is the plan's first
            lot; empty for a settlement that was never a homestead.
    """

    tier: str
    houses: int
    specialized: int
    walled: bool
    grown_from: str = ""
