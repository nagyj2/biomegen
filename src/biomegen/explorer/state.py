"""The explorer's view state, camera and cursor rules (pure: no terminal I/O).

The cursor is always a world-tile coordinate ``(cx, cy)`` whatever the scale, so changing scale never has to
translate it. The camera ``(cam_x, cam_y)`` is the top-left tile of the viewport for the 1:1 map and the zoom
and local scales; the fit map ignores it. The camera only scrolls when the cursor reaches a viewport edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..config.model import Config
from ..interiors import INTERIOR_BUILDERS, footprint_origin
from ..render.fit import tile_priority
from ..sampling.detail import SCALE_LOCAL, SCALE_MAP, SCALE_ZOOM
from ..world.entities import POI
from ..world.tile import WaterType
from ..world.world import World

MODE_FIT = "fit"  # the map scaled down to fit the screen
MODE_ONE_TO_ONE = "onetoone"  # the map at one cell per tile, panned by the camera
_MAX_MESSAGES = 8


def clamp(value: int, low: int, high: int) -> int:
    """Clamp ``value`` into ``[low, high]``; a range with ``high < low`` gives ``low``."""
    if high < low:
        return low
    return max(low, min(high, value))


def edge_pan(cam: int, cursor: int, view: int, world_size: int, margin: int = 1) -> int:
    """Return the camera origin that keeps ``cursor`` within ``margin`` tiles of the viewport edges.

    The camera holds still until the cursor comes within ``margin`` of an edge, then scrolls to follow. A world
    smaller than the viewport is centred (a negative origin).
    """
    if world_size <= view:
        return -((view - world_size) // 2)
    if cursor < cam + margin:
        cam = cursor - margin
    elif cursor > cam + view - 1 - margin:
        cam = cursor - (view - 1 - margin)
    return clamp(cam, 0, world_size - view)


@dataclass
class ViewState:
    """Mutable explorer state driven by the input loop.

    Attributes:
        cx: Cursor tile column.
        cy: Cursor tile row.
        mode: ``"fit"`` or ``"onetoone"`` (applies to the map scale only).
        scale: ``"map"``, ``"zoom"`` or ``"local"``.
        view_index: Index into the configured view names (the ``v`` key cycles it).
        cam_x: Viewport top-left tile column (1:1, zoom and local).
        cam_y: Viewport top-left tile row.
        floor: Current floor when the cursor is on a multi-floor structure.
        recenter: Centre the camera on the cursor at the next draw.
        messages: Recent status messages, newest last.
    """

    cx: int = 0
    cy: int = 0
    mode: str = MODE_FIT
    scale: str = SCALE_MAP
    view_index: int = 0
    cam_x: int = 0
    cam_y: int = 0
    floor: int = 0
    recenter: bool = False
    messages: list[str] = field(default_factory=list)

    @property
    def is_detail(self) -> bool:
        """True when a magnified scale (zoom or local) is active."""
        return self.scale != SCALE_MAP

    @property
    def last_message(self) -> str:
        return self.messages[-1] if self.messages else ""

    def notify(self, text: str) -> None:
        """Record a status message (the panel shows the most recent)."""
        self.messages.append(text)
        if len(self.messages) > _MAX_MESSAGES:
            self.messages.pop(0)


def initial_cursor(world: World, config: Config) -> tuple[int, int]:
    """Return the land tile with the most salient feature, nearest the land's centre (the map centre if no land).

    Salience is the fit-map priority (point of interest, road, river, notable terrain), restricted to land so the
    cursor never starts on open water.
    """
    land = world.water_type == int(WaterType.NONE)
    if not land.any():
        return world.width // 2, world.height // 2
    priority = np.where(land, tile_priority(world, config), -1)
    candidates_y, candidates_x = np.nonzero(priority == priority.max())
    land_y, land_x = np.nonzero(land)
    centre_x, centre_y = float(land_x.mean()), float(land_y.mean())
    nearest = int(np.argmin((candidates_x - centre_x) ** 2 + (candidates_y - centre_y) ** 2))
    return int(candidates_x[nearest]), int(candidates_y[nearest])


def poi_under_cursor(world: World, state: ViewState) -> Optional[POI]:
    """Return the interior-bearing POI whose footprint covers the cursor, or ``None``.

    Footprints come from the POI list (``poi_index`` only marks anchors), so this drives floor cycling: the
    cursor is "inside" a structure anywhere on its footprint.
    """
    for poi in world.pois:
        if not INTERIOR_BUILDERS.has(poi.kind):
            continue
        width, height = poi.footprint
        if width <= 0 or height <= 0:
            continue
        left, top = footprint_origin(poi)
        if left <= state.cx < left + width and top <= state.cy < top + height:
            return poi
    return None


def sync_floor(world: World, state: ViewState, previous: object) -> object:
    """Keep ``state.floor`` valid for the structure under the cursor and return the new tracking id.

    Entering a structure starts at its ground floor (0); moving within it keeps and clamps the chosen floor;
    leaving every structure resets to 0.
    """
    poi = poi_under_cursor(world, state)
    current = id(poi) if poi is not None else None
    if current != previous:
        state.floor = 0
    elif poi is not None:
        state.floor = clamp(state.floor, poi.lowest_floor, poi.lowest_floor + poi.floor_count - 1)
    return current


def cycle_floor(world: World, state: ViewState, delta: int) -> None:
    """Move up or down a floor on the structure under the cursor, or say why it cannot."""
    poi = poi_under_cursor(world, state)
    if poi is None:
        state.notify("no interior here - move onto a structure to cycle floors")
        return
    if poi.floor_count <= 1:
        state.notify(f"{poi.name or poi.kind}: single floor")
        return
    new = clamp(state.floor + delta, poi.lowest_floor, poi.lowest_floor + poi.floor_count - 1)
    if new == state.floor:
        state.notify("no further floor that way")
        return
    state.floor = new
    state.notify(f"{poi.name or poi.kind}: floor {new} ({'ground' if new == 0 else new})")


def step_out(state: ViewState) -> None:
    """The zoom key steps out: map to zoom, zoom to map, local to zoom."""
    state.scale = SCALE_MAP if state.scale == SCALE_ZOOM else SCALE_ZOOM
    state.recenter = True


def step_in(state: ViewState) -> None:
    """The local key steps in: map to zoom, zoom to local, local stays."""
    if state.scale == SCALE_MAP:
        state.scale = SCALE_ZOOM
        state.recenter = True
    elif state.scale == SCALE_ZOOM:
        state.scale = SCALE_LOCAL
        state.recenter = True


def toggle_mode(state: ViewState) -> None:
    """Switch the map between fit-to-screen and 1:1 panning (map scale only)."""
    if state.scale != SCALE_MAP:
        state.notify("fit/1:1 applies to the map only")
        return
    state.mode = MODE_ONE_TO_ONE if state.mode == MODE_FIT else MODE_FIT
    if state.mode == MODE_ONE_TO_ONE:
        state.recenter = True
    state.notify(f"view: {'1:1 pan' if state.mode == MODE_ONE_TO_ONE else 'fit-to-screen'}")


def move_cursor(world: World, state: ViewState, dx: int, dy: int) -> None:
    """Move the cursor by ``(dx, dy)`` tiles, staying inside the world."""
    state.cx = clamp(state.cx + dx, 0, world.width - 1)
    state.cy = clamp(state.cy + dy, 0, world.height - 1)
