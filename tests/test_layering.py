"""Tests for the package layering: a lower layer never imports a higher one.

The order is ``util -> config -> world -> sampling -> sites, naming -> pipeline -> sim -> render -> explorer -> cli``
(``registry`` is a leaf under them all). The imports are read from the source with ``ast``, so a violation fails here
before it can become a cycle.
"""

from __future__ import annotations

import ast
from pathlib import Path

import biomegen

SRC = Path(biomegen.__file__).parent
RANKS = {
    "registry": 0,
    "util": 1,
    "config": 2,
    "world": 3,
    "sampling": 4,
    "sites": 5,
    "naming": 5,
    "pipeline": 6,
    "sim": 7,  # the simulation sits between the pipeline and the renderer
    "render": 8,
    "explorer": 9,
    "cli": 10,
}


# Upward imports that exist on purpose: the config's validators check table rows against the world's enums and import
# them inside the functions that need them (a module-level import would be a cycle with ``world`` importing the config).
ALLOWED_UPWARD = {("config/tables.py", "world"), ("config/validate.py", "world")}


def _layer_of(path: Path) -> str:
    """The layer a source file belongs to: its top-level package, or its own name for a top-level module."""
    first = path.relative_to(SRC).parts[0]
    return first[:-3] if first.endswith(".py") else first


def _imported_layers(path: Path) -> set[str]:
    """Every layer ``path`` imports, with relative imports resolved against its package."""
    package = ["biomegen", *path.relative_to(SRC).parts[:-1]]
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            base = package[: len(package) - (node.level - 1)] if node.level else []
            parts = base + (node.module.split(".") if node.module else [])
            if parts[:1] != ["biomegen"]:
                continue
            if len(parts) == 1:  # ``from .. import x``: each name is a module of the root
                found.update(alias.name for alias in node.names)
            else:
                found.add(parts[1])
        elif isinstance(node, ast.Import):
            found.update(alias.name.split(".")[1] for alias in node.names if alias.name.startswith("biomegen."))
    return found


def _modules() -> list[Path]:
    return sorted(path for path in SRC.rglob("*.py") if _layer_of(path) in RANKS)


def test_no_module_imports_a_higher_layer() -> None:
    bad = [
        f"{path.relative_to(SRC)} ({_layer_of(path)}) imports {layer}"
        for path in _modules()
        for layer in sorted(_imported_layers(path) & RANKS.keys())
        if RANKS[layer] > RANKS[_layer_of(path)] and (path.relative_to(SRC).as_posix(), layer) not in ALLOWED_UPWARD
    ]
    assert bad == []


def test_sites_and_naming_do_not_import_each_other() -> None:
    # They share a layer, so neither may reach the other.
    bad = [
        str(path.relative_to(SRC))
        for path in _modules()
        if _layer_of(path) in ("sites", "naming") and (_imported_layers(path) & {"sites", "naming"}) - {_layer_of(path)}
    ]
    assert bad == []


def test_world_imports_only_util_and_config() -> None:
    bad = [
        f"{path.relative_to(SRC)} imports {layer}"
        for path in _modules()
        if _layer_of(path) == "world"
        for layer in sorted(_imported_layers(path) - {"world", "util", "config", "registry"})
        if layer in RANKS
    ]
    assert bad == []


def test_sites_never_import_a_simulation_package() -> None:
    bad = [
        str(path.relative_to(SRC))
        for path in _modules()
        if _layer_of(path) == "sites" and "sim" in _imported_layers(path)
    ]
    assert bad == []


def test_the_simulation_package_sits_between_the_pipeline_and_the_renderer() -> None:
    assert RANKS["pipeline"] < RANKS["sim"] < RANKS["render"]


def test_the_simulation_package_is_checked_by_the_layering_test() -> None:
    # An empty folder would pass every check above for nothing: its modules must be among the ones scanned.
    assert any(_layer_of(path) == "sim" for path in _modules())


def test_every_allowed_upward_import_still_exists() -> None:
    # An entry nothing uses any more would let a real violation in later.
    used = {
        (path.relative_to(SRC).as_posix(), layer)
        for path in _modules()
        for layer in _imported_layers(path) & RANKS.keys()
    }
    assert ALLOWED_UPWARD <= used
