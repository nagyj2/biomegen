"""Procedural noise: selectable backends + fractal Brownian motion + domain warping.

Natural terrain is built by summing several octaves of smooth gradient noise (fractal Brownian
motion, fBm) and optionally *domain-warping* the sample coordinates so straight noise contours bend
into meandering coastlines and ridgelines. This module provides:

* **Noise backends** (registered in :data:`NOISE_BACKENDS`, selected by ``terrain.noise_backend``):
    - ``perlin``     - in-house, fully numpy-vectorised classic Perlin gradient noise. This is the
                       reproducibility-guaranteed DEFAULT: it uses only +, *, floor and linear
                       interpolation (no transcendental functions), so float64 results are identical
                       across platforms for a given seed.
    - ``value``      - in-house value noise (cheaper, slightly blockier).
    - ``opensimplex``- the opensimplex library (smooth, isotropic; sampled point-wise so it also
                       works under domain warping).
    - ``noise_lib``  - the optional ``noise`` C-extension Perlin; only registered if importable.
* **fBm** (:func:`fbm`), **ridged** multifractal (:func:`ridged`), **mountain belts**
  (:func:`belt_lines`) and **domain warp** (:func:`domain_warp`) that work on any backend.
* Helpers to build a coordinate grid in tiles (:func:`coordinate_grid`) or in km (:func:`km_grid`) and to
  normalise a field to [0, 1] (:func:`normalize01`).

A backend is a callable ``sample(xs, ys) -> ndarray`` where ``xs``/``ys`` are float64 arrays of equal
shape (arbitrary coordinates, not necessarily a separable grid) and the result is roughly in
[-1, 1]. Backends are produced by a factory ``make(seed_int) -> sample`` stored in the registry.
"""

from __future__ import annotations

from typing import Callable, Tuple

import numpy as np

from ..registry import Registry
from .units import GridScale

# A noise sampler maps two coordinate arrays to a value array in ~[-1, 1].
Sampler = Callable[[np.ndarray, np.ndarray], np.ndarray]
# A backend factory turns a seed integer into a sampler.
BackendFactory = Callable[[int], Sampler]

NOISE_BACKENDS: Registry[BackendFactory] = Registry("noise_backend")


