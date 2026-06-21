from __future__ import annotations

from cdmw.ui.research.display_preferences_state import (
    clamp_preview_zoom_factor,
    next_preview_zoom_factor,
    normalize_research_preview_color_scheme,
    normalize_research_text_highlight_style,
    normalize_research_theme_key,
    preview_zoom_label,
)


def test_research_theme_and_preview_style_helpers_normalize_invalid_values() -> None:
    assert normalize_research_theme_key("") == "graphite"
    assert normalize_research_theme_key("midnight") == "midnight"
    assert normalize_research_text_highlight_style("plain") == "plain"
    assert normalize_research_text_highlight_style("missing") == "rich"
    assert normalize_research_preview_color_scheme("vscode") == "vscode"
    assert normalize_research_preview_color_scheme("missing") == "theme"


def test_preview_zoom_helpers_clamp_and_step() -> None:
    assert clamp_preview_zoom_factor(0.01) == 0.1
    assert clamp_preview_zoom_factor(20.0) == 16.0
    assert next_preview_zoom_factor(1.0, 1) == 1.5
    assert next_preview_zoom_factor(1.0, -1) == 0.75
    assert next_preview_zoom_factor(16.0, 1) == 16.0
    assert preview_zoom_label(fit_to_view=True, zoom_factor=1.25) == "Fit"
    assert preview_zoom_label(fit_to_view=False, zoom_factor=1.25) == "125%"
