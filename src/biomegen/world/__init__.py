"""The world data model.

- ``tile``    : the small enums stored per cell (Biome, Relief, WaterType, interior Cell) + a read accessor.
- ``world``   : the immutable ``World`` - struct-of-arrays of numpy fields plus sparse entity lists.
- ``overlay`` : the mutable ``Overlay`` - runtime/gameplay edits composited over the immutable base.
- ``entities``: dataclasses for sparse objects (POI, Region, River, Lake).
"""
