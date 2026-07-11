"""Lazy Texture Workflow workspace assembly."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QScrollArea, QSplitter, QVBoxLayout, QWidget

from cdmw.ui.layout_utils import build_responsive_splitter_sizes, responsive_sidebar_bounds
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
        section.set_expanded(expanded)
        return section

    def _build_texture_workflow_shell_tab(self, pump_startup_splash: Callable[[str], None]) -> None:
        expanded = {
            name: _persisted_section_expanded(self.settings, f"sections/{name}_expanded")
            for name in ("settings", "asset_authoring", "dds_output", "filters", "chainner")
        }
        self.workflow_tab = QWidget()
        workflow_layout = QVBoxLayout(self.workflow_tab)
        workflow_layout.setContentsMargins(0, 0, 0, 0)
        workflow_layout.setSpacing(10)
        self.texture_tabs.addTab(self.workflow_tab, "Workflow")
        pump_startup_splash("Preparing texture workflow...")

        self.workflow_splitter = QSplitter(Qt.Horizontal)
        self.workflow_splitter.setChildrenCollapsible(False)
        workflow_layout.addWidget(self.workflow_splitter, stretch=1)

        self.left_panel = QWidget()
        self.left_panel.setMinimumWidth(320)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        self.left_scroll_area = QScrollArea()
        self.left_scroll_area.setWidgetResizable(True)
        self.left_scroll_area.setFrameShape(QFrame.NoFrame)
        self.left_scroll_area.setMinimumWidth(320)
        self.left_scroll_area.setWidget(self.left_panel)

        self.right_panel = QWidget()
        self.right_panel.setMinimumWidth(320)
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        self.workflow_right_splitter = QSplitter(Qt.Vertical)
        self.workflow_right_splitter.setChildrenCollapsible(False)

        self.workflow_splitter.addWidget(self.left_scroll_area)
        self.workflow_splitter.addWidget(self.right_panel)
        workflow_nav_min, _workflow_nav_pref, workflow_nav_max = responsive_sidebar_bounds(self, role="workflow")
        workflow_content_min, _workflow_content_pref, _workflow_content_max = responsive_sidebar_bounds(self, role="wide")
        self.left_panel.setMinimumWidth(workflow_nav_min)
        self.left_scroll_area.setMinimumWidth(workflow_nav_min)
        self.left_scroll_area.setMaximumWidth(workflow_nav_max)
        self.right_panel.setMinimumWidth(workflow_content_min)
        self.workflow_splitter.setStretchFactor(0, 1)
        self.workflow_splitter.setStretchFactor(1, 2)
        self.workflow_splitter.setSizes(
            build_responsive_splitter_sizes(1180, [42, 58], [workflow_nav_min, workflow_content_min])
        )

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

        self.workflow_right_splitter.addWidget(self._build_texture_workflow_progress_panel())
        self._build_texture_workflow_content_tabs(pump_startup_splash)
        right_layout.addWidget(self.workflow_right_splitter, stretch=1)
        self._build_texture_workflow_action_button_row(workflow_layout)

__all__ = ["TextureWorkspaceLayoutMixin"]
