"""Smoke tests for the measurement scripts in ``scripts/``."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_simulation_spike_times_the_claim_the_front_distance_and_the_danger_field() -> None:
    # The spike runs on a small world and reports each piece it measures, one line each.
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "bench.sh"), "--seed", "5", "--sim", "1", "96x48"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    lines = result.stdout.splitlines()
    assert result.returncode == 0 and [
        any(label in line for line in lines)
        for label in ("claim Dijkstra, every realm", "front distance", "danger field, nearest source")
    ] == [True, True, True]
