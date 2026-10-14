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


def _run_view(capsys, *args: str) -> str:
    from biomegen import cli

    assert cli.main(["--seed", "3", "--width", "64", "--height", "32", *args]) == 0
    return capsys.readouterr().out


def test_view_prints_the_framed_map_with_its_title(capsys):
    # Piped output is plain text: the title names the seed and no escape codes appear.
    out = _run_view(capsys, "--view", "terrain", "--no-legend")
    assert "seed 3" in out and "\x1b" not in out


def test_view_prints_the_legend_by_default(capsys):
    assert "LEGEND" in _run_view(capsys, "--view", "terrain")


def test_no_legend_flag_drops_the_legend(capsys):
    assert "LEGEND" not in _run_view(capsys, "--view", "terrain", "--no-legend")


def test_data_view_prints_its_ramp(capsys):
    assert "RAINFALL, MEAN ANNUAL" in _run_view(capsys, "--view", "rainfall")


def test_forced_colour_emits_escape_codes(capsys):
    assert "\x1b[" in _run_view(capsys, "--view", "terrain", "--color", "truecolor", "--no-legend")


def test_ascii_flag_keeps_the_map_to_ascii(capsys):
    out = _run_view(capsys, "--view", "terrain", "--ascii", "--no-legend")
    assert out.isascii()


def test_size_km_flag_changes_the_title_extent(capsys):
    # A 100-column map is wide enough to show the whole title (narrower maps cut it off at the border).
    out = _run_view(capsys, "--view", "terrain", "--size-km", "4000x2000", "--no-legend", "--width", "100")
    assert "4,000 x 2,000 km" in out


def test_unknown_view_exits_with_an_error(capsys):
    import pytest

    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--view", "nope"])


def test_unknown_style_exits_with_an_error():
    import pytest

    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--view", "terrain", "--style", "nope"])


def test_save_writes_text_for_a_txt_suffix(capsys, tmp_path):
    target = tmp_path / "map.txt"
    _run_view(capsys, "--view", "terrain", "--no-legend", "--save", str(target))
    assert "seed 3" in target.read_text(encoding="utf-8")


def test_save_writes_svg_for_an_svg_suffix(capsys, tmp_path):
    target = tmp_path / "map.svg"
    _run_view(capsys, "--view", "terrain", "--no-legend", "--save", str(target))
    assert target.read_text(encoding="utf-8").startswith("<svg")


def test_html_flag_writes_a_page(capsys, tmp_path):
    target = tmp_path / "map.html"
    _run_view(capsys, "--view", "terrain", "--no-legend", "--html", str(target))
    assert target.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_color_test_prints_swatches_without_generating(capsys):
    from biomegen import cli

    assert cli.main(["--color-test"]) == 0
    assert "Colour test" in capsys.readouterr().out
