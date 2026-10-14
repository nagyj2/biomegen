#!/usr/bin/env bash
# Shared fixtures for scripts/*.sh. Source this file; do not execute it.
#
# Pins the fixture seeds and sizes so outputs are comparable between runs and between agent and user,
# runs from the repo root, and refuses to run without a named uv environment (never falls back silently).

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

if [[ -z "${UV_PROJECT_ENVIRONMENT:-}" ]]; then
    echo "error: UV_PROJECT_ENVIRONMENT is not set; point it at the biome uv environment" >&2
    echo "       e.g. export UV_PROJECT_ENVIRONMENT=~/.venvs/biome (see README, Install)" >&2
    exit 1
fi

# Default fixture seed, the extra fingerprint seeds, and a small fast world for quick checks.
fixture_seed=42
fixture_fingerprint_seeds=(42 7 1337)
fixture_small_width=64
fixture_small_height=32
build_dir="${repo_root}/build"
