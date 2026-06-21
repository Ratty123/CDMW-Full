from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from cdmw.ui.research.preview_controls import (
    apply_preview_zoom,
    next_manual_preview_zoom,
    set_preview_image_controls_enabled,
    set_preview_zoom_label,
)


_APP = QApplication.instance() or QApplication([])


class _PreviewLabel:
    def __init__(self) -> None:
        self.fit_to_view = False
        self.zoom_factor = 0.0

    def set_fit_to_view(self, value: bool) -> None:
        self.fit_to_view = value

    def set_zoom_factor(self, value: float) -> None:
        self.zoom_factor = value


def test_preview_zoom_label_and_apply_preview_zoom() -> None:
    zoom_label = QLabel()
    preview_label = _PreviewLabel()

    set_preview_zoom_label(zoom_label, fit_to_view=True, zoom_factor=2.0)
    assert zoom_label.text() == "Fit"

    apply_preview_zoom(preview_label, zoom_label, fit_to_view=False, zoom_factor=1.5)
    assert preview_label.fit_to_view is False
    assert preview_label.zoom_factor == 1.5
    assert zoom_label.text() == "150%"


def test_preview_controls_enabled_updates_buttons_and_label() -> None:
    buttons = [QPushButton("A"), QPushButton("B")]
    zoom_label = QLabel()
    refreshed = {"value": False}

    def refresh_label() -> None:
        refreshed["value"] = True
        zoom_label.setText("refreshed")

    set_preview_image_controls_enabled(False, buttons=buttons, zoom_value_label=zoom_label, refresh_label=refresh_label)
    assert [button.isEnabled() for button in buttons] == [False, False]
    assert zoom_label.text() == "-"
    assert refreshed["value"] is False

    set_preview_image_controls_enabled(True, buttons=buttons, zoom_value_label=zoom_label, refresh_label=refresh_label)
    assert [button.isEnabled() for button in buttons] == [True, True]
    assert zoom_label.text() == "refreshed"
    assert refreshed["value"] is True


def test_next_manual_preview_zoom_uses_display_scale_for_fit_mode() -> None:
    assert next_manual_preview_zoom(current_display_scale=0.75, fit_to_view=True, zoom_factor=2.0, step=1) == 1.0
    assert next_manual_preview_zoom(current_display_scale=0.75, fit_to_view=False, zoom_factor=2.0, step=-1) == 1.5
