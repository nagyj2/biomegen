# Naming & lore grammar — recorded reference

The procedural names and region lore are produced by a data-driven, **mixed-per-region culture**
system. This document records the rules; the machine-readable sources are
[`biomegen/naming/cultures.py`](../biomegen/naming/cultures.py) (cultures + biome bias),
[`biomegen/naming/grammar_rules.toml`](../biomegen/naming/grammar_rules.toml) (lore sentence
templates), and [`biomegen/config/defaults.py`](../biomegen/config/defaults.py) (naming config).

Everything is deterministic and **keyed on stable entity identity** (region id, POI `(x,y)`,
river/lake canonical cell), so names never depend on processing order and reproduce from the seed.

---

## Cultures

Each region is assigned one culture, chosen by a biome-biased weighted draw seeded on
`(master_seed, "naming.culture", region_id)`. POIs, rivers, and lakes inherit the culture of the
region they sit in. The island is named from its largest region's culture.

| Culture | Feel | Settlement suffixes | Nature / fort words |
|---------|------|---------------------|---------------------|
| `common` | Familiar English-fantasy | -ton · -ham · -ford · -bury · -field · -wick · -stead | Keep · Hold · Watch · Tower |
| `norse` | Hard, weathered | -vik · -by · -stad · -heim · -fjord · -ness | Barrow · Hall · Howe · Hold |
| `elvish` | Flowing, vowel-rich | -loth · -riel · -wyn · -las · -dor · -mar · -thel | Spire · Bower · Court · Tower |
| `dwarvish` | Guttural, stony | -delf · -forge · -hold · -dim · -barim · -dum | Forge · Vault · Gate · Tower |
| `southern` | Warm, far-flung | -abad · -kar · -mir · -zah · -pur · -bad | Citadel · Ribat · Tower · Qasr |

**Biome → culture bias** (heaviest first):

| Biome | Preferred cultures |
|-------|--------------------|
| forest · jungle | elvish · southern |
| taiga | norse |
| mountain | dwarvish |
| tundra · snow | norse · dwarvish |
| desert · savanna | southern |
| grassland · shrubland · beach | common |

Biomes not in the table fall back to a uniform draw across all five cultures.

---

## Name construction

### Root generation

A bare **root** is built by one of two generators, selected per category via
`naming.generators.<category>` in config (default: `"syllable"` for all categories):

**Syllable assembly** (`naming/syllables.py`) — the default:
- Draws `onset + nucleus + coda` from the culture's phoneme sets.
- A vowel-collision guard prevents two adjacent vowels from the boundary of consecutive syllables.
- A syllable-boundary length cap ensures roots stay within `naming.min_name_len .. max_name_len`.
- Number of syllables per category: `poi` and `river`/`lake` use 1–2 syllables; `island` and
  `region` use 2–3 syllables.

**Markov** (`naming/markov.py`) — optional alternative:
- An order-N character Markov chain (`naming.markov_order`, default 2) trained on a small
  per-culture seed corpus generates phonotactically consistent names.
- The model is cached so training happens once per culture+order pair.
- Enable per category: `naming.generators.poi = "markov"`.

### Dressing — root → finished name

The root is dressed differently for each entity category:

| Category | Pattern |
|----------|---------|
| Island | `Root` or `Root Isle` (50% each) |
| Region | `Root Descriptor` (75%) or `Root` alone (25%), where *descriptor* is a biome geographic word: Wood · Vale · Peaks · Sands · Wilds · Dunes · Downs · Heath · Mire · Steppe · Reach |
| Settlement (civilized POI) | `RootSuffix` — suffix drawn from the culture's settlement list |
| Tower | `Root FortWord` or `FortWord of Root` |
| Dungeon | `Root Depths` · `Root Catacombs` · `Tomb of Root` · `Root Deep` |
| Ruin | `Ruins of Root` · `Root Ruins` · `Old Root` |
| Camp | `Root Camp` · `Root Hollow` · `Root Rest` |
| Boat | `The Root` or `Root` |
| River | `RootNatureWord` or `Root River` |
| Lake | `Lake Root` · `Root Lake` · `RootNatureWord` |

---

## Lore grammar

