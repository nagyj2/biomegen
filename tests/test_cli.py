"""Tests for the command-line entry points (`python -m biomegen` and the `biomegen` console script)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from biomegen import pipeline
from biomegen.config import load_config


def test_module_entry_prints_the_pipeline_fingerprint():
    # `python -m biomegen --headless` reports the same fingerprint as generating in-process.
    result = subprocess.run(
        [sys.executable, "-m", "biomegen", "--headless", "--seed", "12345"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    expected = pipeline.generate(load_config(None), 12345).fingerprint()
    assert f"fingerprint: {expected}" in result.stdout


def test_console_script_shows_help():
    # The installed `biomegen` console script resolves to biomegen.cli:main and exits 0 on --help.
    script = Path(sys.executable).with_name("biomegen")
    result = subprocess.run([str(script), "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("usage: biomegen")
