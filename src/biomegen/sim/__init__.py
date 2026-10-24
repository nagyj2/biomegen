"""The tick simulation: it plays the finished present world forward (observer only, deterministic, data driven).

State dataclasses live in ``world/`` (``SimState`` and the readers); the logic is here. The layer sits between
``pipeline`` and ``render`` (it may read the world, sites, naming and the pipeline's pure helpers, and never imports
``render`` or ``explorer``). See ``docs/simulation_plan.md`` and ``CLAUDE.md`` in this folder.
"""
