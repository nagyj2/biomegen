"""The series: a row of counts describing a simulation at a moment, and a run that samples it over the years.

``scripts/simulate.sh`` prints these rows to show a simulation's course (realms, people, wars, stock) and the
fingerprint it ends on. :data:`COLUMNS` is the one list of columns: a later phase appends the columns it wants to watch.
Everything here only reads the world and the state.
"""

from __future__ import annotations

from collections import Counter

from ..config.model import Config
from ..world.entities import POI, RELATION_KINDS
from ..world.sim_state import SimState
from ..world.world import World
from .engine import Simulation

COLUMNS: tuple[str, ...] = (
    "date",
    "tick",
    "powers",
    "factions",
    "settlements",
    "population",
    "wars",
    "rivalries",
    "alliances",
    "trades",
    "stock",
)
_KIND_COLUMN = {"war": "wars", "rivalry": "rivalries", "alliance": "alliances", "trade": "trades"}

Row = dict[str, int | str]


def _poi(world: World, state: SimState, index: int) -> POI:
    """The POI at ``index`` as ``World.place`` numbers them, then the ones the simulation minted."""
    standing = len(world.pois) + len(world.vanished)
    return world.place(index) if index < standing else state.pois[index - standing]


def series_row(world: World, config: Config, state: SimState) -> Row:
    """Return the row for ``state``: the date and tick, then the powers (factions with no liege), all factions, the
    settlements (civilized places), the people the factions count, each kind of relation and the stock held."""
    year, month = state.moment(int(config.get("history.months_per_year")))
    kinds = Counter(relation.kind for relation in state.relations.values())
    row: Row = {
        "date": f"{year}/{month:02d}",
        "tick": state.tick,
        "powers": sum(1 for faction in state.factions.values() if faction.liege < 0),
        "factions": len(state.factions),
        "settlements": sum(1 for index in state.places if _poi(world, state, index).civilized),
        "population": sum(faction.pop for faction in state.factions.values()),
        "stock": sum(sum(place.stock.values()) for place in state.places.values()),
    }
    row.update({_KIND_COLUMN[kind]: kinds[kind] for kind in RELATION_KINDS})
    return {column: row[column] for column in COLUMNS}


def run_series(world: World, config: Config, seed: int, years: int, every: int) -> tuple[list[Row], Simulation]:
    """Simulate ``years`` years from the present and return a row at the start and after every ``every`` years (and at
    the end), with the finished :class:`Simulation`."""
    sim = Simulation(world, config, seed)
    per_year = int(config.get("history.months_per_year")) * sim.state.ticks_per_month
    rows = [series_row(world, config, sim.state)]
    done = 0
    while done < years:
        step = min(every, years - done)
        sim.advance(step * per_year)
        done += step
        rows.append(series_row(world, config, sim.state))
    return rows, sim


def format_rows(rows: list[Row]) -> str:
    """Return ``rows`` as an aligned text table under a header of :data:`COLUMNS`."""
    widths = {column: max([len(column), *(len(str(row[column])) for row in rows)]) for column in COLUMNS}
    lines = [" ".join(f"{column:>{widths[column]}}" for column in COLUMNS)]
    lines += [" ".join(f"{row[column]!s:>{widths[column]}}" for column in COLUMNS) for row in rows]
    return "\n".join(lines)
