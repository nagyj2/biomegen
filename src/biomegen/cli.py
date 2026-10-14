"""biomegen - application entry point.

Run the CLI application with::

    uv run biomegen [--seed N] [--config path.toml] [--width W] [--height H]
                    [--noise-backend {perlin,value,opensimplex}] [--poi-sampler {bluenoise,random,grid}]
                    [--headless]

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
        "--preview",
        action="store_true",
        help="Print a no-colour ASCII rendering of the biome map (no terminal needed).",
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
    return parser


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


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    config = load_config(args.config)

    # Apply CLI overrides directly onto the merged config tree (CLI > config file > defaults).
    if args.width is not None:
        config.data["world"]["width"] = args.width
    if args.height is not None:
        config.data["world"]["height"] = args.height
    if args.noise_backend is not None:
        config.data["terrain"]["noise_backend"] = args.noise_backend
    if args.poi_sampler is not None:
        config.data["poi"]["sampler"] = args.poi_sampler

    seed = resolve_seed(args.seed, config)
    print(f"biomegen: seed={seed}")

    # Generate the world (the same pipeline feeds both the UI and the headless dump).
    from biomegen import pipeline

    world = pipeline.generate(config, seed)

    if args.headless:
        _print_stats(pipeline.stats(world))
        return 0

    if args.preview or args.preview_zoom or args.preview_local:
        from biomegen.render import preview

        if args.preview:
            print(preview.render_biome_ascii(world, config))
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
    print(f"elevation: {stats['elevation']}")
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
