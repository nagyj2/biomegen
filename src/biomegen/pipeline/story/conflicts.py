"""Wars, peace, pacts, battles and the falls they cause, tracked through time.

Every faction (a living realm, or a fallen realm while it lived) has a **strength** that starts from its area (or a
draw for a fallen realm) and moves with what happens to it: each battle won multiplies it by ``1 +
history.victory_gain``, each lost one by ``1 - history.defeat_loss`` (never below ``history.min_strength``). The
timeline is planned first, then played in year order so every result sees the strengths of that moment:

1. **Episodes.** Each pair of independent powers has a run of episodes (a war, a rivalry, an alliance, a trade) drawn
   backwards from today's relation (:mod:`.pair_timeline`, weighed by :mod:`.episodes`): a war with its battles and a
   ``peace`` or ``truce`` that ends it, a pact or rivalry with the event that ends it, a trade as a swap, a standing
   supply or a one-off purchase. Today's relation is the last episode and never moves.
2. **Fallen realms.** Each fights a few wars (``fallen_wars``) against the nearest living realms that exist at the
   time, one decisive battle each at its ruins. A realm whose strength falls below ``fall_strength`` after a lost
   battle is conquered a few years later (``fall_delay_years``); the others fall at their natural year.
3. **Battles** along a war's front are won with a chance proportional to strength. A battle that changes a border is
   tagged ``decisive``: the last battle of an older war before its peace, and the battle in which a fallen realm is
   conquered (a battlefield may mark it).

Every draw is a ``history`` sub-stream keyed on the relation, battle or fallen realm, so the result does not depend on
dict or set order, and nothing here writes a per-tile array.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from ...config.model import Config
from ...util import rng
from ...world.entities import NO_LOCATION, Episode, Relation
from ...world.resources import realm_supply
from ...world.world import World
from ..civilization import diplomacy
from . import episodes, pair_timeline, secession
from .founding import add_founding, add_settling
from .ledger import Ledger
from .places import nearest_settlement
from .rulers import StyleTimeline, style_at

Faction = tuple[str, int]  # ("realm", realm id) or ("fallen", fallen realm id)
REALM, FALLEN = "realm", "fallen"
_ORDER = {"war": 0, "battle": 1, "peace": 2, "secession": 3}  # the order of steps in one year


@dataclass(frozen=True)
class _Step:
    """One battle or peace to play at ``year``, between factions ``a`` and ``b`` (``a`` first in realm pairs)."""

    year: int
    kind: str  # "war" (the start of a war with a fallen realm), "battle" or "peace"
    a: Faction
    b: Faction
    key: tuple  # labels of this step's rng stream
    location: tuple[int, int] = (-1, -1)
    tags: tuple[str, ...] = ()  # a "war" step's tags, or the tags a realm-pair "battle" adds (``decisive``)
    salience: str = (
        "major"  # of the war it belongs to: only its decisive battle and its peace take it, the rest are minor
    )
    episode: int = -1  # index into World.episodes of the ended episode the step belongs to, -1 for none


class _Timeline:
    """The steps planned so far and the strengths and deaths while they are played."""

    def __init__(
        self,
        world: World,
        config: Config,
        seed: int,
        span: int,
        ledger: Ledger,
        styles: dict[int, StyleTimeline] | None = None,
    ) -> None:
        self.world, self.config, self.seed, self.span, self.ledger = world, config, seed, span, ledger
        self.styles = styles or {}
        self.steps: list[_Step] = []
        self.dead: set[Faction] = set()
        self.secessions = 0  # how many have happened so far, against history.secession.max_per_world
        realms = world.realms
        mean_area = sum(r.area_km2 for r in realms) / len(realms) if realms else 1.0
        lo, hi = (float(v) for v in config.get("history.start_strength_range"))
        self.strength: dict[Faction, float] = {
            (REALM, r.id): min(hi, max(lo, r.area_km2 / mean_area if mean_area else 1.0)) for r in realms
        }
        flo, fhi = (float(v) for v in config.get("history.fallen_strength"))
        for fallen in world.fallen_realms:
            self.strength[(FALLEN, fallen.id)] = rng.derive(seed, "history", "strength", fallen.id).uniform(flo, fhi)

    def plan(
        self,
        year: int,
        kind: str,
        a: Faction,
        b: Faction,
        key: tuple,
        location: tuple[int, int] = (-1, -1),
        tags: tuple[str, ...] = (),
        salience: str = "major",
        episode: int = -1,
    ) -> None:
        self.steps.append(_Step(min(year, self.span), kind, a, b, key, location, tags, salience, episode))

    def _result(self, step: _Step) -> tuple[Faction, Faction]:
        """Return ``(winner, loser)`` of ``step``: ``a`` wins with a chance proportional to its strength."""
        sa, sb = self._odds(step.a, step.year), self._odds(step.b, step.year)
        stream = rng.derive(self.seed, "history", step.kind, *step.key)
        return (step.a, step.b) if stream.random() < sa / (sa + sb) else (step.b, step.a)

    def _odds(self, faction: Faction, year: int) -> float:
        """A faction's strength in ``year`` times its ruler's style multiplier then (a fallen realm has no style)."""
        if faction[0] != REALM or faction[1] not in self.styles:
            return self.strength[faction]
        style = style_at(self.styles[faction[1]], year)
        return self.strength[faction] * float(self.config.get(f"tables.ruling_styles.{style}.strength_mul"))

    def _settle(self, winner: Faction, loser: Faction) -> None:
        gain, loss = float(self.config.get("history.victory_gain")), float(self.config.get("history.defeat_loss"))
        floor = float(self.config.get("history.min_strength"))
        self.strength[winner] *= 1.0 + gain
        self.strength[loser] = max(floor, self.strength[loser] * (1.0 - loss))

    def play(self) -> None:
        """Play every step in year order, then let each surviving fallen realm fall at its natural year."""
        for step in sorted(self.steps, key=lambda s: (s.year, _ORDER[s.kind])):
            if step.kind == "secession":
                (self._defection if step.key[0] == "defection" else self._offshoot)(step)
                continue
            if step.a in self.dead or step.b in self.dead:
                continue
            if step.kind == "war":
                realm = step.a if step.a[0] == REALM else step.b
                fallen = step.a if step.a[0] == FALLEN else step.b
                self.ledger.add(
                    step.year,
                    "war",
                    "war_fallen",
                    step.key,
                    self.seed,
                    realm_ids=[realm[1]],
                    fallen_ids=[fallen[1]],
                    location=step.location,
                    tags=step.tags,
                )
                continue
            winner, loser = self._result(step)
            terms = episodes.truce_terms(self.config, self._odds(step.a, step.year), self._odds(step.b, step.year))
            self._settle(winner, loser)
            if step.kind == "peace":
                self.ledger.add(
                    step.year,
                    "peace",
                    "peace_truce" if terms == "truce" else "peace",
                    step.key,
                    self.seed,
                    realm_ids=[winner[1], loser[1]],
                    tags=("ended", *(("truce",) if terms == "truce" else ())),
                    salience=step.salience,
                    episode=step.episode,
                )
            else:
                self._battle(step, winner, loser)
        for record in self.world.fallen_realms:
            if (FALLEN, record.id) not in self.dead:
                self.ledger.add(
                    record.fell,
                    "fall",
                    "fall",
                    (record.id,),
                    self.seed,
                    fallen_ids=[record.id],
                    location=record.location,
                    near_poi=nearest_settlement(self.world, self.config, *record.location),
                )

    def _offshoot(self, step: _Step) -> None:
        """Check whether realm ``step.b`` left realm ``step.a`` in the year of its founding.

        The odds are the offshoot :func:`~.secession.form_chance` times the offshoot score, which reads the parent's
        strength at this moment (against the mean of the living realms), and at most ``max_per_world`` happen. If it
        does the realm's founding is a ``secession`` event, its seat older than the realm; if not, it is founded as any
        realm is.
        """
        world, config, seed = self.world, self.config, self.seed
        parent, child = world.realms[step.a[1]], world.realms[step.b[1]]
        mean = sum(self.strength[(REALM, r.id)] for r in world.realms) / len(world.realms)
        score = secession.offshoot_score(world, config, child, parent, step.year, self.strength[step.a] / mean)
        roll = rng.derive(seed, "history", "secession", "check", "offshoot", child.id).random()
        chance = secession.form_chance(config, "offshoot")
        if self.secessions >= int(config.get("history.secession.max_per_world")) or roll >= chance * score:
            add_founding(world, config, seed, self.ledger, child)
            return
        self.secessions += 1
        child.origin, child.parent = "offshoot", parent.id
        seat = world.pois[child.seat_poi] if child.seat_poi >= 0 else None
        if seat is not None:  # the seat stood under the parent before the break
            first = parent.founded + int(config.get("history.min_gap_years"))
            if child.founded > first:
                roll = rng.derive(seed, "history", "secession", "seat", child.id).random()
                seat.founded = first + int(roll * (child.founded - first))
        tag = secession.relation_tag(world, config, parent, child)
        self.ledger.add(
            step.year,
            "secession",
            f"secession_offshoot_{tag}",
            ("offshoot", child.id),
            seed,
            realm_ids=[child.id, parent.id],
            poi_ids=[child.seat_poi] if seat is not None else [],
            location=(seat.x, seat.y) if seat is not None else NO_LOCATION,
            tags=(child.kind, "offshoot", tag, *(("capital",) if seat is not None and seat.kind == "capital" else ())),
        )

    def _defection(self, step: _Step) -> None:
        """Check whether settlement ``step.key[1]`` left realm ``step.a`` for its holder ``step.b`` in ``step.year``.

        Odds as for an offshoot, with the defection :func:`~.secession.form_chance` and score (the old owner's strength
        then). If it did, the settlement was settled for the realm it left and a ``secession`` tagged ``defection``
        follows; if not, it was settled for its holder as any settlement is.
        """
        world, config, seed = self.world, self.config, self.seed
        index = int(step.key[1])
        old, holder, town = world.realms[step.a[1]], world.realms[step.b[1]], world.pois[index]
        mean = sum(self.strength[(REALM, r.id)] for r in world.realms) / len(world.realms)
        score = secession.defection_score(world, config, town, old, holder, step.year, self.strength[step.a] / mean)
        roll = rng.derive(seed, "history", "secession", "check", "defection", index).random()
        chance = secession.form_chance(config, "defection")
        if self.secessions >= int(config.get("history.secession.max_per_world")) or roll >= chance * score:
            add_settling(world, config, seed, self.ledger, index, holder.id)
            return
        self.secessions += 1
        add_settling(world, config, seed, self.ledger, index, old.id)  # it was the old owner's town to begin with
        tag = secession.relation_tag(world, config, old, holder)
        self.ledger.add(
            step.year,
            "secession",
            f"secession_defection_{tag}",
            ("defection", index),
            seed,
            realm_ids=[holder.id, old.id],
            poi_ids=[index],
            location=(town.x, town.y),
            tags=(town.kind, "defection", tag),
        )

    def _battle(self, step: _Step, winner: Faction, loser: Faction) -> None:
        x, y = step.location
        near = nearest_settlement(self.world, self.config, x, y)
        if step.a[0] == REALM and step.b[0] == REALM:
            self.ledger.add(
                step.year,
                "battle",
                "battle",
                step.key,
                self.seed,
                realm_ids=[winner[1], loser[1]],
                location=step.location,
                near_poi=near,
                tags=("front", *step.tags),
                salience=step.salience if "decisive" in step.tags else "minor",
                episode=step.episode,
            )
            return
        realm = step.a if step.a[0] == REALM else step.b
        fallen = step.a if step.a[0] == FALLEN else step.b
        floor = float(self.config.get("history.fall_strength"))
        conquering = loser == fallen and self.strength[fallen] < floor  # the battle that ends the fallen realm
        self.ledger.add(
            step.year,
            "battle",
            "battle",
            step.key,
            self.seed,
            realm_ids=[realm[1]],
            fallen_ids=[fallen[1]],
            location=step.location,
            near_poi=near,
            tags=(
                "ruins",
                "won_by_fallen" if winner == fallen else "won_by_realm",
                *(("decisive",) if conquering else ()),
            ),
            salience="major" if conquering else "minor",
        )
        if conquering:
            self._conquer(step, realm, fallen)

    def _conquer(self, step: _Step, realm: Faction, fallen: Faction) -> None:
        """The fallen realm lost its last battle: it falls to ``realm`` a few years on."""
        lo, hi = (int(v) for v in self.config.get("history.fall_delay_years"))
        stream = rng.derive(self.seed, "history", "conquered", fallen[1])
        year = min(step.year + stream.randint(lo, hi), self.span - int(self.config.get("history.fallen_min_years_ago")))
        year = max(year, step.year)
        record = self.world.fallen_realms[fallen[1]]
        record.fell = year
        self.dead.add(fallen)
        self.ledger.add(
            year,
            "fall",
            "fall_conquered",
            (fallen[1],),
            self.seed,
            realm_ids=[realm[1]],
            fallen_ids=[fallen[1]],
            location=record.location,
            near_poi=nearest_settlement(self.world, self.config, *record.location),
            tags=("conquered",),
        )


def _draw_year(roll: float, first: int, last: int) -> int:
    """Map ``roll`` in [0, 1) to a year in ``first..last`` (``first`` when the range is empty)."""
    return first + int(roll * max(0, last - first + 1))


_TREATY_ROWS = {
    "alliance": "treaty_alliance",
    "swap": "treaty_trade",
    "buy_once": "treaty_purchase",
    "buy_ongoing": "treaty_supply",
}


def _treaty_row(span: pair_timeline.Span) -> str:
    """The chronicle row of the event that starts a treaty episode (an alliance, or a trade by its deal)."""
    return _TREATY_ROWS[span.deal.name if span.deal is not None else span.kind]


def _episode_of(
    world: World,
    config: Config,
    seed: int,
    pair: tuple[int, int],
    span: pair_timeline.Span,
    km: float,
    front: np.ndarray,
) -> Episode:
    """Record the ended episode ``span`` of ``pair`` in ``World.episodes`` and return it, with its reason worded.

    A war is worded without a reason (its start event has none); a purchase has none either.
    """
    deal = span.deal
    episode = Episode(
        a=pair[0],
        b=pair[1],
        kind=span.kind,
        border_km=km,
        attacker=span.attacker,
        deal=deal.name if deal else "",
        goods=list(deal.goods) if deal else [],
        buyer=deal.buyer if deal else -1,
        volume=deal.volume if deal else "",
        start=span.start,
        end=span.end,
    )
    if span.kind != "war" and (deal is None or deal.name == "swap"):
        stream = rng.derive(seed, "history", "reason", pair[0], pair[1], span.number)
        diplomacy.word_relation(world, config, episode, stream, front if km > 0 else None)
    world.episodes.append(episode)
    return episode


def _plan_war(
    timeline: _Timeline,
    pair: tuple[int, int],
    span: pair_timeline.Span,
    relation: Relation | None,
    index: int,
    km: float,
    front: np.ndarray,
) -> None:
    """Add a war episode's start event and plan its battles and, if it ended, its peace.

    Battles fall at random places of the front and years of the war (at least one when the pair has a front), the last
    battle before the peace of an ended war decisive. Only the decisive battle and the peace take the war's salience.
    """
    world, config, seed = timeline.world, timeline.config, timeline.seed
    a, b = pair
    attacker = span.attacker if span.attacker >= 0 else a
    defender = b if attacker == a else a
    salience = episodes.war_salience(config, world.realms[a].kind, world.realms[b].kind)
    key = ("episode", a, b, span.number)
    if span.present:
        assert relation is not None
        timeline.ledger.add(
            span.start,
            "war",
            "war",
            key,
            seed,
            realm_ids=[attacker, defender],
            poi_ids=[relation.claim_poi] if relation.claim_poi >= 0 else [],
            tags=("ongoing",),
            salience=salience,
        )
    else:
        timeline.ledger.add(
            span.start,
            "war",
            "war_ended",
            key,
            seed,
            realm_ids=[attacker, defender],
            tags=("ended",),
            salience=salience,
            episode=index,
        )
    cells = front.tolist()
    rate = float(config.get("history.battles_per_100km_front"))
    fought = []
    for number in range(max(1, round(km / 100.0 * rate)) if cells and rate > 0.0 else 0):
        stream = rng.derive(seed, "history", "place", a, b, span.number, number)
        y, x = divmod(cells[stream.randrange(len(cells))], world.width)
        fought.append((_draw_year(stream.random(), span.start, span.end), number, (x, y)))
    decisive = max(fought)[1] if fought and not span.present else -1  # the last battle before the peace
    for year, number, place in fought:
        tags = ("decisive",) if number == decisive else ()
        timeline.plan(
            year, "battle", (REALM, attacker), (REALM, defender), (*key, number), place, tags, salience, index
        )
    if not span.present:
        timeline.plan(span.end, "peace", (REALM, attacker), (REALM, defender), key, salience=salience, episode=index)


def _plan_commerce(timeline: _Timeline, pair: tuple[int, int], span: pair_timeline.Span, index: int) -> None:
    """Add the events of a rivalry, alliance or trade episode: its start and, unless a one-off or today's, its end."""
    config, seed = timeline.config, timeline.seed
    a, b = pair
    key = ("episode", a, b, span.number)
    row = config.get(f"tables.episode_kinds.{span.kind}")
    if span.kind == "rivalry":
        kind, start_row, tags = "rivalry", "rivalry", ("rivalry",)
    else:
        kind, start_row = "treaty", _treaty_row(span)
        tags = (span.kind, *((span.deal.name,) if span.deal else ()))
    timeline.ledger.add(
        span.start, kind, start_row, key, seed, realm_ids=[a, b], tags=tags, salience=row["salience"], episode=index
    )
    lasts = span.deal is None or span.deal.name != "buy_once"
    if not span.present and lasts:
        timeline.ledger.add(
            span.end,
            kind,
            f"{start_row}_ended",
            (*key, "end"),
            seed,
            realm_ids=[a, b],
            tags=(*tags, "ended"),
            salience=row["end_salience"],
            episode=index,
        )


