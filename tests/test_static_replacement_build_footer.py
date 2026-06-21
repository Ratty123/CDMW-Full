from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from cdmw.ui.archive_browser.static_replacement_build_footer import (
    AlignmentBuildFooter,
    alignment_build_footer_import_button_state,
    make_alignment_build_footer,
)

_APP = QApplication.instance() or QApplication([])


def test_alignment_build_footer_import_button_state_handles_build_and_blocked_modes() -> None:
    build_mod = alignment_build_footer_import_button_state(
        continue_build=True,
        export_allowed=True,
        export_block_reason="",
    )
    assert build_mod.text == "Build Mod"
    assert build_mod.enabled is True
    assert build_mod.tooltip == "Build/export with the current alignment settings and keep this window open for more edits."

    blocked = alignment_build_footer_import_button_state(
        continue_build=False,
        export_allowed=False,
        export_block_reason="",
    )
    assert blocked.text == "Continue"
    assert blocked.enabled is False
    assert blocked.tooltip == "This asset is not currently safe to export through Mesh Replacement."


def test_make_alignment_build_footer_adds_buttons_and_status_row() -> None:
    parent = QWidget()
    layout = QVBoxLayout(parent)

    footer = make_alignment_build_footer(
        layout,
        continue_build=True,
        export_allowed=False,
        export_block_reason="Blocked",
    )

    assert isinstance(footer, AlignmentBuildFooter)
    assert layout.count() == 2
    assert footer.cancel_button.text() == "Cancel"
    assert footer.import_button.text() == "Build Mod"
    assert footer.import_button.isEnabled() is False
    assert footer.import_button.toolTip() == "Blocked"
    assert footer.build_status_bar.isVisible() is False
    assert footer.build_status_label.objectName() == "MeshReplacementBuilderStatus"
    assert footer.build_status_label.isVisible() is False
