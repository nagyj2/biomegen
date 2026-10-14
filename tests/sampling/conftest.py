"""Shared fixtures for the sampling tests."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config


@pytest.fixture(scope="module")
def config() -> Config:
    return load_config(None)
