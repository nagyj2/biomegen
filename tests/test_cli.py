"""Tests for the command-line entry points (`python -m biomegen` and the `biomegen` console script)."""

from __future__ import annotations

import json
import re
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


def test_political_view_prints_the_realms_and_diplomacy(capsys):
    out = _run_view(capsys, "--view", "political")
    assert "REALMS" in out and "DIPLOMACY" in out and "{" not in out


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
    assert "│" in capsys.readouterr().out


def _chronicle(capsys, *args: str) -> tuple[str, str]:
    from biomegen import cli

    assert cli.main(["--seed", "3", "--width", "64", "--height", "32", "--chronicle", *args]) == 0
    captured = capsys.readouterr()
    return captured.out, captured.err


def test_chronicle_prints_a_title_and_dated_events(capsys):
    out, _ = _chronicle(capsys)
    assert out.startswith("The Chronicle of ") and re.search(r"^\s*\d+/\d\d  \S", out, re.MULTILINE)


def test_chronicle_leaves_no_token_in_the_text(capsys):
    out, _ = _chronicle(capsys)
    assert "{" not in out and "}" not in out


def test_chronicle_sends_the_seed_line_to_stderr(capsys):
    # Stdout is only the chronicle, so it can be piped or parsed.
    out, err = _chronicle(capsys)
    assert "biomegen: seed=3" in err and "biomegen: seed" not in out


def test_chronicle_json_parses_to_events_and_entities(capsys):
    out, _ = _chronicle(capsys, "--chronicle-format", "json")
    data = json.loads(out)
    assert data["seed"] == 3 and data["events"] and {"realms", "fallen_realms", "settlements"} <= set(data)


def test_unknown_chronicle_format_is_rejected(capsys):
    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--seed", "3", "--chronicle", "--chronicle-format", "xml"])
    assert "invalid choice" in capsys.readouterr().err


def test_chronicle_text_has_three_columns(capsys):
    out, _ = _chronicle(capsys)
    lines = out.splitlines()[2:]
    assert lines and all(re.fullmatch(r" *\d+/\d\d  [a-z]+ {2,}\S.*", line) for line in lines)


def test_forced_colour_colours_the_chronicle(capsys):
    out, _ = _chronicle(capsys, "--color", "truecolor")
    assert "\x1b[0;38;2;" in out


def test_no_colour_leaves_the_chronicle_plain(capsys):
    out, _ = _chronicle(capsys, "--color", "none")
    assert "\x1b" not in out


def test_the_coloured_chronicle_has_the_plain_chronicles_text(capsys):
    colored, _ = _chronicle(capsys, "--color", "truecolor")
    plain, _ = _chronicle(capsys, "--color", "none")
    assert re.sub(r"\x1b\[[0-9;]*m", "", colored).rstrip() == plain.rstrip()


def test_json_chronicle_is_never_coloured(capsys):
    out, _ = _chronicle(capsys, "--chronicle-format", "json", "--color", "truecolor")
    assert "\x1b" not in out


def _kinds(out: str) -> set[str]:
    return {line.split()[1] for line in out.splitlines()[2:] if line.strip()}


def test_the_kind_filter_lists_only_those_kinds(capsys):
    out, _ = _chronicle(capsys, "--color", "none", "--kind", "founding,war")
    assert _kinds(out) <= {"founding", "war"}


def test_kind_may_be_repeated(capsys):
    out, _ = _chronicle(capsys, "--color", "none", "--kind", "founding", "--kind", "settling")
    assert _kinds(out) == {"founding", "settling"}


def test_the_year_range_limits_the_events(capsys):
    out, _ = _chronicle(capsys, "--color", "none", "--from-year", "300", "--to-year", "400")
    years = [int(line.split()[0].split("/")[0]) for line in out.splitlines()[2:]]
    assert years and all(300 <= year <= 400 for year in years)


def test_search_keeps_matching_events(capsys):
    out, _ = _chronicle(capsys, "--color", "none", "--search", "founded")
    assert all("founded" in line.lower() for line in out.splitlines()[2:])


def test_a_filter_that_matches_nothing_says_so(capsys):
    out, _ = _chronicle(capsys, "--color", "none", "--search", "no such words anywhere")
    assert out.splitlines()[2:] == ["(no matching events)"]


def test_filtered_json_lists_only_the_matching_events(capsys):
    out, _ = _chronicle(capsys, "--chronicle-format", "json", "--kind", "founding")
    assert {event["kind"] for event in json.loads(out)["events"]} == {"founding"}


def test_an_unknown_kind_is_rejected(capsys):
    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--seed", "3", "--chronicle", "--kind", "feast"])
    assert "unknown kind feast" in capsys.readouterr().err


def test_a_reversed_year_range_is_rejected(capsys):
    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--seed", "3", "--chronicle", "--from-year", "9", "--to-year", "1"])
    assert "after --to-year" in capsys.readouterr().err


def test_chronicle_filters_need_chronicle(capsys):
    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--seed", "3", "--kind", "war"])
    assert "need --chronicle" in capsys.readouterr().err


def test_realm_matches_a_ruler_or_settlement_name_too(capsys):
    # The ruler's name is in a realm's founding line, not in the realm's own name.
    from biomegen import cli

    cli.main(["--seed", "3", "--width", "64", "--height", "32", "--headless"])
    capsys.readouterr()
    full, _ = _chronicle(capsys, "--color", "none")
    word = next(w for line in full.splitlines()[2:] for w in line.split()[2:] if w.istitle())
    narrowed, _ = _chronicle(capsys, "--color", "none", "--realm", word)
    assert narrowed.splitlines()[2:]


def test_history_flag_takes_an_optional_year():
    from biomegen import cli

    parser = cli._build_parser()
    assert (parser.parse_args([]).history, parser.parse_args(["--history"]).history) == (None, -1)
    assert parser.parse_args(["--history", "400"]).history == 400


def test_history_needs_a_terminal(capsys):
    from biomegen import cli

    with pytest.raises(SystemExit):
        cli.main(["--seed", "3", "--width", "64", "--height", "32", "--history"])
    assert "--history needs a terminal" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX pseudo-terminal")
def test_history_viewer_runs_in_a_pseudo_terminal(tmp_path):
    # Start the viewer on a pty at a year, wait for its title, press q, expect a clean exit.
    import fcntl
    import os
    import pty
    import select
    import struct
    import termios
    import time

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    env = {**os.environ, "COLORTERM": "truecolor", "TERM": "xterm-256color"}
    env.pop("NO_COLOR", None)
    process = subprocess.Popen(
        [sys.executable, "-m", "biomegen", "--seed", "3", "--history", "300"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        cwd=tmp_path,
    )
    os.close(slave)
    seen = b""
    sent_quit = False
    deadline = time.monotonic() + 90
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
            if not sent_quit and b"History of" in seen and b"year 300" in seen:
                os.write(master, b"q")
                sent_quit = True
            if process.poll() is not None and not ready:
                break
        code = process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
        os.close(master)
    assert sent_quit and code == 0


def test_sim_is_a_flag_that_is_off_by_default():
    from biomegen import cli

    parser = cli._build_parser()
    assert (parser.parse_args(["--sim"]).sim, parser.parse_args([]).sim) == (True, False)


def test_sim_runs_only_in_the_explorer(capsys):
    import pytest

    from biomegen import cli

    for other in (["--headless"], ["--view", "terrain"], ["--chronicle"], ["--scale", "zoom"]):
        with pytest.raises(SystemExit):
            cli.main(["--sim", *other])
        assert "--sim runs in the explorer" in capsys.readouterr().err
