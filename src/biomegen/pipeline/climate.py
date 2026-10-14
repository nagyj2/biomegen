"""Stage 3: climate fields (temperature + base moisture).

Temperature is **not** noise - it is a smooth, physically-motivated field: a latitude gradient (warm
equator, cold poles) minus an elevation lapse rate (higher = colder). Moisture is its own,
statistically-independent low-frequency fBm (so mountains are not automatically wet), nudged upward
near the coast. Hydrology later adds a freshwater-proximity bonus on top of this base moisture.
"""

from __future__ import annotations

import numpy as np

from ..config.model import Config
from ..util import noise, rng
from ..world.world import World


def _temperature(world: World, config: Config) -> np.ndarray:
    """Compute the normalised temperature field from latitude and an elevation lapse rate."""
    c = config.section("climate")
    h, w = world.height, world.width
    rows = np.linspace(0.0, 1.0, h)  # 0 at the top row, 1 at the bottom

    equator_t = float(c.get("equator_temp"))
    pole_t = float(c.get("pole_temp"))
    if c.get("orientation") == "north-pole-top":
        # Cold at the top, warm at the bottom.
        lat_temp = pole_t + (equator_t - pole_t) * rows
    else:  # "equator-center": warm middle band, cooler toward both top and bottom.
        poleward = np.abs(rows - 0.5) * 2.0  # 0 at the centre, 1 at the top/bottom edges
        lat_temp = equator_t + (pole_t - equator_t) * poleward

    temp = np.repeat(lat_temp[:, None], w, axis=1)  # broadcast across columns

    # Lapse rate: subtract proportional to how far above sea level a tile is.
    sea_level = float(config.get("world.sea_level"))
    above = np.clip((world.elevation - sea_level) / max(1e-6, 1.0 - sea_level), 0.0, 1.0)
    temp = temp - float(c.get("lapse_rate")) * above
    return np.clip(temp, 0.0, 1.0)


def _base_moisture(world: World, config: Config, seed: int) -> np.ndarray:
    """Compute base moisture as decorrelated fBm plus an optional coastal bonus."""
    c = config.section("climate")
    shape = (world.height, world.width)
    sampler = noise.get_sampler(config.get("terrain.noise_backend"), rng.derive_int(seed, "moisture"))
    cx, cy = noise.coordinate_grid(
        shape, float(c.get("moisture_scale")), config.get("world.scale_x"), config.get("world.scale_y")
    )
    moist = noise.normalize01(
        noise.fbm(
            sampler,
            cx,
            cy,
            octaves=int(c.get("moisture_octaves")),
            persistence=float(c.get("moisture_persistence")),
            lacunarity=2.0,
        )
    )

    # Bias the moisture distribution drier (>1) so the map is not blanketed in forest/jungle.
    redist = float(c.get("moisture_redistribution", 1.0))
    if redist != 1.0:
        moist = moist**redist

    coastal_bias = float(c.get("coastal_bias"))
    if coastal_bias > 0:
        # Exponential decay of the coastal bonus with distance to the ocean.
        coast = np.exp(-world.dist_to_ocean / max(1e-6, float(c.get("coastal_range"))))
        moist = np.clip(moist + coastal_bias * coast, 0.0, 1.0)
    return moist


def run(world: World, config: Config, seed: int) -> None:
    """Fill ``world.temperature`` and the base ``world.moisture`` in place."""
    world.temperature = _temperature(world, config).astype(np.float64)
    world.moisture = _base_moisture(world, config, seed).astype(np.float64)
