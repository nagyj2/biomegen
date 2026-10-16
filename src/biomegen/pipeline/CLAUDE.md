# pipeline/

Ordered generation stages that fill an immutable `World`. `pipeline/__init__.py` (`generate`) owns the order.

## Rules

- A stage is `run(world, config, seed) -> None`. It reads only fields produced by earlier stages and writes
  only its own; there is no backtracking.
- One rng label per stage (a stage may add sub-labels, e.g. `rng.derive(seed, "terrain", "warp")`). First
  labels must be in `util.rng.LABELS`; add new ones there, never ad-hoc strings. Streams come from `rng.derive*`, never
  `random` or `numpy.random` seeded by hand, never builtin `hash()`.
- Iterate collections in a defined order (`sorted()`); dict and set order is not a contract.
- Every tunable comes from `config.get(...)`, not a literal (see `config/CLAUDE.md`).
- Folders say what a stage models: `physical/` (land and water), `civilization/` (settlements, roads, realms, diplomacy).
  `story/` holds the history and what follows from it (the chronicle, the POIs events make). `pois.py` is the location-placement
  helper the pois stage (`story/pois.py`) calls; `naming.py` stays in `pipeline/`.

## Physical stages (`physical/`)

- Order: terrain -> climate -> hydrology -> biomes -> geography. Terrain sits inside the land gate.
- Units are physical: `elevation_m` (m, < 0 = sea), `temperature_c` (°C), `rain_mm` (mm/yr), distances
  in km. Sample noise with `noise.km_grid` and measure with `geo.distance_to(..., sampling=world.scale.sampling)`
  so a different grid resolution keeps every `_km` / `_km2` tunable's meaning.
- Ranked thresholds (sea level, moisture, river share) sort with `kind="stable"`, so ties keep row-major
  order; component lists sort by size then first cell, never by labelling-backend order.
- Water: `water_type` is the truth (salt sea, fresh lake or river). A river keeps its land biome;
  `WATER_BIOMES` only says whether the cover itself is water. Old render code draws rivers through
  `render/surface.py`.
- Shared fields have documented co-owners: hydrology flattens lake surfaces in `elevation_m` and
  recomputes `rain_mm` (via `climate.rainfall_mm`) after its moisture bonus. No other stage rewrites
  an earlier stage's field.
- Per-name rows (styles, relief heights, geo name forms) are data tables; classifier numbers stay in
  `config/defaults/`. Time stages with `scripts/bench.sh` when a change could slow them.

## Civilization stages (`civilization/`)

- Order: settlements -> roads -> realms -> diplomacy -> history -> pois -> spurs -> naming. Settlements are placed first and
  every later stage counts them (spacing, remoteness, road endpoints); POIs come after history so they can follow it.
- Tiers are data (`data/tiers.toml`): placement order is `rank`, count is land km² over `land_per_settlement_km2`,
  separation is `spacing_km`, and `backbone` says whether roads join the tier into the trunk. A new tier is a row,
  not a code branch; the settlement interior builder and the render markers still need the kind registered.
- Distances are km on the anisotropic grid: use `world.scale` (`km_per_col`, `km_per_row`, `cell_area_km2`), never a
  tile count. A placement test compares km, not tiles.
- Candidates sort by score then row-major order (`argsort(kind="stable")` or `lexsort`), so equal scores never
  depend on iteration order.
- Roads route per landmass (a connected `water_type != SALT` component), so they never cross open ocean. The trunk is
  a minimum spanning tree over *every pair* of backbone settlements in km (a k-nearest graph can leave a backbone town
  out); villages branch off as spurs to the nearest road tile. A step costs its km length, over the biome and relief
  `move_cost` rows. `roads.run` links the settlements; `roads.spurs` (after the pois stage) branches every non-settlement
  POI with `POI.connect` onto that network (`roads.uncivilized_connect_prob` each, own stream, none on a landmass without a
  road). `connect` is set at commit from the kind's `tables.pois` or `tables.tiers` row (a shrine's from its `poi_sites` row).

## Politics stages (`civilization/realms.py`, `diplomacy.py`)

- Realms exist only after roads: nothing before the realms stage reads `realm_id`, and naming reads it last. POIs and
  settlements take their `realm_id` by grid lookup after realms.
- **Realm partition.** A solid cell (any non-water biome; a river keeps its land biome) belongs to at most one realm and
  water never does; `realm_id` is -1 on wild land. Realms are claimed by a strength-weighted Dijkstra over the move-cost
  surface in km, with salt water within `coastal_hop_km` as unclaimed stepping stones.
