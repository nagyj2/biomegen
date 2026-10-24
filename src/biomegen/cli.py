"""biomegen - application entry point.

Run the CLI application with::

    uv run biomegen [--seed N] [--config path.toml] [--width W] [--height H]
                    [--noise-backend {perlin,value,opensimplex}]
                    [--headless] [--view NAME] [--scale {map,zoom,local,site}] [--at X,Y] [--floor N]
                    [--labels {all,cities,none}]
                    [--color {auto,truecolor,256,none}] [--ascii] [--no-legend] [--save FILE] [--html FILE]
                    [--chronicle] [--chronicle-format {text,json}] [--kind KINDS] [--from-year Y] [--to-year Y]
                    [--realm NAME] [--search TEXT] [--no-pager] [--start {present,dawn}] [--sim] [--color-test]

This launcher wires together the three top-level concerns and nothing else:
    1. parse CLI arguments,
    2. load + override configuration and resolve the effective seed,
    3. hand off to the interactive explorer, a static map, or a headless stats dump.

The heavy lifting lives in the importable :mod:`biomegen` package.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from biomegen.config import Config, load_config
from biomegen.util import rng


def _build_parser() -> argparse.ArgumentParser:
    # Import registries now (they populate at module import time) so choices reflect installed backends.
    from biomegen.util.noise import NOISE_BACKENDS

    noise_choices = list(NOISE_BACKENDS.names())

    parser = argparse.ArgumentParser(
        prog="biomegen",
        description="Procedurally generate and explore a realistic island in your terminal.",
    )
    parser.add_argument(
        "--seed",
        default=None,
        help="Master seed (int, 0xHEX, or any string). Overrides config; absent/0 picks a random seed and echoes it.",
    )
    parser.add_argument(
        "--config", default=None, help="Path to a TOML config file (sparse overlay on built-in defaults)."
    )
    parser.add_argument("--width", type=int, default=None, help="Override world width (tiles).")
    parser.add_argument("--height", type=int, default=None, help="Override world height (tiles).")
    parser.add_argument(
        "--noise-backend",
        choices=noise_choices,
        default=None,
        help=(
            f"Terrain noise algorithm. Overrides config terrain.noise_backend. "
            f"Choices: {', '.join(noise_choices)}. "
            f"Default: perlin (guaranteed deterministic across platforms)."
        ),
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Generate the world and print summary statistics without launching the UI.",
    )
    parser.add_argument("--style", default=None, help="Landmass style (a tables.styles row, or 'seed' to draw one).")
    parser.add_argument(
        "--size-km", type=_parse_size_km, default=None, metavar="WxH", help="Map extent in km, east-west x north-south."
    )
    parser.add_argument(
        "--lat", type=float, default=None, help="Latitude of the map centre in degrees (north positive)."
    )
    parser.add_argument(
        "--lon", type=float, default=None, help="Longitude of the map centre in degrees (east positive)."
    )
    parser.add_argument(
        "--view",
        default=None,
        help="Print a static map of this render.views entry (terrain, political, elevation, ...) and exit.",
    )
    parser.add_argument(
        "--scale",
        choices=("map", "zoom", "local", "site"),
        default=None,
        help=(
            "Draw a magnified part of the world (zoom or local), or with --at the site of a point of interest "
            "(site: a plan cell per terminal cell, centred on the tile and clipped to the terminal), instead of the "
            "whole map; implies --view terrain."
        ),
    )
    parser.add_argument(
        "--at",
        type=_parse_tile,
        default=None,
        metavar="X,Y",
        help="World tile to centre a zoom or local view on, or that holds the site to draw (default: map middle).",
    )
    parser.add_argument(
        "--floor", type=int, default=0, help="Floor of a multi-floor structure to draw (0 is the ground)."
    )
    parser.add_argument("--labels", choices=("all", "cities", "none"), default="all", help="Which names to draw.")
    parser.add_argument(
        "--color",
        choices=("auto", "truecolor", "256", "none"),
        default="auto",
        help="Colour mode of static output (auto detects the terminal).",
    )
    parser.add_argument("--ascii", action="store_true", help="Use only 7-bit ASCII glyphs.")
    parser.add_argument("--no-legend", action="store_true", help="Print only the map, without the legend.")
    parser.add_argument(
        "--save",
        metavar="FILE",
        default=None,
        help="Also save the static map; the suffix picks .txt, .html, .svg or .png.",
    )
    parser.add_argument(
        "--html", metavar="FILE", default=None, help="Also save a coloured HTML copy of the static map."
    )
    parser.add_argument(
        "--chronicle",
        action="store_true",
        help=(
            "Show the world's chronicle and exit: an interactive pager (scroll, filter, search) on a terminal, "
            "else printed (the seed line goes to stderr)."
        ),
    )
    parser.add_argument(
        "--history",
        nargs="?",
        type=int,
        const=-1,
        default=None,
        metavar="YEAR",
        help=(
            "Open the history viewer and exit: the political map at a moment of the past, the powers then and the "
            "chronicle beside it. It opens at the map at the end of YEAR (the first change when no year is given)."
        ),
    )
    parser.add_argument(
        "--sim",
        action="store_true",
        help=(
            "Run the simulation from the present while exploring (explorer only): the sim date shows in the panel; "
            "p pauses it, + and - change its speed, r restarts it from the seed."
        ),
    )
    parser.add_argument(
        "--chronicle-format",
        choices=("text", "json"),
        default="text",
        help="Format of --chronicle: readable text, or JSON with the realms and places its ids name.",
    )
    parser.add_argument(
        "--kind",
        type=_parse_kinds,
        action=_AppendKinds,
        default=(),
        metavar="KINDS",
        help="Keep chronicle events of these kinds (comma separated or repeated, e.g. war,battle).",
    )
    parser.add_argument(
        "--salience",
        choices=("major", "all"),
        default="major",
        help="Chronicle events to keep: major only (default), or all (major and minor).",
    )
    parser.add_argument("--from-year", type=int, default=None, help="Keep chronicle events in this year or later.")
    parser.add_argument("--to-year", type=int, default=None, help="Keep chronicle events in this year or earlier.")
    parser.add_argument(
        "--realm",
        default="",
        metavar="NAME",
        help=(
            "Keep chronicle events involving a realm, fallen realm, ruler or settlement whose name contains NAME "
            "(any case); | is or, & is and."
        ),
    )
    parser.add_argument(
        "--search",
        default="",
        metavar="TEXT",
        help=(
            "Keep chronicle events whose year, kind or text contains TEXT (any case; | is or, & is and); "
            "the pager highlights it."
        ),
    )
    parser.add_argument(
        "--no-pager",
        action="store_true",
        help="Print --chronicle even on a terminal, instead of opening the pager.",
    )
    parser.add_argument(
        "--start",
        choices=("present", "dawn"),
        default=None,
        help="Overrides history.start: a finished world with a history, or a young unsettled one at year 0.",
    )
    parser.add_argument("--color-test", action="store_true", help="Show colour and glyph test swatches and exit.")
    return parser


class _AppendKinds(argparse.Action):
    """Collect the kinds of every ``--kind`` use into one tuple."""

    def __call__(self, parser, namespace, values, option_string=None):  # type: ignore[no-untyped-def]
        setattr(namespace, self.dest, (*getattr(namespace, self.dest), *values))


def _parse_kinds(text: str) -> tuple[str, ...]:
    """Parse ``war,battle`` for ``--kind``, checking each against the event kinds."""
    from biomegen.world.entities import EVENT_KINDS

    kinds = tuple(part.strip() for part in text.split(",") if part.strip())
    unknown = [kind for kind in kinds if kind not in EVENT_KINDS]
    if not kinds or unknown:
        raise argparse.ArgumentTypeError(
            f"unknown kind {', '.join(unknown) or repr(text)}; available: {', '.join(EVENT_KINDS)}"
        )
    return kinds


def _parse_size_km(text: str) -> tuple[float, float]:
    """Parse ``6000x3000`` (km, east-west x north-south) for ``--size-km``."""
    try:
        east_west, north_south = text.lower().replace("km", "").split("x")
        return float(east_west), float(north_south)
    except ValueError:
        raise argparse.ArgumentTypeError("size must look like 6000x3000 (width x height in km)") from None


def _parse_tile(text: str) -> tuple[int, int]:
    """Parse ``X,Y`` (world tile column and row) for ``--at``."""
    try:
        x, y = text.split(",")
        return int(x), int(y)
    except ValueError:
        raise argparse.ArgumentTypeError("tile must look like 40,12 (column,row)") from None


def _detect_color() -> str:
    """Return the colour mode this terminal supports: ``truecolor``, ``256`` or ``none`` (piped or NO_COLOR)."""
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return "none"
    colorterm = os.environ.get("COLORTERM", "").lower()
    if (
        colorterm in ("truecolor", "24bit")
        or os.environ.get("WT_SESSION")
        or os.name == "nt"
        or os.environ.get("TERM_PROGRAM") in ("iTerm.app", "vscode", "WezTerm")
    ):
        return "truecolor"
    return "256"


def _print_color_test(color: str) -> None:
    from biomegen.render.backends.ansi import to_ansi
    from biomegen.render.backends.plain import to_plain
    from biomegen.render.colortest import color_test

    hints = {k: os.environ[k] for k in ("WT_SESSION", "COLORTERM", "TERM", "TERM_PROGRAM") if os.environ.get(k)}
    document = color_test(_detect_color(), hints)
    mode = _detect_color() if color == "auto" else color
    print(to_plain(document) if mode == "none" else to_ansi(document, mode))


def _run_static(world: Any, config: Config, args: argparse.Namespace) -> None:
    """Print (and optionally save) a static map of the whole world, a zoom or local part of it, or one site."""
    from biomegen.render.backends.ansi import to_ansi
    from biomegen.render.backends.html import to_html
    from biomegen.render.backends.plain import to_plain
    from biomegen.render.static import render_detail, render_static

    mode = _detect_color() if args.color == "auto" else args.color
    if args.scale in ("zoom", "local", "site"):
        size = shutil.get_terminal_size(fallback=(120, 37))
        static = render_detail(
            world,
            config,
            args.scale,
            args.view or "terrain",
            at=args.at,
            area=(size.columns, max(1, size.lines - 1)),
            ascii_only=args.ascii,
            color=mode != "none",
            floor=args.floor,
        )
    else:
        static = render_static(
            world,
            config,
            args.view or "terrain",
            labels=args.labels,
            ascii_only=args.ascii,
            color=mode != "none",
            legend=not args.no_legend,
        )
    print(to_plain(static.document) if mode == "none" else to_ansi(static.document, mode))
    title = f"The World of {world.island_name}"
    if args.html:
        Path(args.html).write_text(to_html(static.document, title), encoding="utf-8")
    if args.save:
        _save_static(static, Path(args.save), config, title)


def _save_static(static: Any, path: Path, config: Config, title: str) -> None:
    """Write ``static`` to ``path`` in the back-end its suffix names (.html, .svg, .png, else plain text)."""
    from biomegen.render.backends.html import to_html
    from biomegen.render.backends.plain import to_plain
    from biomegen.render.backends.png import render_png
    from biomegen.render.backends.svg import render_svg

    suffix = path.suffix.lower()
    background = tuple(config.get("export.background"))
    cell_px = int(config.get("export.cell_px"))
    if suffix == ".svg":
        path.write_text(render_svg(static.grid, cell_px, background), encoding="utf-8")
    elif suffix == ".png":
        if not render_png(static.grid, cell_px, background, str(path)):
            print("(install Pillow to save PNG)", file=sys.stderr)
    elif suffix in (".html", ".htm"):
        path.write_text(to_html(static.document, title), encoding="utf-8")
    else:
        path.write_text(to_plain(static.document) + "\n", encoding="utf-8")


def resolve_seed(cli_seed: Optional[str], config: Config) -> int:
    """Resolve the effective master seed with precedence: CLI > config.general.seed > random.

    A freshly generated random seed is normalised and returned so the run can be reproduced later
    (the caller echoes it). os.urandom is used as the entropy source - not the time - so nothing in
    the seed path depends on wall-clock state.
    """
    if cli_seed is not None:
        return rng.normalize_seed(cli_seed)
    cfg_seed = config.get("general.seed", 0)
    if cfg_seed:
        return rng.normalize_seed(cfg_seed)
    return rng.normalize_seed(int.from_bytes(os.urandom(8), "big"))


def _apply_overrides(args: argparse.Namespace, config: Config, parser: argparse.ArgumentParser) -> None:
    """Apply CLI overrides directly onto the merged config tree (CLI > config file > defaults)."""
    if args.width is not None:
        config.data["world"]["width"] = args.width
    if args.height is not None:
        config.data["world"]["height"] = args.height
    if args.noise_backend is not None:
        config.data["terrain"]["noise_backend"] = args.noise_backend
    if args.style is not None:
        if args.style != "seed" and args.style not in config.get("tables.styles"):
            parser.error(f"unknown style {args.style!r}; available: seed, {', '.join(config.get('tables.styles'))}")
        config.data["terrain"]["style"] = args.style
    if args.view is not None and args.view not in config.get("render.views"):
        parser.error(f"unknown view {args.view!r}; available: {', '.join(config.get('render.views'))}")
    if args.at is not None and args.scale in (None, "map"):
        parser.error("--at needs --scale zoom, local or site")
    if args.scale == "site" and args.at is None:
        parser.error("--scale site needs --at X,Y on a point of interest")
    if args.start is not None:
        config.data["history"]["start"] = args.start
    filtering = args.kind or args.from_year is not None or args.to_year is not None or args.realm or args.search
    if (filtering or args.no_pager) and not args.chronicle:
        parser.error("--kind, --from-year, --to-year, --realm, --search and --no-pager need --chronicle")
    if args.from_year is not None and args.to_year is not None and args.from_year > args.to_year:
        parser.error(f"--from-year {args.from_year} is after --to-year {args.to_year}")
    if args.size_km is not None:
        config.data["world"]["size_km"] = list(args.size_km)
    if args.lat is not None:
        config.data["world"]["center_lat"] = args.lat
    if args.lon is not None:
        config.data["world"]["center_lon"] = args.lon


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if os.name == "nt":
        os.system("")  # enables VT escape processing on Windows 10+
    if not args.ascii:
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except AttributeError, ValueError:
            pass
    if args.color_test:
        _print_color_test(args.color)
        return 0
    if args.sim and (
        args.headless or args.chronicle or args.history is not None or args.view or args.scale or args.save or args.html
    ):
        parser.error(
            "--sim runs in the explorer: leave out --headless, --chronicle, --history, --view, --scale, --save "
            "and --html"
        )
    config = load_config(args.config)

    _apply_overrides(args, config, parser)

    seed = resolve_seed(args.seed, config)
    print(f"biomegen: seed={seed}", file=sys.stderr if args.chronicle or args.history is not None else sys.stdout)

    # Generate the world (the same pipeline feeds both the UI and the headless dump).
    from biomegen import pipeline

    world = pipeline.generate(config, seed)

    if args.headless:
        _print_stats(pipeline.stats(world))
        return 0

    if args.chronicle:
        _show_chronicle(world, config, args)
        return 0

    if args.history is not None:
        _show_history(world, config, args, parser)
        return 0

    if args.at is not None and not (0 <= args.at[0] < world.width and 0 <= args.at[1] < world.height):
        parser.error(f"--at {args.at[0]},{args.at[1]} is outside the {world.width}x{world.height} world")

    if args.view or args.scale or args.save or args.html:
        try:
            _run_static(world, config, args)
        except ValueError as error:  # e.g. --scale site on a tile with no point of interest
            parser.error(str(error))
        return 0

    if not sys.stdout.isatty() or not sys.stdin.isatty():
        parser.error("the explorer needs a terminal; use --view, --scale, --save or --headless for scripted output")

    from biomegen.explorer import app
    from biomegen.explorer.ticks import SimTicks

    mode = _detect_color() if args.color == "auto" else args.color
    app.run(world, config, mode, args.ascii, ticks=SimTicks.start(world, config) if args.sim else None)
    return 0


def _show_history(world: Any, config: Config, args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Open the history viewer (``--history [YEAR]``); it needs a terminal."""
    if not sys.stdout.isatty() or not sys.stdin.isatty():
        parser.error("--history needs a terminal; use --chronicle for a printed history")
    from biomegen.explorer.history_viewer import run_history

    mode = _detect_color() if args.color == "auto" else args.color
    run_history(world, config, mode, None if args.history < 0 else args.history, args.ascii)


