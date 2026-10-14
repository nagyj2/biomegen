"""Tests for the determinism anchor (biomegen.util.rng).

These guard the single most important property of the whole generator: that a seed deterministically
and reproducibly fans out into independent sub-streams, with no dependence on Python's per-process
hash salt.
"""

from __future__ import annotations

import os
import subprocess
import sys

from biomegen.util import rng


def test_derive_int_is_stable_across_calls():
    assert rng.derive_int(12345, "heightmap") == rng.derive_int(12345, "heightmap")


def test_derive_int_distinguishes_labels_and_seeds():
    a = rng.derive_int(12345, "heightmap")
    b = rng.derive_int(12345, "moisture")
    c = rng.derive_int(99999, "heightmap")
    assert a != b  # different labels -> different streams
    assert a != c  # different seeds -> different streams


def test_label_components_are_order_sensitive():
    # ("ab", "c") and ("a", "bc") must not collide thanks to the separator byte.
    assert rng.derive_int(1, "ab", "c") != rng.derive_int(1, "a", "bc")


def test_derive_random_streams_match_for_same_inputs():
    r1 = rng.derive(7, "poi")
    r2 = rng.derive(7, "poi")
    assert [r1.random() for _ in range(5)] == [r2.random() for _ in range(5)]


def test_numpy_generator_is_reproducible():
    g1 = rng.derive_numpy(7, "heightmap")
    g2 = rng.derive_numpy(7, "heightmap")
    assert (g1.integers(0, 1000, size=10) == g2.integers(0, 1000, size=10)).all()


def test_normalize_seed_accepts_int_hex_and_string():
    assert rng.normalize_seed(42) == 42
    assert rng.normalize_seed("0x2a") == 42
    assert rng.normalize_seed("42") == 42
    # An arbitrary string hashes to a stable value (and stays in uint64 range).
    s1 = rng.normalize_seed("my island")
    assert 0 <= s1 < 2**64
    assert s1 == rng.normalize_seed("my island")


def test_tile_rng_keyed_on_coordinates():
    assert rng.derive_int(1, "poi_interior", 3, 4) == rng.derive_int(1, "poi_interior", 3, 4)
    assert rng.derive_int(1, "poi_interior", 3, 4) != rng.derive_int(1, "poi_interior", 4, 3)


def test_seed_derivation_independent_of_pythonhashseed():
    """A string seed must derive the same int regardless of PYTHONHASHSEED (proves no hash() use)."""
    code = "from biomegen.util import rng; print(rng.normalize_seed('my island'))"
    outputs = []
    for hashseed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=hashseed)
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
        assert result.returncode == 0, result.stderr
        outputs.append(result.stdout.strip())
    assert len(set(outputs)) == 1, f"seed derivation varied with PYTHONHASHSEED: {outputs}"
