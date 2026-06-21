"""Footer widget construction for the static replacement builder."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QLabel, QHBoxLayout, QProgressBar, QPushButton, QVBoxLayout


@dataclass(frozen=True, slots=True)
class AlignmentBuildFooter:
    cancel_button: QPushButton
    import_button: QPushButton
    build_status_bar: QProgressBar
    build_status_label: QLabel


@dataclass(frozen=True, slots=True)
class AlignmentBuildFooterImportButtonState:
    text: str
    enabled: bool
    tooltip: str


def alignment_build_footer_import_button_state(
    *,
    continue_build: bool,
    export_allowed: bool,
    export_block_reason: str,
) -> AlignmentBuildFooterImportButtonState:
    tooltip = ""
    if bool(continue_build):
        tooltip = "Build/export with the current alignment settings and keep this window open for more edits."
    if not bool(export_allowed):
        tooltip = (
            str(export_block_reason or "")
            or "This asset is not currently safe to export through Mesh Replacement."
        )
    return AlignmentBuildFooterImportButtonState(
        text="Build Mod" if bool(continue_build) else "Continue",
        enabled=bool(export_allowed),
        tooltip=tooltip,
    )


def make_alignment_build_footer(
    root_layout: QVBoxLayout,
    *,
    continue_build: bool,
    export_allowed: bool,
    export_block_reason: str,
) -> AlignmentBuildFooter:
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    cancel_button = QPushButton("Cancel")
    import_button_state = alignment_build_footer_import_button_state(
        continue_build=continue_build,
        export_allowed=export_allowed,
        export_block_reason=export_block_reason,
    )
    import_button = QPushButton(import_button_state.text)
    import_button.setDefault(True)
    import_button.setEnabled(import_button_state.enabled)
    if import_button_state.tooltip:
        import_button.setToolTip(import_button_state.tooltip)
    buttons.addWidget(cancel_button)
    buttons.addWidget(import_button)
    root_layout.addLayout(buttons)

    build_status_row = QHBoxLayout()
    build_status_row.setSpacing(8)
    build_status_bar = QProgressBar()
    build_status_bar.setRange(0, 0)
    build_status_bar.setTextVisible(False)
    build_status_bar.setMaximumWidth(140)
    build_status_bar.setVisible(False)
    build_status_label = QLabel("")
    build_status_label.setObjectName("MeshReplacementBuilderStatus")
    build_status_label.setWordWrap(True)
    build_status_label.setVisible(False)
    build_status_row.addWidget(build_status_bar)
    build_status_row.addWidget(build_status_label, 1)
    root_layout.addLayout(build_status_row)
    return AlignmentBuildFooter(
        cancel_button=cancel_button,
        import_button=import_button,
        build_status_bar=build_status_bar,
        build_status_label=build_status_label,
    )


__all__ = [
    "AlignmentBuildFooter",
    "AlignmentBuildFooterImportButtonState",
    "alignment_build_footer_import_button_state",
    "make_alignment_build_footer",
]