def _show_chronicle(world: Any, config: Config, args: argparse.Namespace) -> None:
    """Show the chronicle (filtered by ``--kind`` and the like): in the pager on a terminal, else printed."""
    from biomegen.world.chronicle import ChronicleFilter

    chronicle_filter = ChronicleFilter(
        kinds=tuple(dict.fromkeys(args.kind)),
        year_from=args.from_year,
        year_to=args.to_year,
        realm=args.realm,
        text=args.search,
        salience=args.salience,
    )
    mode = _detect_color() if args.color == "auto" else args.color
    interactive = sys.stdout.isatty() and sys.stdin.isatty() and args.chronicle_format == "text" and not args.no_pager
    if interactive:
        from biomegen.explorer.chronicle_pager import run_chronicle

        run_chronicle(world, config, mode, chronicle_filter)
        return
    _print_chronicle(world, config, args, chronicle_filter, mode)


def _print_chronicle(world: Any, config: Config, args: argparse.Namespace, chronicle_filter: Any, mode: str) -> None:
    """Print the chronicle as JSON, or as three-column text (coloured when ``mode`` is not ``none``)."""
    from biomegen.render.backends.ansi import to_ansi
    from biomegen.render.chronicle import chronicle_document
    from biomegen.world.chronicle import chronicle_json, chronicle_text, filter_events

    kept = filter_events(world, chronicle_filter)
    events = kept if chronicle_filter.active or len(kept) != len(world.chronicle) else None  # None: the whole chronicle
    if args.chronicle_format == "json":
        print(chronicle_json(world, events))
        return
    if mode == "none":
        print(chronicle_text(world, events))
    else:
        print(to_ansi(chronicle_document(world, config, events), mode))


def _print_stats(stats: dict[str, Any]) -> None:
    """Pretty-print the headless generation statistics."""
    print(f"world: {stats['size'][0]}x{stats['size'][1]}  land={stats['land_fraction']:.0%}")
    print(f"cell: {stats['cell_km'][0]} x {stats['cell_km'][1]} km  top-left: {stats['lat_top']}, {stats['lon_left']}")
    print(f"terrain: {stats['terrain_style']}  elevation_m: {stats['elevation_m']}")
    print(
        f"realms={stats['realms']}  rivers={stats['rivers']} ({stats['river_tiles']} tiles)  "
        f"lakes={stats['lakes']} ({stats['lake_tiles']} tiles)  "
        f"roads={stats['road_tiles']} tiles  bridge_tiles={stats.get('bridge_tiles', 0)}"
    )
    print(f"pois={stats['pois']}: {stats.get('poi_kinds', {})}")
    print(f"chronicle: {stats['events']} events, {stats['fallen_realms']} fallen realms: {stats['event_kinds']}")
    print("biomes:")
    for name, count in stats["biomes"].items():
        print(f"  {name:>10}: {count}")
    print(f"fingerprint: {stats['fingerprint']}")
