"""Smoke tests for the measurement scripts in ``scripts/``."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ROOT / "scripts" / "simulate.sh"), *args], capture_output=True, text=True, check=False, cwd=ROOT
    )


def test_simulate_prints_the_series_and_the_sim_fingerprint() -> None:
    # A header, a row at the start and one a year on, then the digest of the state the run ended on.
    result = _run("--seed", "5", "2", "--every", "1")
    lines = result.stdout.splitlines()
    assert (result.returncode, lines[0].split()[:2], len(lines), lines[-1].split()[0]) == (
        0,
        ["date", "tick"],
        5,
        "sim",
    )


def test_simulate_proof_prints_a_fingerprint_for_each_fixture_seed() -> None:
    result = _run("--proof", "1")
    lines = [line.split() for line in result.stdout.splitlines()]
    assert (result.returncode, [line[0] for line in lines], {len(line[1]) for line in lines}) == (
        0,
        ["42", "7", "1337", "11", "15"],
        {32},
    )


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
