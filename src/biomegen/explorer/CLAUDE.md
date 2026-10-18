# explorer/

The only place that reads keys or writes the screen. Frames are built by `render/` (pure); this layer owns the loop, the
key tables and the terminal.

## Rules

- **Event driven.** `app.run` composes a frame, diff-writes it, blocks on a key and repeats; idle time goes to `prefetch`. It
  must never assume the keyboard blocks: the tick seam (`ticks.py`) polls an active `TickSource` between keys. Nothing ticks
  today (`NoTicks`), so the loop blocks as before; keep it that way unless a source is active.
- **Injected I/O.** Loops take a key reader, an output stream, a size function (and a clock and sleep for ticks) so tests
  drive them with a scripted keyboard and replay the written escapes (`tests/explorer/replay.py`). A loop that opens another
  full-screen app (the history viewer from `t`) runs on the same reader and writer and invalidates the writer afterwards.
- **Keys** come from the rebindable `keys` table: add the default in `config/defaults/keys.py`, the action in `input.py`,
  the key to the controls line and help in `panel.py`, and a row in `README.md` and `config.example.toml`. A bound key beats
  the `HJKL` and `WASD` letters, so check a new letter is free (`H` is a fast move).
- **History is read through `events.py`** (`EventReader`; `ChronicleReader` reads through `world.ledger.EventLog`), never
  `World.chronicle`, so a simulation's events can join it as one list.
- **The explorer shows the present.** Time travel is the history viewer's (`--history`, `t`): it never changes the world and
  reads the map at a moment with `World.owners_at` and `build_grid(..., moment=)`. Do not give the explorer a time cursor.
- **Restart (`r`)** makes the same world again from its seed and resets view, overlay, cache, clock and the tick source
  (`TickSource.reset`); anything new that holds runtime state must reset there too.
- **Frame budget** stays 33 ms (`scripts/bench_render.sh`; judge by its pan sweep).
- **Layout holds still.** Lay a screen out so that nothing moves when data is absent or there is a lot of it (the panel, the
  history viewer, the pager and the static legend all follow this). Every region has a fixed place and height; data fills a
  region and never moves it. Concretely:
  - A field that may be absent keeps its row or column and is left blank (the hook row); never collapse it, or everything under
    it jumps as the cursor moves.
  - A list or block has a fixed number of rows (`render.legend_rows`, `render.panel_events`) and a rule for overflow: clip to the
    width, drop or scroll the rest. A block may grow past its rows only when its content needs more, and only if everything below
    is a region that can lose rows (the legend grows into the detail area).
  - Put what varies last in its region, so only the rows below it can move; put what is fixed above what varies.
  - A region only some views fill (the events, in the political view) stays blank in the others; do not reclaim its rows for
    something else that varies, so switching views moves nothing above it.
  - Test it: build the layout with the data present, absent and in excess and assert the fixed rows sit on the same row each time
    (`tests/explorer/test_panel.py`: the hook row, the legend rows, the events).
- `chronicle_pager.py` and `history_viewer.py` keep everything outside their `run_*` function pure. Both end at the present: the viewer
  always has a present stop (every event is a stop, so stepping is event to event), the pager closes its listing with a present line.