def _plan_episodes(timeline: _Timeline) -> None:
    """Draw the episodes of every pair of independent powers that share a border or hold a relation; add their events.

    Today's relation is the last episode of its pair: it keeps its kind, front and claim, takes its deal if it is a
    trade, and its events carry no episode index (they read the relation).
    """
    world, config, seed, span = timeline.world, timeline.config, timeline.seed, timeline.span
    supply = realm_supply(world, config)
    fronts = diplomacy.power_fronts(world)
    present = {(r.a, r.b): r for r in world.relations}
    for pair in sorted(set(fronts) | set(present)):
        relation = present.get(pair)
        km, front = fronts.get(pair, (0.0, np.empty(0, dtype=np.int64)))
        if relation is not None:
            km = relation.border_km
        strengths = (timeline.strength[(REALM, pair[0])], timeline.strength[(REALM, pair[1])])
        for run in pair_timeline.plan_pair(world, config, seed, span, pair, relation, km, strengths, supply):
            if run.present:
                assert relation is not None
                index = -1
                if run.deal is not None:
                    relation.deal, relation.goods = run.deal.name, list(run.deal.goods)
                    relation.buyer, relation.volume = run.deal.buyer, run.deal.volume
            else:
                index = len(world.episodes)
                _episode_of(world, config, seed, pair, run, km, front)
            if run.kind == "war":
                _plan_war(timeline, pair, run, relation, index, km, front)
            else:
                _plan_commerce(timeline, pair, run, index)


