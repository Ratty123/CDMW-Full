from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from cdmw.ui.research.help_widgets import (
    add_help_row,
    add_titled_help_header,
    make_research_help_button,
    set_help_button_text,
    wrapped_help_tooltip,
)
from cdmw.ui.research.progress_helpers import (
    set_progress_error,
    set_progress_idle,
    set_progress_ready,
    set_research_progress,
)
from cdmw.ui.research.preview_controls import (
    apply_preview_zoom,
    next_manual_preview_zoom,
    set_preview_image_controls_enabled,
    set_preview_zoom_label,
)


_APP = QApplication.instance() or QApplication([])


def test_wrapped_help_tooltip_escapes_and_wraps_text() -> None:
    tooltip = wrapped_help_tooltip("Use <safe>\nhelp", width=420)

    assert "width: 420px" in tooltip
    assert "Use &lt;safe&gt;<br>help" in tooltip


def test_make_and_update_research_help_button_contract() -> None:
    button = make_research_help_button("First")

    assert button.text() == "?"
    assert "width: 380px" in button.toolTip()
    assert button.cursor().shape() == Qt.WhatsThisCursor
    assert button.autoRaise() is True
    assert button.width() == 22
    assert button.height() == 22

    set_help_button_text(button, "Second")
    assert "Second" in button.toolTip()


def test_help_row_builders_add_expected_container_rows() -> None:
    parent = QWidget()
    layout = QVBoxLayout(parent)

    add_help_row(layout, "Help row")
    add_titled_help_header(layout, "Title", "Header help")

    assert layout.count() == 2
    assert layout.itemAt(0).widget() is not None
    assert layout.itemAt(1).widget() is not None


def test_set_research_progress_clamps_and_formats_determinate_progress() -> None:
    progress = QProgressBar()

    safe_current = set_research_progress(progress, 15, 10)

    assert safe_current == 10
    assert progress.minimum() == 0
    assert progress.maximum() == 10
    assert progress.value() == 10
    assert progress.format() == "10 / 10"


def test_set_research_progress_marks_indeterminate_work() -> None:
    progress = QProgressBar()

    safe_current = set_research_progress(progress, 1, 0)

    assert safe_current == 0
    assert progress.minimum() == 0
    assert progress.maximum() == 0
    assert progress.format() == "Working..."


def test_progress_error_and_ready_helpers_set_terminal_states() -> None:
    progress = QProgressBar()

    set_progress_error(progress)
    assert progress.minimum() == 0
    assert progress.maximum() == 1
    assert progress.value() == 0
    assert progress.format() == "Error"

    set_progress_ready(progress)
    assert progress.minimum() == 0
    assert progress.maximum() == 1
    assert progress.value() == 1
    assert progress.format() == "Ready"

    set_progress_idle(progress)
    assert progress.minimum() == 0
    assert progress.maximum() == 1
    assert progress.value() == 0
    assert progress.format() == "Idle"


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
