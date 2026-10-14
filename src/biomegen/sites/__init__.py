"""Sites: the plan you see when you zoom into a point of interest.

A site is a pure, lazily built view of one POI: its extent in world tiles (:mod:`.geometry`), the terrain under it
(:mod:`.patch`) and a layout of walls, streets and furniture on that terrain (:mod:`.plan`). Nothing here is stored in
the :class:`~biomegen.world.world.World`.
"""
