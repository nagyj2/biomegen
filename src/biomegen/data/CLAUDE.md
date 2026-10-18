# data/

Attribute tables keyed by name: one row per biome, relief level, settlement tier, terrain style or
geographic feature kind, site or furniture set. Numbers that apply to the whole world (counts, budgets, thresholds) stay in
`config/defaults/`, not here.

## How they load

- `config/defaults/tables.py` reads every file in `DATA_FILES` with `tomllib` and puts each top-level
  table under the `tables` config section (`tables.biomes`, `tables.relief` from `biomes.toml`;
  `tables.detail`, `tables.detail_relief` from `detail.toml`; `tables.tiers`; `tables.styles` from `terrain.toml`;
  `tables.geo_names` from `geography.toml`; `tables.sites` from `sites.toml`; `tables.buildings` from `buildings.toml`; `tables.dress` from `dress.toml`; `tables.pois`, `tables.poi_fates`, `tables.poi_sites` and `tables.poi_styles` from `pois.toml`; `tables.furniture` from `furniture.toml`; `tables.realm_kinds`, `tables.realm_forms`,
  `tables.relation_weights` and `tables.realm_colors` from `polity.toml`; `tables.reasons` and `tables.reason_tokens` from
  `reasons.toml`; `tables.ruling_styles` from `rulers.toml`; `tables.chronicle` from `chronicle.toml`; `tables.secession_terms`,
  `tables.secession_relations` and `tables.secession_forms` from `secession.toml`; `tables.free_fates` from `pois.toml`).
- A user config overrides with the ordinary deep-merge: `[tables.biomes.desert]` + `goods = "glass"`
  changes one attribute and keeps the rest of the row.
- `config/tables.py` validates every row against its table's schema (`SCHEMAS`): unknown keys, missing
  keys and wrong kinds are errors; colours accept `[r, g, b]` or `"#rrggbb"`.
- Stages read rows through `config.get("tables.<table>.<name>.<key>")`, never by opening these files.

## Adding a row

1. Add the row with every key the file's header comment lists (only optional keys may be omitted).
2. Biome and relief rows are keyed by the lower-case enum member name in `world/tile.py`; both tables must
   have exactly one row per member, so a new biome is an enum entry plus a row (and a band rule in
   `config/defaults/biomes.py` if the classifier should produce it). Relief rows with `min_elevation_m`
   are chosen by height (highest match wins); rows without it (none, volcano) are set otherwise.
3. A new terrain style is a `styles` row; `weight = 0` keeps it out of the per-seed draw. A `geo_names`
   row needs a `forms` list whose every pattern contains `{n}` exactly once.
4. When order matters, it is a column (`rank` in tiers), never file order.
5. Run `scripts/check.sh`. A changed row that a stage reads changes the world: compare
   `scripts/fingerprint.sh` before and after.

## Sites and furniture

- `sites.toml` has one row per POI kind: its `layout`, the `furniture` set, `extent_tiles` (w, h in world tiles, below 1
  for a site smaller than a tile), `rows_per_tile` (plan resolution) and, for settlements, `plaza_tiles`, `specialized` and
  `houses` (`[min, max]` buildings, mapped from population in `sites/manifest.py` only) and the optional `walled` (a wall
  with a gate where each road arrives). A settlement or ruin is drawn from the row of its *potential*
  (`POI.potential`), so its extent, plaza, wall outline and resolution are those of the tier it could grow into. A tier that a ruin may have been
  (`tables.pois.ruin` origins) also needs `ruin_standing` and `ruin_wall_fall` ([young, old] shares of buildings standing and
  wall fallen, over `sites.ruin_erosion_years`) and `ruin_extent_share` (a factor on its extent as a ruin). Every settlement tier in `tiers.toml` and every `tables.pois` kind needs a site row to be zoomable. A camp's `purpose` picks the row
  `camp_<purpose>` (`site_row_name`).
- `furniture.toml` has weight sets nested by family then room role (`[furniture.dungeon.vault]` + `chest = 4.0`): each
  key a lower-case `Cell` name, each value a weight. A layout asks for a role per room; a missing role leaves it bare.
  `validate_tables` checks the keys and that each site row names a family that exists.

## POIs

