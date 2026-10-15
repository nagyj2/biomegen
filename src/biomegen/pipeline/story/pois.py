"""Stage: pois - the wild and history-made points of interest, placed after the history stage.

The stage runs once realms, diplomacy and the chronicle exist, so a POI can follow the world's history and take its
realm by grid lookup. History placement (ruins, battlefields, watchtowers, shrines: :mod:`.poi_rules`) comes first;
the location pass (:func:`biomegen.pipeline.pois.place_by_location`) then fills the rest by score. With
``history.start = "dawn"`` there are no realms and no events, so only the kinds whose ``source`` is "both" are placed,
by location: a few ruins, towers and dungeons already stand at year 0.
"""

from __future__ import annotations

from ...config.model import Config
from ...world.world import World
from .. import pois


def run(world: World, config: Config, seed: int) -> None:
    """Place the POIs of the world, mutating ``world`` in place."""
    dawn = config.get("history.start") == "dawn"
    pois.place_by_location(world, config, seed, ("both",) if dawn else ("location", "both"))
