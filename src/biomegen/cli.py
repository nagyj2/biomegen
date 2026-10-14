"""biomegen - application entry point.

Run the CLI application with::

    uv run biomegen [--seed N] [--config path.toml] [--width W] [--height H]
                    [--noise-backend {perlin,value,opensimplex}] [--poi-sampler {bluenoise,random,grid}]
                    [--headless] [--view NAME] [--labels {all,cities,none}] [--color {auto,truecolor,256,none}]
                    [--ascii] [--no-legend] [--save FILE] [--html FILE] [--color-test]

This launcher wires together the three top-level concerns and nothing else:
    1. parse CLI arguments,
    2. load + override configuration and resolve the effective seed,
    3. hand off to either the curses UI (interactive) or a headless stats dump.

The heavy lifting lives in the importable :mod:`biomegen` package. (Phase 0 scaffolding: the
generation pipeline and curses UI are stubbed and filled in by later phases.)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from biomegen.config import Config, load_config
from biomegen.util import rng


def _build_parser() -> argparse.ArgumentParser:
    # Import registries now (they populate at module import time) so choices reflect installed backends.
    from biomegen.pipeline.poi_sampler import POI_SAMPLERS
    from biomegen.util.noise import NOISE_BACKENDS

    noise_choices = list(NOISE_BACKENDS.names())
    sampler_choices = list(POI_SAMPLERS.names())

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
        "--poi-sampler",
        choices=sampler_choices,
        default=None,
        help=(
            f"POI placement algorithm. Overrides config poi.sampler. "
            f"Choices: {', '.join(sampler_choices)}. "
            f"Default: bluenoise (Poisson-disk spacing for natural spread)."
        ),
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Generate the world and print summary statistics without launching the UI.",
    )
    parser.add_argument(
        "--preview-zoom", action="store_true", help="Print a no-colour ASCII rendering of the mid 'zoom' detail view."
    )
    parser.add_argument(
        "--preview-local",
        action="store_true",
        help="Print a no-colour ASCII rendering of the close 'local' detail view.",
    )
    parser.add_argument(
        "--export",
        choices=("world", "view"),
        default=None,
        help=(
            "Export an image to export.dir without launching the UI: 'world' = the whole island at "
            "full resolution, 'view' = the biome map. Writes SVG always, PNG if Pillow is installed."
        ),
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
        help="Print a static map of this render.views entry (terrain, elevation, temperature, rainfall) and exit.",
    )
    parser.add_argument("--labels", choices=("all", "cities", "none"), default="all", help="Which names to draw.")
    parser.add_argument(
        "--color",
        choices=("auto", "truecolor", "256", "none"),
        default="auto",
        help="Colour mode of static output (auto detects the terminal).",
    )
    parser.add_argument("--ascii", action="store_true", help="Use only 7-bit ASCII glyphs in static output.")
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
    parser.add_argument("--color-test", action="store_true", help="Show colour and glyph test swatches and exit.")
    return parser


def _parse_size_km(text: str) -> tuple[float, float]:
    """Parse ``6000x3000`` (km, east-west x north-south) for ``--size-km``."""
    try:
        east_west, north_south = text.lower().replace("km", "").split("x")
        return float(east_west), float(north_south)
    except ValueError:
        raise argparse.ArgumentTypeError("size must look like 6000x3000 (width x height in km)") from None


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
    """Print (and optionally save) a static map of the whole world."""
    from biomegen.render.backends.ansi import to_ansi
    from biomegen.render.backends.html import to_html
    from biomegen.render.backends.plain import to_plain
    from biomegen.render.static import render_static

    mode = _detect_color() if args.color == "auto" else args.color
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
    if args.poi_sampler is not None:
        config.data["poi"]["sampler"] = args.poi_sampler
    if args.style is not None:
        if args.style != "seed" and args.style not in config.get("tables.styles"):
            parser.error(f"unknown style {args.style!r}; available: seed, {', '.join(config.get('tables.styles'))}")
        config.data["terrain"]["style"] = args.style
    if args.view is not None and args.view not in config.get("render.views"):
        parser.error(f"unknown view {args.view!r}; available: {', '.join(config.get('render.views'))}")
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
    config = load_config(args.config)

    _apply_overrides(args, config, parser)

    seed = resolve_seed(args.seed, config)
    print(f"biomegen: seed={seed}")

    # Generate the world (the same pipeline feeds both the UI and the headless dump).
    from biomegen import pipeline

    world = pipeline.generate(config, seed)

    if args.headless:
        _print_stats(pipeline.stats(world))
        return 0

    if args.view or args.save or args.html:
        _run_static(world, config, args)
        return 0

    if args.preview_zoom or args.preview_local:
        from biomegen.render import preview

        if args.preview_zoom:
            print(preview.render_zoom_ascii(world, config))
        if args.preview_local:
            print(preview.render_local_ascii(world, config))
        return 0

    if args.export is not None:
        from biomegen import export
        from biomegen.render.state import ViewState

        if args.export == "world":
            paths = export.export_world(world, config)
        else:
            vs = ViewState(cx=world.width // 2, cy=world.height // 2, mode="fit")
            paths = export.export_view(world, config, vs)
        for path in paths:
            print(f"wrote {path}")
        if not any(p.endswith(".png") for p in paths):
            print("(install Pillow to also export PNG)")
        return 0

    from biomegen.render import app

    app.run(world, config)
    return 0


def _print_stats(stats: dict[str, Any]) -> None:
    """Pretty-print the headless generation statistics."""
    print(f"world: {stats['size'][0]}x{stats['size'][1]}  land={stats['land_fraction']:.0%}")
    print(f"cell: {stats['cell_km'][0]} x {stats['cell_km'][1]} km  top-left: {stats['lat_top']}, {stats['lon_left']}")
    print(f"terrain: {stats['terrain_style']}  elevation_m: {stats['elevation_m']}")
    print(
        f"regions={stats['regions']}  rivers={stats['rivers']} ({stats['river_tiles']} tiles)  "
        f"lakes={stats['lakes']} ({stats['lake_tiles']} tiles)  "
        f"roads={stats['road_tiles']} tiles  bridges={stats.get('bridges', 0)}"
    )
    print(f"pois={stats['pois']}: {stats.get('poi_kinds', {})}")
    print("biomes:")
    for name, count in stats["biomes"].items():
        print(f"  {name:>10}: {count}")
    print(f"fingerprint: {stats['fingerprint']}")
