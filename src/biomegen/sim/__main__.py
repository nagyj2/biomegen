"""``python -m biomegen.sim``: run the simulation headless and print its series and fingerprint.

``scripts/simulate.sh`` is the way in. The world is generated from ``--seed`` with the default config (or
``--config``), hydrated and advanced ``YEARS`` years from the present; the table has a row at the start and every
``--every`` years, and the last line is ``sim <fingerprint>``, the digest of the state it ended on.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Optional

from .. import pipeline
from ..config import load_config
from .fingerprint import sim_fingerprint
from .series import format_rows, run_series


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="biomegen.sim", description=__doc__.splitlines()[0])
    parser.add_argument(
        "years", nargs="?", type=int, default=None, help="Years to simulate (default: sim.series.years)."
    )
    parser.add_argument("--seed", type=int, required=True, help="World seed.")
    parser.add_argument("--every", type=int, default=None, help="Years between rows (default: sim.series.every_years).")
    parser.add_argument("--config", default=None, help="A config file to merge over the defaults.")
    parser.add_argument("--fingerprint-only", action="store_true", help="Print only the sim fingerprint.")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    years = args.years if args.years is not None else int(config.get("sim.series.years"))
    every = args.every if args.every is not None else int(config.get("sim.series.every_years"))
    if years < 0 or every < 1:
        parser.error("years must be 0 or more and --every at least 1")
    world = pipeline.generate(config, args.seed)
    rows, sim = run_series(world, config, world.master_seed, years, every)
    fingerprint = sim_fingerprint(sim.state)
    if args.fingerprint_only:
        print(fingerprint)
    else:
        print(format_rows(rows))
        print(f"sim {fingerprint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
