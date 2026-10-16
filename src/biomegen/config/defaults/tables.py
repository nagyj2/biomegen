"""Defaults for the ``tables`` section: per-name attribute tables read from ``biomegen/data/*.toml``.

Each data file contributes its top-level tables (``biomes`` and ``relief`` from ``biomes.toml``, ``detail`` and
``detail_relief`` from ``detail.toml``, ``tiers`` from ``tiers.toml``, ``styles`` from ``terrain.toml``,
``buildings`` from ``buildings.toml``, ``geo_names``
from ``geography.toml``, ``sites`` from ``sites.toml``, ``pois``, ``poi_fates``, ``poi_sites``, ``poi_styles`` and
``free_fates`` from ``pois.toml``,
``furniture`` from ``furniture.toml``, ``realm_kinds``, ``realm_forms``, ``relation_weights`` and ``realm_colors`` from
``polity.toml``, ``reasons`` and ``reason_tokens`` from ``reasons.toml``, ``ruling_styles`` from ``rulers.toml``,
``chronicle`` from ``chronicle.toml``, ``secession_terms``, ``secession_relations`` and ``secession_forms`` from
``secession.toml``) as sub-sections, so a user config overrides one attribute of one row with the
ordinary deep-merge, e.g. ``[tables.biomes.desert]`` +
``goods = "glass"``. The schema is checked by
:func:`biomegen.config.tables.validate_tables`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Dict

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# Loaded in this order; two files may not define the same table.
DATA_FILES: tuple[str, ...] = (
    "biomes.toml",
    "detail.toml",
    "tiers.toml",
    "terrain.toml",
    "geography.toml",
    "sites.toml",
    "buildings.toml",
    "pois.toml",
    "furniture.toml",
    "polity.toml",
    "reasons.toml",
    "rulers.toml",
    "chronicle.toml",
    "secession.toml",
)


def _load(data_dir: Path, files: tuple[str, ...]) -> Dict[str, Any]:
    """Read every data file and combine their top-level tables, rejecting a table defined twice."""
    tables: Dict[str, Any] = {}
    for name in files:
        with (data_dir / name).open("rb") as fh:
            for table, rows in tomllib.load(fh).items():
                if table in tables:
                    raise ValueError(f"data table {table!r} is defined twice (again in {name})")
                tables[table] = rows
    return tables


VALUES: Dict[str, Any] = _load(DATA_DIR, DATA_FILES)
