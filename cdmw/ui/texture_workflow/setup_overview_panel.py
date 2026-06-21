"""Texture workflow setup overview section construction."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from cdmw.ui.widgets import CollapsibleSection


class TextureWorkflowSetupOverviewPanelMixin:
    """Build first-run setup controls."""

    def _build_texture_workflow_setup_overview_section(self) -> None:
        self.setup_section = CollapsibleSection("Setup", expanded=False)
        setup_group = QWidget()
        setup_layout = QVBoxLayout(setup_group)
        setup_layout.setContentsMargins(0, 0, 0, 0)
        setup_layout.setSpacing(8)

        setup_overview_layout = QGridLayout()
        setup_overview_layout.setContentsMargins(0, 0, 0, 0)
        setup_overview_layout.setHorizontalSpacing(10)
        setup_overview_layout.setVerticalSpacing(8)

        setup_workspace_group = QGroupBox("Workspace")
        setup_workspace_layout = QGridLayout(setup_workspace_group)
        setup_workspace_layout.setContentsMargins(10, 10, 10, 10)
        setup_workspace_layout.setHorizontalSpacing(8)
        setup_workspace_layout.setVerticalSpacing(8)
        self.init_workspace_button = QPushButton("Init Workspace")
        self.create_folders_button = QPushButton("Create Folders")
        self.open_texture_editor_button = QPushButton("Open File In Texture Editor")
        setup_workspace_layout.addWidget(self.init_workspace_button, 0, 0)
        setup_workspace_layout.addWidget(self.create_folders_button, 1, 0)
        setup_workspace_layout.addWidget(self.open_texture_editor_button, 2, 0)
        setup_workspace_layout.setColumnStretch(0, 1)

        setup_tools_group = QGroupBox("External Tools")
        setup_tools_layout = QGridLayout(setup_tools_group)
        setup_tools_layout.setContentsMargins(10, 10, 10, 10)
        setup_tools_layout.setHorizontalSpacing(8)
        setup_tools_layout.setVerticalSpacing(8)
        self.download_chainner_button = QPushButton("Open chaiNNer Download Page")
        self.download_chainner_button.setToolTip("Open the official chaiNNer download page in your default browser.")
        self.download_texconv_button = QPushButton("Open DirectXTex / texconv Page")
        self.download_texconv_button.setToolTip("Open the official DirectXTex releases page. texconv is optional legacy fallback only.")
        self.download_ncnn_button = QPushButton("Open Real-ESRGAN NCNN Download Page")
        self.download_ncnn_button.setToolTip("Open the official Real-ESRGAN NCNN releases page in your default browser.")
        self.import_ncnn_models_button = QPushButton("Import NCNN Models")
        self.import_ncnn_models_button.setToolTip(
            "Import NCNN models from a folder, zip, or files that contain matching .param + .bin pairs."
        )
        setup_tools_layout.addWidget(self.download_texconv_button, 0, 0)
        setup_tools_layout.addWidget(self.download_chainner_button, 1, 0)
        setup_tools_layout.addWidget(self.download_ncnn_button, 2, 0)
        setup_tools_layout.addWidget(self.import_ncnn_models_button, 3, 0)
        setup_tools_layout.setColumnStretch(0, 1)
        for button in (
            self.init_workspace_button,
            self.create_folders_button,
            self.open_texture_editor_button,
            self.download_chainner_button,
            self.download_texconv_button,
            self.download_ncnn_button,
            self.import_ncnn_models_button,
        ):
            button.setMinimumHeight(28)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        setup_note_group = QGroupBox("Notes")
        setup_note_layout = QVBoxLayout(setup_note_group)
        setup_note_layout.setContentsMargins(10, 10, 10, 10)
        setup_note_layout.setSpacing(8)
        setup_hint = QLabel(
            "Recommended first run: put the portable EXE in its own folder, set the game/package path under "
            "Archive Locations, click Init Workspace, then use the bundled DirectXTex/native DDS tools. "
            "texconv.exe is optional legacy fallback only; download buttons open official pages "
            "in your browser instead of downloading files inside the app."
        )
        setup_hint.setObjectName("HintLabel")
        setup_hint.setWordWrap(True)
        setup_note_layout.addWidget(setup_hint)
        setup_note_layout.addStretch(1)

        setup_overview_layout.addWidget(setup_workspace_group, 0, 0)
        setup_overview_layout.addWidget(setup_tools_group, 1, 0)
        setup_overview_layout.addWidget(setup_note_group, 2, 0)
        setup_overview_layout.setColumnStretch(0, 1)
        setup_layout.addLayout(setup_overview_layout)

        self.setup_section.body_layout.addWidget(setup_group)


__all__ = ["TextureWorkflowSetupOverviewPanelMixin"]
