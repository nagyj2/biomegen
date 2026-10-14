# interiors/

Lazy views built from a POI; interiors are never stored in the `World`.

## Contract

- `build_interior(poi, floor, config, world=None)` is a pure function of the POI's `interior_seed`, the
  floor and the config, memoised by `functools.lru_cache` on cheap scalar inputs. Same inputs, same grid.
- The cached base array is read-only. Runtime edits go through `Overlay.apply_interior` (copy-on-write).
- Floor 0 is always the ground/entry level: dungeons descend, towers ascend.
- Interiors are schematic (cells per tile from config), not km-true.
- Everything random comes from `interior_seed` (`rng.derive*`); no wall-clock or global state.

## Adding an archetype

1. Add `<kind>.py` with a builder decorated `@register_interior("<kind>")`, built on `grid.py`.
2. Import it in `interiors/__init__.py` so the registration side-effect runs.
3. Add a footprint entry for the kind in `config/defaults/interiors.py`; render and pipeline iterate the
   registry, so they need no change.
4. Add tests in `tests/interiors/` covering determinism and the kind's terrain behaviour.
