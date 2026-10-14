"""Tests for the determinism anchor (biomegen.util.rng).

These guard the single most important property of the whole generator: that a seed deterministically
and reproducibly fans out into independent sub-streams, with no dependence on Python's per-process
hash salt.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

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


def _stage_labels_used_in_source() -> set[str]:
    """Collect the first label of every ``derive*`` call in the package that passes a string literal."""
    package = Path(rng.__file__).resolve().parents[1]
    labels: set[str] = set()
    for path in sorted(package.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("derive", "derive_int", "derive_numpy")
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                labels.add(node.args[1].value)
    return labels


def test_every_stage_label_in_source_is_registered():
    # A derive call whose first label is not in LABELS could collide with another stage's stream.
    used = _stage_labels_used_in_source()
    assert used, "the scan found no derive calls; the collector is broken"
    rng.assert_known_labels(used)


def test_redesigned_stage_labels_are_registered():
    # Each stage of the redesigned pipeline (plan 4.1) has its label reserved, incl. history.
    stages = {"terrain", "climate", "biomes", "geography", "settlements", "realms", "diplomacy", "history", "pois"}
    assert stages <= rng.LABELS