- **One seat per major realm.** Every capital founds exactly one major realm, seated in it; a city-state is seated in its
  city; a tribe takes its area's most populous settlement or none (`seat_poi` -1).
- **Deterministic Dijkstra tie-breaks.** The heap orders by (cost, cell, realm) and a cell is taken only by a strictly
  cheaper claim, so ties go to the earlier row-major frontier cell. Tribe areas sort by size, then first cell.
- **Acyclic vassal tree.** Only a realm with no vassals swears fealty (majors, smallest first, to a larger independent major;
  city-states and tribes to any neighbouring major), so a chain never loops and `World.top_realm` terminates.
- **Relations only between independent powers.** Borders are summed over each vassal tree and a relation joins two tops
  (`a < b`, at most one per pair); at least one war when any border exists. `front` marks the border cells of a war's two
  powers only. A relation's `why` is a raw template from `tables.reasons`; naming fills its tokens last.
- **Colours.** Every realm has its own colour (`diplomacy.faction_color`: farthest in CIELAB from the colours taken, at its role's
  saturation and value); fallen realms get theirs in the history stage. The chronicle shows these same colours.
- Every draw is a `diplomacy` or `realms` sub-stream drawn in a fixed order (always draw, then test, so the stream stays
  aligned); `World.realms[i].id == i`.

## Story stage (`story/history.py`)

- The chronicle is derived from the finished political state; there is no tick simulation. It runs after diplomacy and
  before naming, writes only entities (`world.chronicle`, `fallen_realms`, `founded`, `year`) and never a per-tile array, so
  the fingerprint is the same with or without it.
- **Causality.** A realm's first event is its founding or the secession that made it (a fallen realm's is its founding); a conquest, war, rivalry or treaty comes
  at least `history.min_gap_years` after both realms exist (or at the present); nothing happens to a fallen realm outside
  its life; a fall is before the present. Wars join independent, bordering powers only (they are `Relation`s), and
  a relation that follows an older war begins after its peace.
- **Rulers are records, successions mostly silent.** `rulers.py` gives a realm a ruling style that may change every
  `succession_years` and a `Ruler` per reign (the founder, then one per succession, silent ones included) with the style's
  base traits plus a draw on its own stream (`history.ruler_trait_spread`); only a style change is an event, so the chronicle
  does not fill with rulers dying. The style timeline feeds `conflicts` (a battle's odds use the style's `strength_mul` in that
  year); the present style is `Realm.ruling_style`. Texts find a ruler by realm and year (`World.ruler_at`).
- **Factions through time.** `conflicts.py` plans every battle and peace, then plays them in year order against
  per-faction strengths (a win raises, a loss lowers); a dead (fallen) faction takes no further steps. Strengths are
  tracked in the timeline, not stored on the entities.
- **Founding dates.** Realm founding years are shifted so the oldest is in `history.first_founding_year`; an event
  never comes before it.
- **Free settlements.** A free city or town (`POI.free`, never stored) has a `settling` event tagged `free`; one within
  `history.remnant_km` of a fallen realm's site on its landmass is a remnant, dated after the conflicts inside that realm's
  life, with a `settling_remnant` event and the fall event in its `event_ids`. Hooks come from the tier's `hooks_free` or
  `hooks_remnant`.
- **Secession** (`secession.py`, `founding.py`; `docs/redesign_plan.md` phase 8b). No cell moves and the
  partition, one seat per major, acyclic vassal tree and relation invariants are untouched. Order: clean splits are planned
  and applied first (touching realms of `OFFSHOOT_KINDS` share the earlier founding year, the old realm is a `Predecessor`
  with its own founding, one `secession` event replaces the two foundings), then the rulers, then offshoots and defections are
  *planned* (candidates only) and checked on the conflicts timeline in their year, reading the parent's or old owner's strength
  then; a failed check gives the ordinary founding or settling, so those events are held back until the check. The chance is
  `history.secession.chance` times the form's weight share (`form_chance`) times the score (`secession.py`, pure, shared with a
  later simulation), at most `max_per_world` in all. A realm is in at most one split; a tribe is never part of one; a realm's
  first event is its founding or its secession; an offshoot's parent is an older major realm; a split's children share its
  year; a defecting town was settled for the realm it left.
