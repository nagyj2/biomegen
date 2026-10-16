"""The explorer's view state, camera and cursor rules (pure: no terminal I/O).

The cursor is always a world-tile coordinate ``(cx, cy)`` whatever the scale, so changing scale never has to
translate it. The camera ``(cam_x, cam_y)`` is the top-left tile of the viewport for the 1:1 map and the zoom
and local scales; the fit map ignores it. The camera only scrolls when the cursor reaches a viewport edge.

The highest zoom of a point of interest is the **site** scale: the explorer shows that POI's plan one plan cell per
terminal cell, and the cursor is one cell ``(px, py)`` of the site's window with its own camera. ``(cx, cy)`` follows
the tile under that cell, so leaving the site (moving past the window edge, or stepping out) lands on the right tile.
Everywhere that is not a POI the highest zoom is still the local scale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..config.model import Config
from ..render.fit import tile_priority
from ..sampling.detail import SCALE_LOCAL, SCALE_MAP, SCALE_SITE, SCALE_ZOOM
from ..sites import site_at, site_floor_range, site_geometry, site_plan, site_roof_floor
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


PAN_EDGE = "edge"  # controls.pan: scroll one step as the cursor reaches the margin
PAN_CENTRE = "centre"  # controls.pan: jump to centre the cursor when it reaches the margin


def pan(cam: int, cursor: int, view: int, world_size: int, margin: int, mode: str) -> int:
    """Return the camera origin after the cursor moved, following ``controls.pan`` (``mode``).

    Both modes hold the camera still while the cursor stays ``margin`` inside the viewport. At the margin, ``"edge"``
    scrolls just enough (:func:`edge_pan`); ``"centre"`` re-centres the cursor, moving about half a screen, so a pan
    redraws the whole screen once per half screen of travel instead of on every step.
    """
    inside = cam + margin <= cursor <= cam + view - 1 - margin
    if mode != PAN_CENTRE or world_size <= view or inside:
        return edge_pan(cam, cursor, view, world_size, margin)
    return clamp(cursor - view // 2, 0, world_size - view)


def pan_viewport(cam: int, cursor: int, view: int, world_size: int, margin: int, delta: int) -> tuple[int, int]:
    """Scroll the camera by ``delta`` and drag the cursor along if it would leave the viewport.

    Returns ``(camera origin, cursor)``. A world no larger than the viewport has nothing to scroll, so the camera stays.
    """
    if world_size > view:
        cam = clamp(cam + delta, 0, world_size - view)
    return cam, clamp(cursor, cam + margin, cam + view - 1 - margin)


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
        poi: The POI whose site is open at the site scale (``None`` otherwise).
        px: Cursor column in the open site's window, in plan cells.
        py: Cursor row in the open site's window.
        site_cam_x: First window column shown at the site scale.
        site_cam_y: First window row shown.
        recenter: Centre the camera on the cursor at the next draw.
        pan_x: Viewport scroll requested since the last draw, in tiles (site cells at the site scale).
        pan_y: Viewport scroll requested since the last draw, rows.
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
    poi: Optional[POI] = None
    px: int = 0
    py: int = 0
    site_cam_x: int = 0
    site_cam_y: int = 0
    recenter: bool = False
    pan_x: int = 0
    pan_y: int = 0
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


def poi_under_cursor(world: World, config: Config, state: ViewState) -> Optional[POI]:
    """Return the POI whose site the cursor is in: the open site, or the one covering the cursor's tile."""
    if state.scale == SCALE_SITE and state.poi is not None:
        return state.poi
    return site_at(world, config, state.cx, state.cy)


def sync_floor(world: World, config: Config, state: ViewState, previous: object) -> object:
    """Keep ``state.floor`` valid for the structure under the cursor and return the new tracking id.

    Entering a structure starts at its ground floor (0); moving within it keeps and clamps the chosen floor;
    leaving every structure resets to 0.
    """
    poi = poi_under_cursor(world, config, state)
    current = id(poi) if poi is not None else None
    if current != previous:
        state.floor = 0
    elif poi is not None:
        state.floor = clamp(state.floor, *site_floor_range(poi, config))
    return current


def floor_label(poi: POI, config: Config, floor: int) -> str:
    """Name a floor of a site: ``ground``, ``roofs`` (a settlement's level above its top storey) or its number."""
    if floor == 0:
        return "ground"
    return "roofs" if floor == site_roof_floor(poi, config) else str(floor)


