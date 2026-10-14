#!/usr/bin/env bash
# Launch the interactive app on the fixture seed. Extra arguments go to biomegen and may override --seed.
source "$(dirname "${BASH_SOURCE[0]}")/_fixtures.sh"

uv run biomegen --seed "${fixture_seed}" "$@"
