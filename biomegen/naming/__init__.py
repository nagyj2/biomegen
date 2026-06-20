"""Procedural naming and lore.

A small, data-driven engine that names the island, its regions, POIs, rivers and lakes, and writes
1-4 sentences of lore per region. Naming is **mixed-per-region**: each region is assigned a *culture*
(common / norse / elvish / dwarvish / southern), biased by its dominant biome and seeded on the
region's stable id, and every name within a region is built from that culture's phonetics and affixes.
Names are keyed on stable entity identity (region id, POI coordinates, river/lake canonical cell), so
they are invariant to processing order.

- ``cultures``  : culture profiles (phonetics + affixes), biome->culture weighting, assignment.
- ``syllables`` : the syllable-assembly name generator.
- ``markov``    : an order-2 character Markov alternative generator.
- ``forge``     : the name facade (``name_entity``) used by the pipeline stage.
- ``grammar``   : a Tracery-style expansion engine for lore (rules in ``grammar_rules.toml``).
- ``lore``      : extracts region facts and renders balanced lore sentences.
"""