- **Ledger.** Events are collected, sorted by `(year, kind order in EVENT_KINDS, creation order)` and then numbered, so an
  event's `id` is its index. Anything added later (a simulation) has `year >= World.year`, so appending keeps the order. An id
  shifts whenever an event is added, swapped or a kind is switched off, so nothing seeded may be keyed on it: POI draws use
  `poi_rules.event_key` (the event's content).
- **Token resolution.** The stage stores a raw template and the ids it needs; `naming/chronicle.py` fills the tokens last,
  once every name exists. A template may use only its row's tokens (`config/tables.py`); a new token is a schema entry,
  a value in `naming/chronicle.py` and a test that no `{` is left in any text.
- **Locality cap.** A place named in an event comes from `places.nearest_settlement`: a settlement on the same landmass
  within `history.near_km`, else the event draws only from `templates` (never `templates_near`). The same rule governs a
  relation's reason: diplomacy keeps only templates whose `{river}`, `{range}` or `{sea}` has a feature within
  `politics.reason_near_km` of the border (`places.nearest_feature`, recorded in `Relation.places`); naming words that
  feature, never the largest in the world.
- Every draw is `rng.derive(seed, "history", ...)` keyed on the entity (realm, POI, relation, battle number, fallen realm),
  so no event depends on another's draws.
- **Decisive battles.** `conflicts.py` tags a battle `decisive` when it changes a border: the last battle of an older war
  before its peace, and the battle that conquers a fallen realm. A battlefield may mark it.
- `history.start = "dawn"` skips settlements through history and the spurs in `generate()` (`DAWN_SKIPPED`); the pois stage
  still runs, placing only `source = "both"` kinds by location. Everything that reads a world must work with no realms,
  settlements or events.

## POIs from history (`story/pois.py`, `poi_rules.py`)

- **Rule table.** `poi_rules.poi_for_event(world, config, seed, event)` is pure: it returns the `PoiPlan`s the event makes (a
  rule is when an event makes a POI; a cap is a limit on how many) from `tables.pois` rows, never placing or writing. Draws
  are `rng.derive(seed, "poi", "event", *event_key(event), kind)` in a fixed order, so a plan depends on its event alone. A later
  simulation calls it per event (`simulated=True` opens the `sim_only` fates, `now=` is its year).
- **Placement** (`story/pois.py`) walks the ledger in order and places each plan: ruins on the fallen realm's exact site plus
  holdings, battlefields, towers and dungeons on the nearest free cell round the event, watchtowers on the front, shrines in
  their site's band round the seat. Spacing is checked against the POIs placed so far (it depends on order, so it is not a
  rule). The location pass follows. New POIs append to `world.pois`; an index never moves.
- **Ruins by origin.** A ruin records `ruin_of` (the tier it was; a fall's capital ruin is `capital`, holdings and location ruins
  draw from `tables.pois.ruin` `holding_origins` and `origins`) and `pop` (the tier's range), on streams keyed on the cell; they
  move nothing. The site draws it as that tier's settlement (see `sites/CLAUDE.md`).
- **Styles pass** (`story/poi_styles.py`, last in the pois stage; none at a dawn start). A homestead (one building, `source = "style"`)
  or a generated hamlet is placed by a `tables.poi_styles` row. `style_score` is pure (`-inf` where ineligible; a simulation passes its
  own `realm_id` and `road`), `style_count` is suited land over the kind's `km2_per_poi`, `place_styles` appends: hamlets first (only
  styles that grow, each the tier's `spacing_km` from every settlement), then homesteads (held land only). It only appends, so no
  earlier POI, realm, road or event moves; streams are `rng.derive(seed, "poi", "style", style, kind, x, y)`. `pois.build_poi` builds
  a POI without a world (the simulation's seam; `commit` is `build_poi` plus the append). A hamlet tier with `near_target = false` is
  never `nearest_settlement`; post-pois counts of settlements (the legend) leave it out.
- **Event link.** A POI lists the events that made or mark it in `event_ids` (and a settlement its founding or settling event);
  an event's `poi_ids` is never appended to, because naming reads `poi_ids[0]` as a `{town}`. `World.events_at` finds events
  through both.
- **Simulation seams.** Rows carry `owner`, `dynamic`, `connect`, `bandit_strength`, `bandit_radius_km`, `lifespan`; `POI.fell`
  and `bandit_strength` are data only until a simulation reads them. No simulation code lives here.

## Adding a stage

1. Create the module with `run(...)`, add its label to `LABELS`, call it in `generate()` at the right point.
2. Add a test under `tests/pipeline/` mirroring the module, plus a stats entry if it adds countable output.
3. Update the stage list in `docs/ARCHITECTURE.md`.
4. Run `scripts/fingerprint.sh` before and after and explain every change.
