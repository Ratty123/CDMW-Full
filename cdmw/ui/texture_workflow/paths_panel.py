"""Texture workflow path section construction."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLineEdit, QWidget

from cdmw.ui.widgets import CollapsibleSection


class TextureWorkflowPathsPanelMixin:
    """Build texture workflow path inputs shared with Settings."""

    def _build_texture_workflow_paths_section(self) -> None:
        self.paths_section = CollapsibleSection("Paths", expanded=False)
        paths_group = QWidget()
        paths_layout = QGridLayout(paths_group)
        paths_layout.setContentsMargins(0, 0, 0, 0)
        paths_layout.setHorizontalSpacing(10)
        paths_layout.setVerticalSpacing(10)
        paths_layout.setColumnMinimumWidth(0, 136)
        paths_layout.setColumnStretch(1, 1)

        self.original_dds_edit = QLineEdit()
        self.png_root_edit = QLineEdit()
        self.texture_editor_png_root_edit = QLineEdit()
        self.dds_staging_root_edit = QLineEdit()
        self.output_root_edit = QLineEdit()

        self._add_path_row(paths_layout, 0, "Original DDS root", self.original_dds_edit, self._browse_original_dds_root)
        self._add_path_row(paths_layout, 1, "PNG root", self.png_root_edit, self._browse_png_root)
        self._add_path_row(
            paths_layout,
            2,
            "Texture Editor PNG root",
            self.texture_editor_png_root_edit,
            self._browse_texture_editor_png_root,
        )
        self.dds_staging_browse_button = self._add_path_row(
            paths_layout,
            3,
            "Staging PNG root",
            self.dds_staging_root_edit,
            self._browse_dds_staging_root,
        )
        self._add_path_row(paths_layout, 4, "Output root", self.output_root_edit, self._browse_output_root)
        self.paths_section.body_layout.addWidget(paths_group)


__all__ = ["TextureWorkflowPathsPanelMixin"]