- `pois.toml`: `pois` has one row per wild or dynamic POI kind (tower, dungeon, ruin, camp, boat, battlefield, watchtower,
  shrine); settlements are tiers. A row names where the kind comes from (`source`: `location`, `history` or `both`), its
  placement numbers (`km2_per_poi` omitted for a kind the location pass never places, spacing, biomes, score weights incl.
  `wild` and `seat_remoteness`), the events that make it (`events`, `tags`, `chance`, `min_age_years`, `holdings`,
  `per_km_of_front`, `max_per_event`, `offset_km`, the spacings), its `names` and `hooks` texts, and the simulation seams
  (`owner`, `dynamic`, `connect`, `bandit_*`, `lifespan`). The header of the file documents every key.
- `poi_fates` rows (`weight`, `sim_only`, `bandits`) are what becomes of a fallen realm's ruins; `poi_sites` rows
  (`kind`, `temper`, `land`, `min_km`, `max_km`, `connect`, score weights) are where a shrine is built, by the previous ruler's
  `temper` from `rulers.toml`. A kind with sites needs one for each temper.
- Name patterns use `{n}` once and `{fort}`; `names_fallen` (a fallen realm's capital ruin) uses `{fallen}`; `hooks` use
  `{name}` and `hooks_near` also `{near}` and need it. A kind placed by location needs `hooks`. All are checked.
- Adding a kind: a `pois` row, a `sites` row (reuse a layout until it has its own), a furniture family, a `render.markers`
  glyph and the texts. Check `scripts/fingerprint.sh`: a kind placed by location or from an event changes the world.
- The `ruin` row also has `origins` (tier -> weight, a ruin placed by location), `fall_origin` (the tier of a fallen realm's capital
  ruin) and `holding_origins` (tier -> weight, its holdings); every named tier must be a settlement tier.
- `poi_styles` rows (farm, mill, mine, lodge, fishery) place the lone building (`homestead`, a kind row with `source = "style"`
  and `marker = false`) and the generated hamlet: `generated` / `dynamic`, `grows_into` (a tier; only a style that grows makes
  hamlets), `homestead_km2_per_poi` / `hamlet_km2_per_poi` (one per this much *suited* land: eligible and scoring at least
  `min_score`), spacings, eligibility (`biomes`, `elevation_*`, `needs_freshwater_km`, `needs_coast_km`, `min_land`), the score
  weights (`near_freshwater`, `coastal`, `remoteness`, `fertility`, `relief`, `forest`, `near_settlement` and `near_road` with
  their `_km` scale), `names` and the per-kind `hooks_homestead` / `hooks_hamlet` (each with a `_near` variant). A style needs
  `hooks_homestead`, and `hooks_hamlet` when it grows; its look is a `homestead_<style>` row in `sites.toml`. Counts and
  affinities are tuned by eye on the fixture seeds; `tests/pipeline/story/test_poi_styles.py` holds the count bands.
- `free_fates` rows (`join`, `found`, `bandit`: `weight`, `sim_only`, `factors`) are what a later simulation draws for a free
  settlement; generation reads none of it.
- `tiers.toml` rows may set `free_fg` (the marker colour of a free settlement), `hooks_free` (`{name}`) and `hooks_remnant`
  (`{name}` and `{fallen}`, needed): the texts of a settlement no realm holds, and of one that outlived a fallen realm.
- `tiers.toml` rows may set `dynamic` (a later simulation mints it; the settlements stage skips it), `connect` (roads link
  it), `map_marker` (false hides the marker at the map scale) and `near_target` (false: other places' texts never name it as
  the settlement nearby and the legend leaves it out of settlement counts): the hamlet tier does all four.
- Every `tiers.toml` row needs a `centre` (a civic kind of `buildings.toml`: the building that stands at the plaza and defines a settlement
  of the tier; the plaza keeps clear the plot of the centre of the settlement's potential) and may set `potential_land` (0 to 1: the
  habitable share of the land round a site, within `sites.potential.radius_km`, it takes for the site to grow into the tier; a
  tier without it, the capital and the hamlet, is never a potential beyond what a POI already is). A `sites.toml` settlement row
  has `specialized` and `houses` (`[min, max]`, more with population, the range of the tier the settlement *is*).

## Buildings and dressings

- `buildings.toml` has one row per building kind (the header documents every key): `function` is `housing`, `production` or `civic`
  and decides the keys the row must have (`validate_tables` checks them). `rank` is unique below 64 and sets the kind's roof cell
  (`KIND_ROOF_BASE + rank`); civic kinds rank last. `rows` and `width` size a lot, `shapes`, `roles` and `furniture` its rooms, `roof`
  its look (`glyph`, `ascii`, `color`). A production kind's `suits` weights (`fertility`, `forest`, `roughness`, `fresh_water`,
  `coast`) feed `sites/surroundings.py`, with `needs_tag`, `min_score`, `max_per_kind`, `siting` (`river`, `shore`, `edge`, `any`),
  `tries` and a `dress` set. A `poi_styles` row's `building` names a production kind, a tier's `centre` a civic kind.