def cycle_floor(world: World, config: Config, state: ViewState, delta: int) -> None:
    """Move up or down a floor on the structure under the cursor, or say why it cannot."""
    poi = poi_under_cursor(world, config, state)
    if poi is None:
        state.notify("no interior here - move onto a structure to cycle floors")
        return
    lowest, highest = site_floor_range(poi, config)
    if highest <= lowest:
        state.notify(f"{poi.name or poi.kind}: single floor")
        return
    new = clamp(state.floor + delta, lowest, highest)
    if new == state.floor:
        state.notify("no further floor that way")
        return
    state.floor = new
    state.notify(f"{poi.name or poi.kind}: floor {new} ({floor_label(poi, config, new)})")


def step_out(state: ViewState) -> None:
    """The zoom key steps out: site to zoom, local to zoom, zoom to map, map to zoom."""
    if state.scale == SCALE_SITE:
        _leave_site(state, SCALE_ZOOM)
        return
    state.scale = SCALE_MAP if state.scale == SCALE_ZOOM else SCALE_ZOOM
    state.recenter = True


def _enter_site(world: World, config: Config, state: ViewState, poi: POI) -> bool:
    """Open ``poi``'s site with the cursor on its anchor; False if it has no plan to show."""
    geometry = site_geometry(poi, config)
    if geometry is None or site_plan(poi, 0, config, world) is None:
        return False
    state.scale = SCALE_SITE
    state.poi = poi
    state.px, state.py = geometry.cell_at(poi.x, poi.y)
    state.floor = 0
    state.recenter = True
    state.notify(f"{poi.name or poi.kind}: inside")
    return True


def _leave_site(state: ViewState, scale: str) -> None:
    """Close the open site and show ``scale`` centred on the cursor's tile."""
    state.scale = scale
    state.poi = None
    state.recenter = True


def step_in(world: World, config: Config, state: ViewState) -> None:
    """The local key steps in: map to zoom; zoom to the site of the POI under the cursor, else local.

    From local, the key opens the site of a POI under the cursor; it does nothing elsewhere or inside a site.
    """
    if state.scale == SCALE_MAP:
        state.scale = SCALE_ZOOM
        state.recenter = True
        return
    poi = site_at(world, config, state.cx, state.cy)
    if state.scale == SCALE_ZOOM:
        if poi is None or not _enter_site(world, config, state, poi):
            state.scale = SCALE_LOCAL
            state.recenter = True
    elif state.scale == SCALE_LOCAL and poi is not None:
        _enter_site(world, config, state, poi)


def toggle_mode(state: ViewState) -> None:
    """Switch the map between fit-to-screen and 1:1 panning (map scale only)."""
    if state.scale != SCALE_MAP:
        state.notify("fit/1:1 applies to the map only")
        return
    state.mode = MODE_ONE_TO_ONE if state.mode == MODE_FIT else MODE_FIT
    if state.mode == MODE_ONE_TO_ONE:
        state.recenter = True
    state.notify(f"view: {'1:1 pan' if state.mode == MODE_ONE_TO_ONE else 'fit-to-screen'}")


def move_cursor(world: World, config: Config, state: ViewState, dx: int, dy: int) -> None:
    """Move the cursor by ``(dx, dy)``: tiles on the map scales, plan cells inside a site (leaving it at the edge)."""
    if state.scale == SCALE_SITE and state.poi is not None:
        _move_in_site(world, config, state, dx, dy)
        return
    state.cx = clamp(state.cx + dx, 0, world.width - 1)
    state.cy = clamp(state.cy + dy, 0, world.height - 1)


def pan_view(world: World, config: Config, state: ViewState, dx: int, dy: int) -> None:
    """Scroll the viewport by ``(dx, dy)``, at the next draw; the fit map has no viewport, so the cursor moves."""
    if state.scale == SCALE_MAP and state.mode == MODE_FIT:
        move_cursor(world, config, state, dx, dy)
        return
    state.pan_x += dx
    state.pan_y += dy


def _move_in_site(world: World, config: Config, state: ViewState, dx: int, dy: int) -> None:
    """Move the plan-cell cursor; stepping past the site window (or off the world) leaves for the local scale."""
    poi = state.poi
    geometry = site_geometry(poi, config) if poi is not None else None
    if poi is None or geometry is None:
        _leave_site(state, SCALE_LOCAL)
        return
    col, row = state.px + dx, state.py + dy
    x, y = geometry.position_of(col, row)
    tile_x, tile_y = round(x), round(y)
    off_window = not (0 <= col < geometry.cols and 0 <= row < geometry.rows)
    off_world = not (0 <= tile_x < world.width and 0 <= tile_y < world.height)
    if off_window or off_world:
        state.cx, state.cy = clamp(tile_x, 0, world.width - 1), clamp(tile_y, 0, world.height - 1)
        state.notify(f"left {poi.name or poi.kind}")
        _leave_site(state, SCALE_LOCAL)
        return
    state.px, state.py = col, row
    state.cx, state.cy = tile_x, tile_y
