"""Wars, peace, pacts, battles and the falls they cause, tracked through time.

Every faction (a living realm, or a fallen realm while it lived) has a **strength** that starts from its area (or a
draw for a fallen realm) and moves with what happens to it: each battle won multiplies it by ``1 +
history.victory_gain``, each lost one by ``1 - history.defeat_loss`` (never below ``history.min_strength``). The
timeline is planned first, then played in year order so every result sees the strengths of that moment:

1. **Relations.** Each relation of two independent powers may have an older, ended war first (``past_war_chance``,
   lasting ``past_war_years``, when the pair share a border): its battles, then a ``peace`` won by the likelier side.
   The relation itself (a war that is still going, a rivalry or a treaty) begins at a year drawn anywhere after that,
   so wars and pacts can be old or new.
2. **Fallen realms.** Each fights a few wars (``fallen_wars``) against the nearest living realms that exist at the
   time, one decisive battle each at its ruins. A realm whose strength falls below ``fall_strength`` after a lost
   battle is conquered a few years later (``fall_delay_years``); the others fall at their natural year.
3. **Battles** along a war's front are won with a chance proportional to strength.

Every draw is a ``history`` sub-stream keyed on the relation, battle or fallen realm, so the result does not depend on
dict or set order, and nothing here writes a per-tile array.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...config.model import Config
from ...util import rng
from ...world.world import World
from ..civilization.diplomacy import front_cells
from .ledger import Ledger
from .places import nearest_settlement
from .rulers import StyleTimeline, style_at

Faction = tuple[str, int]  # ("realm", realm id) or ("fallen", fallen realm id)
REALM, FALLEN = "realm", "fallen"
_ORDER = {"war": 0, "battle": 1, "peace": 2}  # the order of steps in one year


@dataclass(frozen=True)
class _Step:
    """One battle or peace to play at ``year``, between factions ``a`` and ``b`` (``a`` first in realm pairs)."""

    year: int
    kind: str  # "war" (the start of a war with a fallen realm), "battle" or "peace"
    a: Faction
    b: Faction
    key: tuple  # labels of this step's rng stream
    location: tuple[int, int] = (-1, -1)
    tags: tuple[str, ...] = ()  # a "war" step's tags


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
    ) -> None:
        self.steps.append(_Step(min(year, self.span), kind, a, b, key, location, tags))

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
            self._settle(winner, loser)
            if step.kind == "peace":
                self.ledger.add(
                    step.year, "peace", "peace", step.key, self.seed, realm_ids=[winner[1], loser[1]], tags=("ended",)
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
                tags=("front",),
            )
            return
        realm = step.a if step.a[0] == REALM else step.b
        fallen = step.a if step.a[0] == FALLEN else step.b
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
            tags=("ruins", "won_by_fallen" if winner == fallen else "won_by_realm"),
        )
        floor = float(self.config.get("history.fall_strength"))
        if loser == fallen and self.strength[fallen] < floor:
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


def _plan_relations(timeline: _Timeline) -> None:
    """Plan each relation: an optional older war with its battles and peace, then the relation itself."""
    world, config, seed, span = timeline.world, timeline.config, timeline.seed, timeline.span
    gap = int(config.get("history.min_gap_years"))
    rate = float(config.get("history.battles_per_100km_front"))
    chance = float(config.get("history.past_war_chance"))
    len_lo, len_hi = (int(v) for v in config.get("history.past_war_years"))
    for index, relation in enumerate(world.relations):
        stream = rng.derive(seed, "history", "relation", index)
        roll_past, roll_length, roll_start, roll_main, roll_side = (stream.random() for _ in range(5))
        pair = [relation.a, relation.b]
        first = min(max(world.realms[relation.a].founded, world.realms[relation.b].founded) + gap, span)
        cells = front_cells(world, relation.a, relation.b).tolist() if relation.border_km > 0 else []
        battles = max(1, round(relation.border_km / 100.0 * rate)) if cells else 0
        main_first = first
        if cells and roll_past < chance:
            length = len_lo + int(roll_length * (len_hi - len_lo + 1))
            latest = span - length - gap
            if latest >= first:
                start = _draw_year(roll_start, first, latest)
                end = start + length
                attacker, defender = (relation.a, relation.b) if roll_side < 0.5 else (relation.b, relation.a)
                timeline.ledger.add(
                    start, "war", "war_ended", ("past", index), seed, realm_ids=[attacker, defender], tags=("ended",)
                )
                for number in range(battles):
                    step_stream = rng.derive(seed, "history", "place", "past", index, number)
                    y, x = divmod(cells[step_stream.randrange(len(cells))], world.width)
                    year = _draw_year(step_stream.random(), start, end)
                    timeline.plan(year, "battle", (REALM, attacker), (REALM, defender), ("past", index, number), (x, y))
                timeline.plan(end, "peace", (REALM, attacker), (REALM, defender), ("past", index))
                main_first = min(end + gap, span)
        year = _draw_year(roll_main, main_first, span)
        if relation.kind == "war":
            attacker = relation.attacker if relation.attacker >= 0 else relation.a
            defender = relation.b if attacker == relation.a else relation.a
            timeline.ledger.add(
                year,
                "war",
                "war",
                (index,),
                seed,
                realm_ids=[attacker, defender],
                poi_ids=[relation.claim_poi] if relation.claim_poi >= 0 else [],
                tags=("ongoing",),
            )
            for number in range(round(relation.border_km / 100.0 * rate) if cells else 0):
                step_stream = rng.derive(seed, "history", "place", index, number)
                y, x = divmod(cells[step_stream.randrange(len(cells))], world.width)
                battle_year = _draw_year(step_stream.random(), year, span)
                timeline.plan(battle_year, "battle", (REALM, attacker), (REALM, defender), (index, number), (x, y))
        elif relation.kind == "rivalry":
            timeline.ledger.add(year, "rivalry", "rivalry", (index,), seed, realm_ids=pair, tags=("rivalry",))
        else:
            timeline.ledger.add(
                year, "treaty", f"treaty_{relation.kind}", (index,), seed, realm_ids=pair, tags=(relation.kind,)
            )


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


def derive(
    world: World, config: Config, seed: int, span: int, ledger: Ledger, styles: dict[int, StyleTimeline] | None = None
) -> None:
    """Add the war, peace, battle, rivalry, treaty and fall events of the world to ``ledger``."""
    timeline = _Timeline(world, config, seed, span, ledger, styles)
    _plan_relations(timeline)
    _plan_fallen_wars(timeline)
    timeline.play()
