"""Tests for the command-line entry points (`python -m biomegen` and the `biomegen` console script)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

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


def test_zoom_prints_the_bare_grid_without_frame_or_legend(capsys):
    # A zoomed view is just cells: no title, no legend, no escape codes when piped.
    out = _run_view(capsys, "--scale", "zoom", "--at", "20,10")
    assert "seed 3" not in out and "LEGEND" not in out and "\x1b" not in out


def test_local_view_is_ascii_with_the_flag(capsys):
    assert _run_view(capsys, "--scale", "local", "--ascii").isascii()


def test_zoom_view_is_repeatable(capsys):
    first = _run_view(capsys, "--scale", "zoom", "--at", "20,10")
    assert first == _run_view(capsys, "--scale", "zoom", "--at", "20,10")


def test_zoom_can_draw_a_data_view(capsys):
    assert _run_view(capsys, "--scale", "zoom", "--view", "elevation", "--color", "truecolor").count("\x1b[") > 10


def test_scale_map_is_the_whole_world_map(capsys):
    assert "seed 3" in _run_view(capsys, "--scale", "map", "--view", "terrain", "--no-legend")


def test_zoom_view_saves_to_the_suffix_back_end(capsys, tmp_path):
    target = tmp_path / "zoom.svg"
    _run_view(capsys, "--scale", "zoom", "--save", str(target))
    assert target.read_text(encoding="utf-8").startswith("<svg")


def test_at_without_a_detail_scale_is_an_error(capsys):
    import pytest

    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--view", "terrain", "--at", "5,5"])
    assert "--at needs --scale" in capsys.readouterr().err


def test_at_outside_the_world_is_an_error(capsys):
    import pytest

    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--seed", "3", "--width", "64", "--height", "32", "--scale", "zoom", "--at", "99,5"])
    assert "outside the 64x32 world" in capsys.readouterr().err


def test_malformed_tile_is_an_error(capsys):
    import pytest

    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--scale", "zoom", "--at", "five"])
    assert "column,row" in capsys.readouterr().err


def test_explorer_needs_a_terminal(capsys):
    # With output captured (not a TTY) the explorer refuses and points at the scripted options.
    import pytest

    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--seed", "3", "--width", "64", "--height", "32"])
    assert "needs a terminal" in capsys.readouterr().err


def test_removed_preview_flags_are_rejected(capsys):
    import pytest

    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--preview-zoom"])
    assert "unrecognized arguments" in capsys.readouterr().err


def test_removed_export_flag_is_rejected(capsys):
    import pytest

    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--export", "world"])
    assert "unrecognized arguments" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX pseudo-terminal")
def test_explorer_runs_in_a_pseudo_terminal(tmp_path):
    # The real thing end to end: start the app on a pty, wait for its first frame, press q, expect a clean exit.
    import fcntl
    import os
    import pty
    import select
    import struct
    import termios
    import time

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 100, 0, 0))
    env = {**os.environ, "COLORTERM": "truecolor", "TERM": "xterm-256color"}
    env.pop("NO_COLOR", None)
    process = subprocess.Popen(
        [sys.executable, "-m", "biomegen", "--seed", "3", "--width", "64", "--height", "32"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        cwd=tmp_path,
    )
    os.close(slave)
    seen = b""
    sent_quit = False
    deadline = time.monotonic() + 60
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.5)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                seen += chunk
            if not sent_quit and b"seed 3" in seen and b"\x1b[?1049h" in seen:
                os.write(master, b"q")
                sent_quit = True
            if process.poll() is not None and not ready:
                break
        code = process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
        os.close(master)
    assert (code, sent_quit, b"\x1b[?1049l" in seen) == (0, True, True)


def test_site_scale_needs_a_tile(capsys):
    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--seed", "3", "--width", "64", "--height", "32", "--scale", "site"])
    assert "--scale site needs --at" in capsys.readouterr().err


def test_site_scale_on_a_tile_without_a_poi_is_an_error(capsys):
    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--seed", "3", "--width", "64", "--height", "32", "--scale", "site", "--at", "0,0"])
    assert "no site at tile 0,0" in capsys.readouterr().err


def test_site_scale_draws_a_poi(capsys):
    from biomegen import cli

    config = load_config(None)
    config.data["world"]["width"], config.data["world"]["height"] = 64, 32
    world = pipeline.generate(config, 3)
    poi = next(p for p in world.pois if p.kind in ("village", "town", "city", "capital"))
    assert (
        cli.main(["--seed", "3", "--width", "64", "--height", "32", "--scale", "site", "--at", f"{poi.x},{poi.y}"]) == 0
    )
    assert "#" in capsys.readouterr().out