def _plan_fallen_wars(timeline: _Timeline) -> None:
    """Plan each fallen realm's wars against the nearest living realms that exist when the war is fought."""
    world, config, seed = timeline.world, timeline.config, timeline.seed
    gap = int(config.get("history.min_gap_years"))
    lo, hi = (int(v) for v in config.get("history.fallen_wars"))
    near = int(config.get("history.fallen_neighbours"))
    seated = [r for r in world.realms if r.seat_poi >= 0]
    for fallen in world.fallen_realms:
        stream = rng.derive(seed, "history", "fallen-wars", fallen.id)
        wars = stream.randint(lo, hi)
        km = {
            r.id: world.scale.distance_km(*fallen.location, world.pois[r.seat_poi].x, world.pois[r.seat_poi].y)
            for r in seated
        }
        neighbours = sorted(seated, key=lambda r: (km[r.id], r.id))[:near]
        for number in range(wars):
            rolls = [stream.random() for _ in range(3)]
            first, last = fallen.founded + gap, fallen.fell - gap
            if not neighbours or last < first:
                continue
            year = _draw_year(rolls[0], first, last)
            realm = neighbours[int(rolls[1] * len(neighbours))]
            if realm.founded + gap > year:
                continue
            fallen_attacks = rolls[2] < 0.5
            key = ("fallen", fallen.id, number)
            tags = ("ended", "attacker:fallen" if fallen_attacks else "attacker:realm")
            timeline.plan(year, "war", (REALM, realm.id), (FALLEN, fallen.id), key, fallen.location, tags)
            timeline.plan(year, "battle", (REALM, realm.id), (FALLEN, fallen.id), key, fallen.location)


