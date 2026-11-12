"""Font sizes and layout metrics from one place (P11).

Every surface (Qt widgets, the Mesh Editor's helper, Create New Item and Mod
Management) takes its text sizes from here, so one range applies everywhere:
``UI_FONT_SIZE_MIN`` to ``UI_FONT_SIZE_MAX`` points (``cdmw.constants``).
Small and hint text is one point below its base, never below the minimum;
titles add a step on top of the base. No surface keeps a floor of its own.
"""

from __future__ import annotations

from cdmw.constants import UI_FONT_SIZE_MAX, UI_FONT_SIZE_MIN

#: Points to pixels at 100 % scaling (Qt's and Windows' 96 dpi).
_PIXELS_PER_POINT = 96.0 / 72.0


def clamp_font_points(value: object, default: int | None = None) -> int:
    """A font size in points, inside the one range; ``default`` when unreadable."""

    try:
        points = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        if default is None:
            return UI_FONT_SIZE_MIN
        points = int(default)
    return max(UI_FONT_SIZE_MIN, min(UI_FONT_SIZE_MAX, points))


def small_font_points(points: float) -> float:
    """Small and hint text: one point below ``points``, never below the minimum."""

    return max(float(UI_FONT_SIZE_MIN), float(points) - 1.0)


def title_font_points(points: float, step: float) -> float:
    """A title ``step`` points above ``points``, never below the minimum."""

    return max(float(UI_FONT_SIZE_MIN), float(points) + float(step))


def font_pixels(points: float, dpi: float = 96.0) -> int:
    """A point size in pixels at ``dpi`` (96 is 100 % scaling)."""

    return max(1, round(float(points) * float(dpi) / 72.0))


#: The smallest text any surface draws, in pixels at 100 % scaling.
MIN_FONT_PIXELS = font_pixels(UI_FONT_SIZE_MIN)


__all__ = [
    "MIN_FONT_PIXELS", "clamp_font_points", "font_pixels", "small_font_points", "title_font_points",
]
