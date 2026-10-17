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
- **History is read through `events.py`** (`EventReader`), never `World.chronicle`, so a simulation's ledger can join it.
- **The explorer shows the present.** Time travel is the history viewer's (`--history`, `t`): it never changes the world and
  reads the map at a moment with `World.owners_at` and `build_grid(..., moment=)`. Do not give the explorer a time cursor.
- **Restart (`r`)** makes the same world again from its seed and resets view, overlay, cache, clock and the tick source
  (`TickSource.reset`); anything new that holds runtime state must reset there too.
- **Frame budget** stays 33 ms (`scripts/bench_render.sh`; judge by its pan sweep).
- `chronicle_pager.py` and `history_viewer.py` keep everything outside their `run_*` function pure.
