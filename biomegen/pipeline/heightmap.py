"""Stage 1: heightmap generation.

Produces ``world.elevation`` (normalised to [0, 1]) - the field every later stage leans on. The
recipe is the standard noise-driven-worldgen one (Red Blob Games / libnoise / Minecraft-style), with
two shaping controls that make the island look interesting rather than a smooth blob:

1. Build a fractal-Brownian-motion (fBm) field from the configured noise backend.
2. Strongly **domain-warp** the sample coordinates so coastlines and ridges meander naturally.
3. Build an **irregular island mask** = a radial falloff whose effective radius is perturbed by:
     * medium/high-frequency *coast-detail* noise -> peninsulas, bays, gulfs, channels, straits, and
     * low-frequency *archipelago* noise -> satellite islands surfacing around the main landmass.
4. Multiply the terrain by the mask, renormalise to [0, 1], and apply a redistribution exponent.

All four noise fields (terrain, warp, coast, island) use independent derived seeds so they vary
independently yet reproducibly. This stage owns the noise; later stages only read ``elevation``.
"""

from __future__ import annotations

import numpy as np

from ..config.model import Config
from ..util import noise, rng
from ..world.world import World


def _radial_distance(shape: tuple[int, int]) -> np.ndarray:
    """Return normalised distance-from-centre in [0, ~1], matching the map's aspect ratio.

    Using ``linspace(-1, 1)`` on each axis makes the base island elliptical to the map rather than a
    circle squashed into a wide terminal.
    """
    h, w = shape
    yy, xx = np.meshgrid(np.linspace(-1.0, 1.0, h), np.linspace(-1.0, 1.0, w), indexing="ij")
    return np.sqrt(xx * xx + yy * yy) / np.sqrt(2.0)


def _island_mask(shape: tuple[int, int], t: Config, seed: int, scale_x: float, scale_y: float) -> np.ndarray:
    """Return the island mask in [0, 1] (1 = solid land core, 0 = open ocean).

    Built from a broad radial *core* (1 at the centre, falling to 0 at the edge) that is then shaped:

    * **coast detail** perturbs the core, but weighted by ``(1 - core)`` so it only bites near the
      shoreline. The interior stays solid (no fragmentation) while the outline becomes organic with
      peninsulas and bays (less round).
    * **archipelago** adds positive-only low-frequency lobes; since the core is already ~1 in the
      interior, these only matter in the outer ring, where they raise patches of ocean into small
      satellite islands around the dominant main island.
    """
    d = _radial_distance(shape)
    core = 1.0 - d ** float(t.get("falloff_power"))  # broad, solid core (negative far past the edge)

    coast_detail = float(t.get("coast_detail"))
    if coast_detail > 0:
        coast_sampler = noise.get_sampler(t.get("noise_backend"), rng.derive_int(seed, "heightmap.coast"))
        cx, cy = noise.coordinate_grid(shape, float(t.get("coast_scale")), scale_x, scale_y)
        coast = noise.fbm(coast_sampler, cx, cy, octaves=4, persistence=0.5, lacunarity=2.0)
        edge_weight = np.clip(1.0 - core, 0.0, 1.0)  # ~0 deep interior, ~1 at/below the shoreline
        core = core + coast_detail * coast * edge_weight

    archipelago = float(t.get("archipelago"))
    if archipelago > 0:
        island_sampler = noise.get_sampler(t.get("noise_backend"), rng.derive_int(seed, "heightmap.island"))
        ax, ay = noise.coordinate_grid(shape, float(t.get("archipelago_scale")), scale_x, scale_y)
        island = noise.fbm(island_sampler, ax, ay, octaves=3, persistence=0.5, lacunarity=2.0)
        core = core + archipelago * np.maximum(0.0, island)

    mask = np.clip(core, 0.0, 1.0)
    strength = float(t.get("falloff_strength"))  # <1 lets some terrain survive everywhere
    return mask * strength + (1.0 - strength)


def run(world: World, config: Config, seed: int) -> None:
    """Fill ``world.elevation`` in place."""
    t = config.section("terrain")
    backend = t.get("noise_backend")
    scale_x = config.get("world.scale_x")
    scale_y = config.get("world.scale_y")
    shape = (world.height, world.width)

    height_sampler = noise.get_sampler(backend, rng.derive_int(seed, "heightmap"))
    warp_sampler = noise.get_sampler(backend, rng.derive_int(seed, "heightmap.warp"))

    cx, cy = noise.coordinate_grid(shape, t.get("scale"), scale_x, scale_y)

    # Domain warp: offset the coordinates by a (lower-frequency) vector noise field.
    warp_strength = float(t.get("warp_strength"))
    if warp_strength > 0:
        wcx, wcy = noise.coordinate_grid(shape, t.get("warp_scale"), scale_x, scale_y)
        dx = noise.fbm(warp_sampler, wcx, wcy, octaves=int(t.get("warp_octaves")), persistence=0.5, lacunarity=2.0)
        dy = noise.fbm(
            warp_sampler, wcx + 137.0, wcy + 91.0, octaves=int(t.get("warp_octaves")), persistence=0.5, lacunarity=2.0
        )
        cx = cx + warp_strength * dx
        cy = cy + warp_strength * dy

    # Base fractal terrain in ~[-1, 1] -> normalise to [0, 1].
    base = noise.normalize01(
        noise.fbm(
            height_sampler,
            cx,
            cy,
            octaves=int(t.get("octaves")),
            persistence=float(t.get("persistence")),
            lacunarity=float(t.get("lacunarity")),
        )
    )

    # Shape it into an island. Blend the base terrain up to a land floor inside the mask so the main
    # landmass is solid (the interior cannot dip below sea level and break into fragments), while the
    # mask tapers to ocean at the coast and in the gaps between satellite islands. The result is
    # already a valid [0, 1] elevation, so it is NOT renormalised (renormalising would re-inflate the
    # land area and erase the ocean margins / satellite gaps).
    mask = _island_mask(shape, t, seed, scale_x, scale_y)
    land_floor = float(t.get("land_floor"))
    elev = mask * (land_floor + (1.0 - land_floor) * base)

    redistribution = float(t.get("redistribution"))
    if redistribution != 1.0:
        elev = elev**redistribution

    world.elevation = elev.astype(np.float64)