- `dress.toml` has one row per dressing: `variants` (each an existing `cell` or a look of its own with a `rank` below 64, a weight
  per condition `standing` and `ruin`, and optional `kinds`) and `wear` (the shares a ruin turns its cells to `void`, `rubble` or
  `overgrown`). A row may have only `wear` (a pier, a boat). A site asks for the dress for its kind in its condition, so a standing
  field is full or harvested rows and a ruin's harvested or dead.

## Politics

- `polity.toml`: `realm_kinds` has one row per kind (`major`, `city_state`, `tribal`: strength and rural population
  spans, vassal chance). `realm_forms` rows are the ways a realm is named and ruled; a row names its `kind`, a `habitat`
  (`any`, or `dry`, `cold`, `wood`, `high` to favour it, `open` as the default) and a `weight`, and each kind needs an
  `any` or `open` row. `relation_weights` (`major_pair`, `other_pair`) and `realm_colors` (saturation and value per role: major, vassal, city_state, tribal, fallen) are fixed row sets; every faction
  takes the colour farthest from the ones taken (`util/palette.py`), so no two share one.
- `reasons.toml`: `reasons` has one row per relation kind with `templates`; the tokens a template may use are checked
  (`{town}`, `{river}`, `{range}`, `{sea}` for war and rivalry; `{goods_a}`, `{goods_b}`, `{short_a}`, `{short_b}` for trade).
  `reason_tokens` gives the words used when the world lacks the place.
- Counts, budgets and distances (km) are in the `politics` config section.

## Chronicle

- `rulers.toml`: `ruling_styles` has one row per ruling style: `label` (the word the text uses), `weight` (the chance it is
  drawn) and `strength_mul` (a battle multiplier while it holds) and `temper` (`aggressive` or `passive`, which picks a shrine's site). A new
  style is a row (its `traits` are the five base personality values, 0 to 1, of a ruler of the style; a ruler draws within
  `history.ruler_trait_spread` of them); the succession rate is in the
  `history` section.

- `secession.toml`: `secession_terms` (a `weight` per term: proximity, size, age, relation, prosperity, leader, strength),
  `secession_relations` (a `score` and a wording `tag`, bitter or amicable, per relation kind and `none`) and `secession_forms`
  (a `weight` per form: offshoot, split, defection; `history.secession.chance` is the chance of the likeliest form and a form
  with weight 0 never happens). The rows are exactly these sets.
- `chronicle.toml`: `chronicle` has one row per kind of event text (`founding`, `founding_fallen`, `founding_predecessor`,
  `settling`, `settling_free`, `settling_remnant`, `secession_<offshoot|split|defection>_<bitter|amicable>`, `conquest`,
  `succession`, `war`, `war_ended`, `war_fallen`, `rivalry`, `treaty_alliance`, `treaty_trade`, `battle`, `peace`, `fall`,
  `fall_conquered`). `templates` are sentences that name no nearby place;
  `templates_near` (optional) are sentences that name one with `{near}` and must contain it. The tokens a row may use are
  listed in the file's header and checked (`{year}` is allowed everywhere); `{near}` is allowed in `templates_near` only.
- The history stage picks a template per event (`templates_near` only when a settlement qualifies, see
  `pipeline/CLAUDE.md`) and naming fills the tokens. To change a wording, edit the row; to add a token, see "Token
  resolution" in `pipeline/CLAUDE.md`.
- Counts, years and distances (km) are in the `history` config section.

## Adding a table or column

Add the schema to `config/tables.py`, the file to `DATA_FILES` if it is new, a header comment documenting
every key, and a test in `tests/config/test_tables.py`.
