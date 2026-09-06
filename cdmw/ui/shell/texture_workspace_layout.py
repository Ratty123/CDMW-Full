"""Lazy Texture Workflow workspace assembly."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QLayout, QScrollArea, QVBoxLayout, QWidget

from cdmw.ui.panel_widgets import CollapsibleSection


def _persisted_section_expanded(settings: object, key: str) -> bool:
    value = settings.value(key, False)  # type: ignore[attr-defined]
    return value if isinstance(value, bool) else str(value).strip().lower() in {"1", "true", "yes", "on"}


class TextureWorkspaceLayoutMixin:
    def _initialize_workflow_profile_state(self) -> None:
        self.texture_rules_legacy_text = ""
        self.workflow_profiles_state = []
        self.texture_rules_state = []
        self.workflow_matched_processing_plan = []
        self._workflow_editor_syncing = False
        self._workflow_match_refresh_timer = QTimer(self)
        self._workflow_match_refresh_timer.setSingleShot(True)
        self._workflow_match_refresh_timer.setInterval(300)
        self._workflow_match_refresh_timer.timeout.connect(
            lambda: getattr(self, "_refresh_workflow_matched_files_view")()
        )

    def _deferred_workflow_section(
        self,
        attribute: str,
        title: str,
        body_method: str,
        *,
        expanded: bool,
        body_arguments: tuple[object, ...] = (),
    ) -> CollapsibleSection:
        def build(body_layout: QVBoxLayout) -> None:
            getattr(self, body_method)(body_layout, *body_arguments)

        section = CollapsibleSection(title, body_builder=build)
        setattr(self, attribute, section)
        section.toggled.connect(
            lambda _expanded: QTimer.singleShot(0, self, self._fit_upscale_sidebar)
        )
        section.set_expanded(expanded)
        return section

    def _build_texture_workflow_shell_tab(self, pump_startup_splash: Callable[[str], None]) -> None:
        expanded = {
            name: _persisted_section_expanded(self.shell.settings, f"sections/{name}_expanded")
            for name in ("settings", "asset_authoring", "dds_output", "filters", "chainner")
        }
        self.workflow_tab = self
        pump_startup_splash("Preparing texture controls...")
        self.left_panel = QWidget()
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setSizeConstraint(QLayout.SetMinimumSize)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        self.left_scroll_area = QScrollArea(self)
        self.left_scroll_area.setWidgetResizable(True)
        self.left_scroll_area.setFrameShape(QFrame.NoFrame)
        self.left_scroll_area.setWidget(self.left_panel)
        self.upscale_controls = self.left_scroll_area
        self.upscale_export_controls = QWidget(self)
        self.upscale_export_controls.hide()
        export_layout = QVBoxLayout(self.upscale_export_controls)

        self._build_texture_workflow_paths_section()
        self._build_texture_workflow_setup_overview_section()
        self._initialize_workflow_profile_state()
        left_layout.addWidget(self._deferred_workflow_section(
            "settings_section",
            "Settings",
            "_build_texture_workflow_settings_body",
            expanded=expanded["settings"],
            body_arguments=(pump_startup_splash,),
        ))
        left_layout.addWidget(self._deferred_workflow_section(
            "asset_authoring_section",
            "Asset Authoring",
            "_build_texture_workflow_asset_authoring_body",
            expanded=expanded["asset_authoring"],
        ))
        left_layout.addWidget(self._deferred_workflow_section(
            "dds_output_section",
            "DDS Output",
            "_build_dds_output_body",
            expanded=expanded["dds_output"],
        ))
        left_layout.addWidget(self._deferred_workflow_section(
            "filters_section",
            "Workflow Profiles, Rules & Matches",
            "_build_workflow_profiles_body",
            expanded=expanded["filters"],
        ))
        left_layout.addWidget(self._deferred_workflow_section(
            "chainner_section",
            "Upscaling",
            "_build_upscale_backend_body",
            expanded=expanded["chainner"],
            body_arguments=(pump_startup_splash,),
        ))
        left_layout.addStretch(1)

        export_layout.addWidget(self._build_texture_workflow_progress_panel())
        from PySide6.QtWidgets import QPlainTextEdit, QPushButton
        from cdmw.ui.widgets import LogHighlighter
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(5000)
        self.log_highlighter = LogHighlighter(self.log_view.document(), self.shell.current_theme_key)
        export_layout.addWidget(self.log_view, stretch=1)
        self.clear_log_button = QPushButton("Clear Log")
        export_layout.addWidget(self.clear_log_button)
        self._build_texture_workflow_action_button_row(export_layout)

__all__ = ["TextureWorkspaceLayoutMixin"]
