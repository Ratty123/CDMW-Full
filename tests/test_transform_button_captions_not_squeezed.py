"""Transform-row buttons must never be squeezed below their captions.

The Placement panel's reset and tilt buttons sat in single rows with
`setMinimumWidth(0)`. Both halves clipped: the explicit zero minimum
overrode QPushButton's caption-based `minimumSizeHint`, and the embedded
setup page carries `QSizePolicy.Ignored`, which squeezes an overlong row
below its minimum regardless of hints. The reader saw the centred text cut
at both ends -- "eset Placemer", "ilt X+", "urn Y", "oll Z". The rows are
now grids narrow enough to fit the panel: reset two-per-row, tilt one axis
per column with minus above plus.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QWidget,
)

from cdmw.ui.archive_browser.static_replacement_transform_control_state import (  # noqa: E402
    alignment_global_transform_layout_specs,
    alignment_global_transform_tilt_button_specs,
    alignment_transform_control_text,
)

# The embedded mesh-edit setup column is at least this wide; the defect showed
# at widths like this, so the fix must hold here.
_NARROW_PANEL_WIDTH = 340


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _tilt_captions() -> list[str]:
    control_text = alignment_transform_control_text()
    return [
        str(control_text[str(spec["text_key"])])
        for spec in alignment_global_transform_tilt_button_specs()
    ]


def _clamped(container: QWidget, width: int = _NARROW_PANEL_WIDTH) -> QWidget:
    # QSizePolicy.Ignored on the embedded setup page means the panel width
    # wins over the content's minimum; a fixed width reproduces that clamp.
    container.setFixedWidth(width)
    container.show()
    container.layout().activate()
    return container


class TransformButtonCaptionTests(unittest.TestCase):
    def setUp(self) -> None:
        _app()
        self.captions = _tilt_captions()

    def test_the_defect_mechanism_is_real(self) -> None:
        """A single row of six captioned buttons squeezes below its hints."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        buttons = [QPushButton(caption) for caption in self.captions]
        for button in buttons:
            row.addWidget(button)
        self.addCleanup(container.deleteLater)
        hint_floor = sum(button.minimumSizeHint().width() for button in buttons)
        _clamped(container, max(1, hint_floor - 1))
        self.assertTrue(
            any(button.width() < button.minimumSizeHint().width() for button in buttons),
            "expected the single row to shrink at least one button below its caption",
        )

    def test_the_axis_grid_keeps_every_caption_at_its_floor(self) -> None:
        """Three columns of two, exactly as the construction arranges them."""
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        buttons = [QPushButton(caption) for caption in self.captions]
        for index, button in enumerate(buttons):
            grid.addWidget(button, index % 2, index // 2)
        self.addCleanup(container.deleteLater)
        _clamped(container)
        for button in buttons:
            self.assertGreaterEqual(
                button.width(),
                button.minimumSizeHint().width(),
                f"{button.text()!r} was squeezed below its caption",
            )

    def test_the_construction_arranges_grids_and_leaves_the_hint_floor(self) -> None:
        specs = alignment_global_transform_layout_specs()
        self.assertEqual(int(specs["reset_button_minimum_width"]), 0)
        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "cdmw",
            "ui",
            "archive_browser",
            "static_replacement_dialog_sections_setup_options_transform_part_02.py",
        )
        with open(source_path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("_state.tilt_button.setMinimumWidth(0)", text)
        self.assertIn(
            "if int(_state.transform_layout_specs['reset_button_minimum_width']) > 0:",
            text,
        )
        self.assertIn("_state.reset_index // 2, _state.reset_index % 2", text)
        self.assertIn("1 + _state.tilt_index % 2, _state.tilt_index // 2", text)


if __name__ == "__main__":
    unittest.main()
