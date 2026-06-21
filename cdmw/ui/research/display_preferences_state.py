"""Display preference and preview zoom state rules for the Research tab."""

from __future__ import annotations

from cdmw.constants import (
    DEFAULT_UI_LOG_TEXT_STYLE,
    DEFAULT_UI_PREVIEW_COLOR_SCHEME,
    DEFAULT_UI_THEME,
    UI_LOG_TEXT_STYLE_OPTIONS,
    UI_TEXT_COLOR_SCHEME_OPTIONS,
)

__all__ = [
    "clamp_preview_zoom_factor",
    "next_preview_zoom_factor",
    "normalize_research_preview_color_scheme",
    "normalize_research_text_highlight_style",
    "normalize_research_theme_key",
    "preview_zoom_label",
]

PREVIEW_ZOOM_STEPS = (0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0)


def normalize_research_theme_key(value: object) -> str:
    return str(value or DEFAULT_UI_THEME)


def normalize_research_text_highlight_style(value: object) -> str:
    normalized = str(value or DEFAULT_UI_LOG_TEXT_STYLE).strip().lower()
    allowed = {key for key, _label in UI_LOG_TEXT_STYLE_OPTIONS}
    return normalized if normalized in allowed else DEFAULT_UI_LOG_TEXT_STYLE


def normalize_research_preview_color_scheme(value: object) -> str:
    normalized = str(value or DEFAULT_UI_PREVIEW_COLOR_SCHEME).strip().lower()
    allowed = {key for key, _label in UI_TEXT_COLOR_SCHEME_OPTIONS}
    return normalized if normalized in allowed else DEFAULT_UI_PREVIEW_COLOR_SCHEME


def clamp_preview_zoom_factor(zoom_factor: float) -> float:
    return min(max(float(zoom_factor), PREVIEW_ZOOM_STEPS[0]), PREVIEW_ZOOM_STEPS[-1])


def next_preview_zoom_factor(current_zoom: float, step: int) -> float:
    current = clamp_preview_zoom_factor(current_zoom)
    closest_index = min(range(len(PREVIEW_ZOOM_STEPS)), key=lambda idx: abs(PREVIEW_ZOOM_STEPS[idx] - current))
    next_index = min(max(closest_index + int(step), 0), len(PREVIEW_ZOOM_STEPS) - 1)
    return PREVIEW_ZOOM_STEPS[next_index]


def preview_zoom_label(*, fit_to_view: bool, zoom_factor: float) -> str:
    return "Fit" if fit_to_view else f"{int(round(float(zoom_factor) * 100))}%"
