"""Data-driven configuration.

The single control surface for the whole generator. A nested in-code :data:`~biomegen.config.defaults.DEFAULTS`
dict holds an authoritative default for *every* tunable, so the app always runs with no config file.
A user TOML file (parsed by stdlib :mod:`tomllib`) is treated as a *sparse overlay*: only the keys
the user wants to change need appear, and they are deep-merged onto a copy of the defaults. The
merged tree is validated/coerced and wrapped in a frozen :class:`~biomegen.config.model.Config` that
exposes dotted-path access (``config.get("terrain.octaves")``).
"""

from .loader import load_config
from .model import Config

__all__ = ["load_config", "Config"]
