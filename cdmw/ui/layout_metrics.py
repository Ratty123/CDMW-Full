"""Font sizes and layout metrics from one place (P11 steps 2 and 4).

Every surface (Qt widgets, the Mesh Editor's helper, Create New Item and Mod
Management) takes its text sizes from here, so one range applies everywhere:
``UI_FONT_SIZE_MIN`` to ``UI_FONT_SIZE_MAX`` points (``cdmw.constants``).
Small and hint text is one point below its base, never below the minimum;
titles add a step on top of the base. No surface keeps a floor of its own.
"""

from __future__ import annotations

from dataclasses import dataclass

from cdmw.constants import UI_FONT_SIZE_MAX, UI_FONT_SIZE_MIN

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


# ----- spacing (P11 step 4) ------------------------------------------------------

#: Next's compact metrics, in pixels at 100 %: the starting point for Compact.
_COMPACT = {
    "window_pad": (7, 6),
    "frame_pad": (5, 3),
    "item_spacing": (6, 4),
    "inner_spacing": (4, 3),
    "indent": 12,
    "scrollbar": 11,
    "rounding": 2,
}
#: Spacing grows with density; text does not. Comfortable is Next's "Detailed".
_SPACING_FACTOR = {"compact": 1.0, "normal": 1.25, "comfortable": 1.5}
_SCROLLBAR_FACTOR = {"compact": 1.0, "normal": 1.125, "comfortable": 1.25}
#: The screen's own factor (small screens tighter, large ones a little looser).
_SCREEN_SCALE_RANGE = (0.72, 1.15)


@dataclass(frozen=True)
class LayoutMetrics:
    """Spacing for one density, text size and screen, in pixels."""

    density: str
    font_pixels: int
    window_pad: tuple[int, int]
    frame_pad: tuple[int, int]
    item_spacing: tuple[int, int]
    inner_spacing: tuple[int, int]
    indent: int
    scrollbar: int
    rounding: int
    #: A control's height: its text and its frame padding above and below.
    control_height: int

    def payload(self) -> dict[str, object]:
        """For the helper's theme: the same values the Qt stylesheet uses."""

        return {
            "density": self.density,
            "font_pixels": self.font_pixels,
            "window_pad": list(self.window_pad),
            "frame_pad": list(self.frame_pad),
            "item_spacing": list(self.item_spacing),
            "inner_spacing": list(self.inner_spacing),
            "indent": self.indent,
            "scrollbar": self.scrollbar,
            "rounding": self.rounding,
            "control_height": self.control_height,
        }


def _density(value: object) -> str:
    key = str(value or "compact").strip().lower()
    return key if key in _SPACING_FACTOR else "compact"


def layout_metrics(density: object = "compact", font_points: float = 10.0, screen_scale: float = 1.0) -> LayoutMetrics:
    """The metrics for ``density`` (Compact, Normal or Comfortable), a text size and a screen."""

    key = _density(density)
    low, high = _SCREEN_SCALE_RANGE
    screen = max(low, min(high, float(screen_scale or 1.0)))
    spacing = _SPACING_FACTOR[key] * screen

    def pair(name: str) -> tuple[int, int]:
        x, y = _COMPACT[name]
        return (max(1, round(x * spacing)), max(1, round(y * spacing)))

    text = font_pixels(clamp_font_points(font_points))
    frame_pad = pair("frame_pad")
    return LayoutMetrics(
        density=key,
        font_pixels=text,
        window_pad=pair("window_pad"),
        frame_pad=frame_pad,
        item_spacing=pair("item_spacing"),
        inner_spacing=pair("inner_spacing"),
        indent=max(1, round(_COMPACT["indent"] * spacing)),
        scrollbar=max(6, round(_COMPACT["scrollbar"] * _SCROLLBAR_FACTOR[key] * screen)),
        rounding=_COMPACT["rounding"],
        control_height=text + 2 * frame_pad[1],
    )


def stylesheet_metrics(metrics: LayoutMetrics) -> dict[str, int]:
    """The Qt stylesheet's paddings and minimum heights, derived from ``metrics``.

    At Compact, 10 pt and 100 % these reproduce the values the stylesheet used
    before (P11 step 4 moved where they come from, not what they are).
    """

    window_x, window_y = metrics.window_pad
    frame_x, frame_y = metrics.frame_pad
    item_x, item_y = metrics.item_spacing
    inner_x, inner_y = metrics.inner_spacing
    button_min = metrics.font_pixels + frame_y
    return {
        "menu_pad_y": frame_y,
        "menu_pad_x": window_x + 1,
        "menu_item_pad_y": inner_y + 1,
        "menu_item_pad_x": window_x + 2,
        "group_margin_top": round(metrics.font_pixels * 0.75) + item_y - 1,
        "group_pad_top": window_y + 2,
        "group_title_pad_y": 0,
        "group_title_pad_x": window_x - 1,
        "section_pad_y": frame_y + 2,
        "section_pad_x": window_x + 1,
        "field_pad_y": frame_y + 1,
        "field_pad_x": window_x,
        "list_pad_y": max(0, inner_y - 1),
        "list_pad_x": frame_x,
        "header_pad_y": inner_y + 1,
        "header_pad_x": item_x,
        "button_pad_y": frame_y + 1,
        "button_pad_x": window_x + 1,
        "button_min_h": button_min,
        "progress_min_h": button_min + 2,
        "tab_pad_top": frame_y + 2,
        "tab_pad_bottom": frame_y + 3,
        "tab_pad_x": window_x + 3,
        "tab_min_h": button_min + 2,
    }


__all__ = [
    "LayoutMetrics", "MIN_FONT_PIXELS", "clamp_font_points", "font_pixels", "layout_metrics",
    "small_font_points", "stylesheet_metrics", "title_font_points",
]
