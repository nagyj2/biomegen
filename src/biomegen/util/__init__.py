"""Cross-cutting utilities shared by every subsystem.

- ``rng``      : the determinism anchor - derives independent, reproducible random streams from one
                 master seed via blake2b (never Python's per-process-salted ``hash()``).
- ``noise``    : selectable noise backends + fractal Brownian motion + domain warping.
- ``geometry`` : shared spatial primitives (neighbours, connected components, distance transforms, A*).
"""
