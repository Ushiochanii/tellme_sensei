"""Pure geometry helpers for placing an answer window around a watched ROI."""

from __future__ import annotations

from PySide6.QtCore import QRect


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def _intersection_area(first: QRect, second: QRect) -> int:
    intersection = first.intersected(second)
    return max(0, intersection.width()) * max(0, intersection.height())


def place_answer_window(
    window_rect: QRect,
    watched_roi: QRect,
    available_geometry: QRect,
    margin: int = 12,
) -> QRect:
    """Place a window beside ``watched_roi`` while keeping it on-screen.

    Candidates are attempted in right, left, down, up order. If no candidate
    both avoids the ROI and fits, the candidate with the least overlap wins.
    """
    if not isinstance(window_rect, QRect) or not isinstance(watched_roi, QRect):
        raise TypeError("window_rect and watched_roi must be QRect")
    if not isinstance(available_geometry, QRect):
        raise TypeError("available_geometry must be QRect")
    margin = max(0, int(margin))
    screen = available_geometry.normalized()
    width = min(max(0, window_rect.width()), max(0, screen.width()))
    height = min(max(0, window_rect.height()), max(0, screen.height()))
    max_x = screen.x() + screen.width() - width
    max_y = screen.y() + screen.height() - height

    def clamped_candidate(x: int, y: int) -> QRect:
        return QRect(_clamp(x, screen.x(), max_x), _clamp(y, screen.y(), max_y), width, height)

    directional = (
        (watched_roi.right() + 1 + margin, _clamp(watched_roi.top(), screen.y(), max_y), "x"),
        (watched_roi.left() - margin - width, _clamp(watched_roi.top(), screen.y(), max_y), "x"),
        (_clamp(watched_roi.left(), screen.x(), max_x), watched_roi.bottom() + 1 + margin, "y"),
        (_clamp(watched_roi.left(), screen.x(), max_x), watched_roi.top() - margin - height, "y"),
    )
    fallback_candidates: list[QRect] = []
    for x, y, primary_axis in directional:
        item = clamped_candidate(x, y)
        fallback_candidates.append(item)
        primary = x if primary_axis == "x" else y
        primary_limit = max_x if primary_axis == "x" else max_y
        primary_origin = screen.x() if primary_axis == "x" else screen.y()
        if primary_origin <= primary <= primary_limit and not item.intersects(watched_roi):
            return item

    fallback_candidates.extend(
        (
            QRect(screen.x(), screen.y(), width, height),
            QRect(max_x, screen.y(), width, height),
            QRect(screen.x(), max_y, width, height),
            QRect(max_x, max_y, width, height),
        )
    )
    return min(fallback_candidates, key=lambda item: _intersection_area(item, watched_roi))


__all__ = ["place_answer_window"]
