"""Allow ``python -m biomegen`` (and ``uv run python -m biomegen``) to launch the CLI."""

import sys

from biomegen.cli import main

sys.exit(main())