def _plan_offshoots(timeline: _Timeline, offshoots: Mapping[int, int]) -> None:
    """Plan the check of every realm that may have left an older one, at the year it was founded."""
    for child_id, parent_id in sorted(offshoots.items()):
        child = timeline.world.realms[child_id]
        timeline.plan(child.founded, "secession", (REALM, parent_id), (REALM, child_id), ("offshoot", child_id))


def _plan_defections(timeline: _Timeline, defections: Mapping[int, tuple[int, int]]) -> None:
    """Plan the check of every settlement that may have left an older realm for its holder, in its drawn year."""
    for index, (old_id, year) in sorted(defections.items()):
        holder_id = timeline.world.pois[index].realm_id
        timeline.plan(year, "secession", (REALM, old_id), (REALM, holder_id), ("defection", index))


def derive(
    world: World,
    config: Config,
    seed: int,
    span: int,
    ledger: Ledger,
    styles: dict[int, StyleTimeline] | None = None,
    offshoots: Mapping[int, int] | None = None,
    secessions_made: int = 0,
    defections: Mapping[int, tuple[int, int]] | None = None,
) -> None:
    """Add the war, peace, battle, rivalry, treaty and fall events of the world to ``ledger``.

    ``offshoots`` maps a realm that may have left an older one to that parent: each gets its founding (or secession)
    event here, from a check at its founding year. ``secessions_made`` counts the clean splits already decided, which
    use up the per-world cap first. ``defections`` maps a settlement that may have changed sides to the realm it would
    have left and the year; each is checked there, and gets its ``settling`` event from the outcome.
    """
    timeline = _Timeline(world, config, seed, span, ledger, styles)
    timeline.secessions = secessions_made
    _plan_episodes(timeline)
    _plan_fallen_wars(timeline)
    _plan_offshoots(timeline, offshoots or {})
    _plan_defections(timeline, defections or {})
    timeline.play()
