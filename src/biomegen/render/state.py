"""The interactive view state and the camera helpers that keep the cursor on screen.

The cursor is always a **biome-tile coordinate** ``(cx, cy)`` regardless of view mode (fit / 1:1 /
zoom), which makes toggling views trivial - the cursor never has to be translated. The camera
``(cam_x, cam_y)`` is the top-left biome tile of the viewport for the 1:1 and zoom views; fit mode
ignores it (the whole map is shown).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


def clamp(value: int, lo: int, hi: int) -> int:
    """Clamp ``value`` into the inclusive range [lo, hi] (hi may be < lo -> returns lo)."""
    if hi < lo:
        return lo
    return max(lo, min(hi, value))


def center_cam(cursor: int, view: int, world_size: int) -> int:
    """Return a camera origin that centres ``cursor`` in a ``view``-wide window, clamped to the world.

    Used when *entering* the zoomed view so the tile you zoomed on lands in the middle of the screen
    (rather than wherever the previous camera happened to sit).
    """
    if world_size <= view:
        return -((view - world_size) // 2)
    return clamp(cursor - view // 2, 0, world_size - view)


def edge_pan(cam: int, cursor: int, view: int, world_size: int, margin: int = 1) -> int:
    """Return a new camera origin that keeps ``cursor`` within ``margin`` of the viewport edges.

    This is the "pan only when the cursor reaches the edge" behaviour: the camera holds still until
    the cursor comes within ``margin`` cells of an edge, then scrolls to follow. If the world is
    smaller than the viewport the content is centred (a negative origin -> letterboxing).
    """
    if world_size <= view:
        return -((view - world_size) // 2)  # centre, leaving equal margins
    if cursor < cam + margin:
        cam = cursor - margin
    elif cursor > cam + view - 1 - margin:
        cam = cursor - (view - 1 - margin)
    return clamp(cam, 0, world_size - view)


# The three view scales, from most zoomed-out to most zoomed-in.
SCALE_BIOME = "biome"  # the whole-island biome map (fit or 1:1 panning)
SCALE_ZOOM = "zoom"  # mid detail: each biome tile -> a small (zoom_scale) grid
SCALE_LOCAL = "local"  # close detail: the screen shows ~a handful of biome tiles, heavily magnified


@dataclass
class ViewState:
    """Mutable UI state driven by the input loop."""

    cx: int = 0  # cursor world tile
    cy: int = 0
    mode: str = "fit"  # biome-scale rendering: "fit" or "onetoone"
    scale: str = SCALE_BIOME  # which of the three view scales is active
    cam_x: int = 0  # viewport top-left biome tile (1:1, zoom, local views)
    cam_y: int = 0
    floor: int = 0  # current floor when standing on a multi-floor POI (Phase 5)
    recenter: bool = False  # request: centre the camera on the cursor on the next draw
    messages: List[str] = field(default_factory=list)

    @property
    def is_detail(self) -> bool:
        """True when a magnified detail view (zoom or local) is active."""
        return self.scale != SCALE_BIOME

    def notify(self, text: str) -> None:
        """Record a status message (the HUD shows the most recent)."""
        self.messages.append(text)
        if len(self.messages) > 8:
            self.messages.pop(0)

    @property
    def last_message(self) -> str:
        return self.messages[-1] if self.messages else ""