Region lore is 1–4 sentences (controlled by `naming.lore_min` / `naming.lore_max`), drawn from
a Tracery-style grammar defined in `grammar_rules.toml`.

### How the grammar works

1. `_sentences` lists the **top-level symbol names** to sample from: `["overview", "settlement", "water", "flavour"]`.
2. The lore stage randomly samples `lore_min..lore_max` of these symbols (without replacement).
3. Each symbol maps to a list of template strings. One template is chosen at random.
4. Within a template, `#token#` expands recursively:
   - If `token` is a grammar symbol, one of its templates is chosen and expanded.
   - Otherwise, `token` is looked up as a **pre-bound region fact** (see table below).
   - If a fact is missing or empty, a safe fallback phrase is substituted so no raw `#token#` ever
     appears in output.

### Sentence symbols

| Symbol | Templates |
|--------|-----------|
| `overview` | `"#region_name# is a #size# #biome#."` · `"The #size# #biome# of #region_name# spreads across the isle."` · `"#region_name#, a #culture_adj# #biome#, lies here."` · `"Maps mark #region_name# as a #size# #biome#."` |
| `settlement` | `"It is home to #settlement_phrase#."` · `"Within its bounds lie #settlement_phrase#."` · `"Travellers there find #settlement_phrase#."` |
| `water` | `"#water_phrase#"` |
| `flavour` | `"Folk speak of it as a #culture_adj# land."` · `"It is reckoned a #culture_adj# place."` · `"There is something #culture_adj# about its reaches."` |

### Pre-bound region facts

| Fact | Source |
|------|--------|
| `region_name` | The region's generated name |
| `biome` | Natural word for the dominant biome (e.g. "mountains", "forest", "desert") |
| `size` | Tile-count bucket: `small` (<50) · `modest` (<150) · `broad` (<400) · `vast` (≥400) |
| `culture_adj` | A flavour adjective drawn from the region's culture's adjective list |
| `settlement_phrase` | A summary of the POIs in the region (e.g. "a city and three villages, and a tower") or "no permanent settlements" |
| `water_phrase` | Adjacency summary: presence of a river, lake, or sea coast; else "No great waters cross it." |

---

## Sample names (syllable generator, seed 12345)

### `common`
- Settlements: Edirford · Bioufield · Hearthiford
- Regions: Braigurk Vale · Aimelo Vale
- Wild POIs: Moend Depths

### `norse`
- Settlements: Bjyfellheim · Graundstjaby · Bjeisnarkby
- Regions: Bjuveill Vale
- Wild POIs: Skeihjja Deep

### `elvish`
- Settlements: Lylaewyn · Vaerlyiariel · Liaglirdor
- Regions: Syiavia
- Wild POIs: Phithlya Deep

### `dwarvish`
- Settlements: Abrorundum · Boauhold · Bougrurunbarim
- Regions: Bududur Vale
- Wild POIs: Khudurdha Deep

### `southern`
- Settlements: Azhaambad · Khumhaikar · Ziarankar
- Regions: Zijiakar Vale
- Wild POIs: Miasai Deep

## Sample lore (seed 9999)

> **Elas Wilds** — "The vast forest of Elas Wilds spreads across the isle." · "Travellers there
> find a city and a village, and a tower, a ruin and three camps." · "A river threads through it." ·
> "There is something whispering about its reaches."

> **Khamirpur Dunes** — "No great waters cross it." · "Within its bounds lie no permanent
> settlements."

---

## Configuration reference (`naming.*`)

| Key | Default | Description |
|-----|---------|-------------|
| `generators.island` | `"syllable"` | Root generator for the island name |
| `generators.region` | `"syllable"` | Root generator for region names |
| `generators.poi` | `"syllable"` | Root generator for POI names |
| `generators.river` | `"syllable"` | Root generator for river names |
| `generators.lake` | `"syllable"` | Root generator for lake names |
| `markov_order` | `2` | Order of the Markov chain (when `"markov"` is selected) |
| `min_name_len` | `4` | Minimum character length for a generated root |
| `max_name_len` | `12` | Maximum character length for a generated root |
| `lore_min` | `1` | Minimum sentences generated per region |
| `lore_max` | `4` | Maximum sentences generated per region |
