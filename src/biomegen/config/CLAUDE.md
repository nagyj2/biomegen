# config/

Every tunable lives here. The program must run correctly with no config file at all.

## Adding a tunable

1. Add the key and its value to the matching section module in `defaults/` (one module per top-level
   section, each exposing `VALUES`; `defaults/__init__.py` assembles `DEFAULTS`). Comment units and ranges.
2. A new top-level section is a new module plus an entry in `DEFAULTS` (`tests/config/test_defaults.py`
   fails if a module is not wired in).
3. If a user would plausibly set it, show it in `config.example.toml`. The file is a sparse overlay: it may
   only name sections and keys that exist in the defaults.
4. Touch `validate.py` only when the value needs coercion (colours) or a clamp that would otherwise crash a
   stage. Validation collects every problem before raising; keep it light.

## Rules

- Read values through `Config.get("section.key")` at the call site; never import `DEFAULTS` outside `config/`.
- Callers work on copies (`get_defaults()` deep-copies); never mutate `DEFAULTS` in place.
- Precedence is CLI flag > config file > defaults. A new CLI flag overrides the merged tree in `cli.py`.
- Changing a default changes the world: say so, and compare `scripts/fingerprint.sh` before and after.
