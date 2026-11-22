"""Pure geometry and formatting helpers for the floating bubble and preview panel.

Kept free of Qt imports so all positioning math is fast and unit-testable headless.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DockEdge = Literal["left", "right"] | None


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def center_x(self) -> int:
        return self.x + self.w // 2

    @property
    def center_y(self) -> int:
        return self.y + self.h // 2


def format_badge(count: int, more: bool = False) -> str:
    """Format the unread counter for the bubble badge (empty string when 0)."""
    if count <= 0:
        return ""
    if count > 99 or (more and count >= 99):
        return "99+"
    return f"{count}+" if more else str(count)


def clamp_bubble_pos(
    x: int,
    y: int,
    bubble_w: int,
    bubble_h: int,
    screen: Rect,
    margin: int = 8,
) -> tuple[int, int]:
    """Clamp bubble top-left coordinates within ``screen`` with a safety margin."""
    min_x = screen.x + margin
    max_x = max(min_x, screen.right - bubble_w - margin)
    min_y = screen.y + margin
    max_y = max(min_y, screen.bottom - bubble_h - margin)
    return (
        max(min_x, min(x, max_x)),
        max(min_y, min(y, max_y)),
    )


def default_bubble_pos(
    bubble_w: int,
    bubble_h: int,
    screen: Rect,
    margin_x: int = 20,
    margin_y: int = 24,
) -> tuple[int, int]:
    """Default top-right position matching the desktop chat-head mockup."""
    return (
        max(screen.x + 8, screen.right - bubble_w - margin_x),
        screen.y + margin_y,
    )


def detect_dock_edge(
    x: int,
    bubble_w: int,
    screen: Rect,
    threshold: int = 28,
) -> DockEdge:
    """Return 'left' or 'right' if the bubble is close enough to snap to a screen edge."""
    if x - screen.x <= threshold:
        return "left"
    if screen.right - (x + bubble_w) <= threshold:
        return "right"
    return None


def docked_bubble_x(
    edge: DockEdge,
    current_x: int,
    bubble_w: int,
    screen: Rect,
    *,
    peek: int = 22,
    expanded: bool = False,
    margin: int = 10,
) -> int:
    """Compute target X coordinate for a docked bubble (peeking vs expanded)."""
    if edge == "right":
        if expanded:
            return screen.right - bubble_w - margin
        return screen.right - max(12, min(peek, bubble_w))
    if edge == "left":
        if expanded:
            return screen.x + margin
        return screen.x - bubble_w + max(12, min(peek, bubble_w))
    return current_x


def compute_panel_pos(
    bubble: Rect,
    panel_w: int,
    panel_h: int,
    screen: Rect,
    *,
    gap: int = 8,
    margin: int = 10,
) -> tuple[int, int]:
    """Anchor the preview panel cleanly next to the bubble without clipping off-screen."""
    # Horizontal alignment: right-align when bubble is on the right half, else left-align.
    x = bubble.right - panel_w if bubble.center_x >= screen.center_x else bubble.x

    min_x = screen.x + margin
    max_x = max(min_x, screen.right - panel_w - margin)
    x = max(min_x, min(x, max_x))

    # Vertical alignment: prefer below the bubble; flip above if it would clip the bottom.
    below_y = bubble.bottom + gap
    above_y = bubble.y - panel_h - gap
    if below_y + panel_h <= screen.bottom - margin:
        y = below_y
    elif above_y >= screen.y + margin:
        y = above_y
    else:
        min_y = screen.y + margin
        max_y = max(min_y, screen.bottom - panel_h - margin)
        y = max(min_y, min(below_y, max_y))

    return x, y