# ---------------------------------------------------------------------------
# Shared math helpers (vectorised, transcendental-free).
# ---------------------------------------------------------------------------
def _fade(t: np.ndarray) -> np.ndarray:
    """Perlin's smootherstep easing curve 6t^5 - 15t^4 + 10t^3 (zero 1st & 2nd derivatives at 0/1)."""
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _lerp(a: np.ndarray, b: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Linear interpolation."""
    return a + t * (b - a)


def _build_permutation(seed_int: int, size: int = 256) -> np.ndarray:
    """Return a doubled permutation table of ``[0, size)`` shuffled deterministically from the seed.

    Doubling (``[p, p]``) lets us index ``perm[perm[xi] + yi]`` without bounds-wrapping arithmetic.
    """
    gen = np.random.default_rng(seed_int)
    perm = gen.permutation(size).astype(np.int32)
    return np.concatenate([perm, perm])


def _grad2(h: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Dot the lattice gradient (selected by the low 3 bits of hash ``h``) with offset ``(x, y)``.

    Uses 8 evenly distributed gradient directions - the standard improved-Perlin 2-D gradient set.
    """
    g = h & 7
    u = np.where(g < 4, x, y)
    v = np.where(g < 4, y, x)
    su = np.where((g & 1) == 0, u, -u)
    sv = np.where((g & 2) == 0, v, -v)
    return su + sv


# ---------------------------------------------------------------------------
# Backend: Perlin gradient noise (default, in-house, fully vectorised).
# ---------------------------------------------------------------------------
@NOISE_BACKENDS.register("perlin")
def _make_perlin(seed_int: int) -> Sampler:
    """Classic improved-Perlin gradient noise (Ken Perlin, 2002), vectorised over numpy arrays."""
    perm = _build_permutation(seed_int)

    def sample(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        # Integer lattice cell coordinates (wrapped to the 256-period table) and fractional offsets.
        xi = np.floor(xs).astype(np.int64) & 255
        yi = np.floor(ys).astype(np.int64) & 255
        xf = xs - np.floor(xs)
        yf = ys - np.floor(ys)
        u = _fade(xf)
        v = _fade(yf)
        # Hash the four cell corners through the permutation table.
        aa = perm[perm[xi] + yi]
        ab = perm[perm[xi] + yi + 1]
        ba = perm[perm[xi + 1] + yi]
        bb = perm[perm[xi + 1] + yi + 1]
        # Interpolate the corner gradient contributions.
        x1 = _lerp(_grad2(aa, xf, yf), _grad2(ba, xf - 1, yf), u)
        x2 = _lerp(_grad2(ab, xf, yf - 1), _grad2(bb, xf - 1, yf - 1), u)
        # Perlin output is roughly in [-1, 1]; scale toward that range.
        return _lerp(x1, x2, v) * 0.9

    return sample


# ---------------------------------------------------------------------------
# Backend: value noise (in-house, vectorised).
# ---------------------------------------------------------------------------
@NOISE_BACKENDS.register("value")
def _make_value(seed_int: int) -> Sampler:
    """Value noise: bilinearly-interpolated pseudo-random lattice values (cheap, blockier)."""
    perm = _build_permutation(seed_int)

    def _corner(xi: np.ndarray, yi: np.ndarray) -> np.ndarray:
        # Hash the integer corner to a value in [-1, 1].
        h = perm[perm[xi & 255] + (yi & 255)]
        return h / 127.5 - 1.0

    def sample(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        xi = np.floor(xs).astype(np.int64)
        yi = np.floor(ys).astype(np.int64)
        xf = xs - np.floor(xs)
        yf = ys - np.floor(ys)
        u = _fade(xf)
        v = _fade(yf)
        c00 = _corner(xi, yi)
        c10 = _corner(xi + 1, yi)
        c01 = _corner(xi, yi + 1)
        c11 = _corner(xi + 1, yi + 1)
        return _lerp(_lerp(c00, c10, u), _lerp(c01, c11, u), v)

    return sample


# ---------------------------------------------------------------------------
# Backend: opensimplex (library; sampled point-wise so it works under domain warping).
# ---------------------------------------------------------------------------
@NOISE_BACKENDS.register("opensimplex")
def _make_opensimplex(seed_int: int) -> Sampler:
    """opensimplex noise. Sampled per point (the lib's grid helper is separable; warp is not)."""
    import opensimplex

    gen = opensimplex.OpenSimplex(seed=seed_int & 0x7FFFFFFFFFFFFFFF)
    noise2 = gen.noise2

    def sample(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        fx = xs.ravel()
        fy = ys.ravel()
        out = np.empty(fx.shape, dtype=np.float64)
        for i in range(fx.size):
            out[i] = noise2(float(fx[i]), float(fy[i]))
        return out.reshape(xs.shape)

    return sample


def _register_optional_backends() -> None:
    """Register backends that depend on optional packages, only if those import successfully."""
    try:
        import noise as _noise_lib  # noqa: F401  (C-extension Perlin/Simplex; optional)
    except Exception:
        return  # Not installed (e.g. no C compiler) -> backend simply unavailable.

    def _make_noise_lib(seed_int: int) -> Sampler:
        base = int(seed_int % 256)

        def sample(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
            import noise as nz

            fx = xs.ravel()
            fy = ys.ravel()
            out = np.empty(fx.shape, dtype=np.float64)
            for i in range(fx.size):
                out[i] = nz.pnoise2(float(fx[i]), float(fy[i]), base=base)
            return out.reshape(xs.shape)

        return sample

    NOISE_BACKENDS.add("noise_lib", _make_noise_lib)


_register_optional_backends()


# ---------------------------------------------------------------------------
# Public high-level API used by the generation stages.
# ---------------------------------------------------------------------------
def get_sampler(name: str, seed_int: int) -> Sampler:
    """Return a seeded noise sampler for backend ``name`` (raises if the backend is unknown)."""
    return NOISE_BACKENDS.get(name)(seed_int)


def coordinate_grid(
    shape: Tuple[int, int], scale: float, scale_x: float = 1.0, scale_y: float = 1.0
) -> Tuple[np.ndarray, np.ndarray]:
    """Return ``(cx, cy)`` float64 coordinate arrays for a ``(height, width)`` grid.

    Each tile coordinate is divided by ``scale * scale_<axis>`` so ``scale`` sets the base feature
    size (in tiles) and the global ``scale_x``/``scale_y`` multipliers stretch features along an axis
    (values > 1 enlarge features / zoom out).
    """
    h, w = shape
    ys, xs = np.meshgrid(np.arange(h, dtype=np.float64), np.arange(w, dtype=np.float64), indexing="ij")
    cx = xs / (scale * scale_x)
    cy = ys / (scale * scale_y)
    return cx, cy


def km_grid(shape: Tuple[int, int], scale: GridScale, feature_km: float) -> Tuple[np.ndarray, np.ndarray]:
    """Return ``(cx, cy)`` coordinates of cell centres in units of ``feature_km`` kilometres.

    Unlike :func:`coordinate_grid`, one unit is the same physical distance on both axes, so noise
    features stay round on anisotropic cells and keep their km size when the grid resolution changes.
    """
    h, w = shape
    ys, xs = np.meshgrid(np.arange(h, dtype=np.float64), np.arange(w, dtype=np.float64), indexing="ij")
    cx = (xs + 0.5) * (scale.km_per_col / feature_km)
    cy = (ys + 0.5) * (scale.km_per_row / feature_km)
    return cx, cy


def fbm(
    sampler: Sampler,
    cx: np.ndarray,
    cy: np.ndarray,
    *,
    octaves: int,
    persistence: float,
    lacunarity: float,
) -> np.ndarray:
    """Sum ``octaves`` of ``sampler`` at growing frequency / shrinking amplitude (fractal Brownian motion).

    Each octave multiplies frequency by ``lacunarity`` and amplitude by ``persistence``; the sum is
    normalised by the total amplitude so the result stays in ~[-1, 1] regardless of octave count.
    """
    total = np.zeros_like(cx)
    amplitude = 1.0
    frequency = 1.0
    norm = 0.0
    for _ in range(int(octaves)):
        total += amplitude * sampler(cx * frequency, cy * frequency)
        norm += amplitude
        amplitude *= persistence
        frequency *= lacunarity
    return total / norm if norm else total


def ridged(
    sampler: Sampler,
    cx: np.ndarray,
    cy: np.ndarray,
    *,
    octaves: int,
    persistence: float = 0.5,
    lacunarity: float = 2.1,
) -> np.ndarray:
    """Ridged multifractal noise in [0, 1]: sharp crests where the base noise crosses zero.

    Each octave contributes ``(1 - |n|)^2``, so the zero-crossings of the sampler become narrow
    ridges; the sum is normalised by the total amplitude.
    """
    total = np.zeros_like(cx)
    amplitude = 1.0
    frequency = 1.0
    norm = 0.0
    for _ in range(int(octaves)):
        crest = 1.0 - np.abs(sampler(cx * frequency, cy * frequency))
        total += amplitude * crest * crest
        norm += amplitude
        amplitude *= persistence
        frequency *= lacunarity
    return np.clip(total / norm, 0.0, 1.0) if norm else total


def belt_lines(
    sampler: Sampler,
    cx: np.ndarray,
    cy: np.ndarray,
    *,
    width: float,
    octaves: int = 3,
    persistence: float = 0.5,
    lacunarity: float = 2.0,
) -> np.ndarray:
    """Mountain-belt strength in [0, 1]: 1 on the winding zero-crossings of a low-frequency fBm.

    Strength falls linearly to 0 where ``|fbm|`` reaches ``width``, so ``width`` (in fBm units) sets
    how broad the belts are. Sampled at a low frequency, the result is a few long, curving bands.
    """
    field = fbm(sampler, cx, cy, octaves=octaves, persistence=persistence, lacunarity=lacunarity)
    return np.clip(1.0 - np.abs(field) / max(width, 1e-12), 0.0, 1.0)


def domain_warp(
    warp_sampler: Sampler,
    cx: np.ndarray,
    cy: np.ndarray,
    *,
    strength: float,
    octaves: int = 2,
    persistence: float = 0.5,
    lacunarity: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return coordinate arrays perturbed by a vector fBm field (Inigo Quilez's domain warping).

    Two decorrelated fBm fields (the second sampled at a large constant offset) give the x and y
    components of the warp vector, scaled by ``strength``. Feeding the warped coordinates into the
    terrain sampler bends otherwise-straight contours into natural meanders.
    """
    if strength <= 0:
        return cx, cy
    wx = fbm(warp_sampler, cx, cy, octaves=octaves, persistence=persistence, lacunarity=lacunarity)
    # Offset by a large constant so the y component is statistically independent of the x component.
    wy = fbm(warp_sampler, cx + 137.0, cy + 91.0, octaves=octaves, persistence=persistence, lacunarity=lacunarity)
    return cx + strength * wx, cy + strength * wy


def normalize01(field: np.ndarray) -> np.ndarray:
    """Rescale a field to [0, 1] by its own min/max (constant fields map to all zeros)."""
    lo = float(field.min())
    hi = float(field.max())
    if hi - lo < 1e-12:
        return np.zeros_like(field)
    return (field - lo) / (hi - lo)
