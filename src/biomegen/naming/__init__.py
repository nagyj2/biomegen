"""Procedural naming.

A small, data-driven engine that names the island, its realms, rulers, POIs, rivers, lakes and geographic features.
Naming is **mixed-per-realm**: each realm is assigned a *culture* (common / norse / elvish / dwarvish / southern),
biased by its dominant biome and seeded on the realm's stable id, and every name within a realm is built from that
culture's phonetics and affixes. Names are keyed on stable entity identity (realm id, POI coordinates, river/lake
canonical cell), so they are invariant to processing order.

- ``cultures``  : culture profiles (phonetics + affixes), biome->culture weighting, assignment.
- ``syllables`` : the syllable-assembly name generator.
- ``markov``    : an order-2 character Markov alternative generator.
- ``forge``     : the name facade (``name_entity``, ``name_feature``) used by the pipeline stage.
- ``polity``    : realm names, rulers and the wording of relation reasons.
"""
