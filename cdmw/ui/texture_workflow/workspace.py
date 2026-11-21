"""Explicit texture ownership for the workbench."""

from __future__ import annotations

import importlib

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from cdmw.ui.texture_workflow.editor_bridge import TextureWorkflowEditorBridgeMixin
from cdmw.ui.texture_workflow.paths_panel import TextureWorkflowPathsPanelMixin
from cdmw.ui.texture_workflow.progress_panel import TextureWorkflowProgressPanelMixin
from cdmw.ui.texture_workflow.shell_controls import TextureWorkflowShellControlsMixin
from cdmw.ui.texture_workflow.setup_panel import TextureWorkflowSetupPanelMixin
from cdmw.ui.texture_workflow.setup_overview_panel import TextureWorkflowSetupOverviewPanelMixin
from cdmw.ui.texture_workflow.workflow_profiles_panel import TextureWorkflowProfilesPanelMixin
from cdmw.ui.texture_workflow.workers import TextureWorkflowWorkerMixin
from cdmw.ui.shell.texture_workspace_layout import TextureWorkspaceLayoutMixin
from cdmw.ui.texture_workflow.job import TextureJob
from cdmw.ui.texture_workflow.workspace_ui import TextureJobUiMixin

# Mixins unused during startup construction are loaded on first attribute access
# and attached directly onto TexturesWorkspace so subsequent lookups pay zero
# __getattr__ overhead while preserving normal bound-method semantics.
_LAZY_MIXIN_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("cdmw.ui.texture_workflow.replacement_sources", "TextureReplacementSourcesMixin", ("can_change_texture_sources", "confirm_texture_asset_removal", "remove_texture_assets", "accept_replacement_import", "replacement_item_key", "open_replacement_item", "set_replacement_item_included", "replacement_build_items")),
    ("cdmw.ui.texture_workflow.job_review", "TextureJobReviewMixin", ("select_replacement_asset", "prepare_replacement_review", "synchronize_replacement_matches")),
    ("cdmw.ui.texture_workflow.job_operations", "TextureJobOperationsMixin", ("open_texture_package_asset", "capture_texture_job_inputs", "begin_texture_operation", "set_texture_job_busy", "finish_texture_operation")),
    ("cdmw.ui.texture_workflow.config_collection", "TextureWorkflowConfigCollectionMixin", ("collect_config",)),
    ("cdmw.ui.texture_workflow.dds_output_panel", "TextureWorkflowDdsOutputPanelMixin", ("_build_dds_output_section", "_build_dds_output_body")),
    ("cdmw.ui.texture_workflow.editor_handoff", "TextureWorkflowEditorHandoffMixin", ("_set_pending_archive_workflow_extract", "_handle_texture_editor_send_to_replace_assistant", "_handle_texture_editor_send_to_texture_workflow", "_manual_workflow_cleanup_targets", "_handle_texture_editor_send_to_item_icons", "_handle_model_library_item_icon_generated", "_choose_item_icon_library_source", "_show_compare_from_texture_editor")),
    ("cdmw.ui.texture_workflow.settings_panel", "TextureWorkflowSettingsPanelMixin", ("_build_texture_workflow_settings_section", "_build_texture_workflow_settings_body", "_build_texture_workflow_asset_authoring_section", "_build_texture_workflow_asset_authoring_body", "_asset_authoring_service", "_openimageio_configured_paths", "_browse_openimageio_source_path", "_browse_openimageio_output_path", "_browse_openimageio_compare_path", "_openimageio_existing_path", "_openimageio_output_path", "start_openimageio_metadata", "start_openimageio_convert", "start_openimageio_diff", "_start_openimageio_task", "_handle_openimageio_task_complete", "_handle_openimageio_task_cancelled")),
    ("cdmw.ui.texture_workflow.upscale_backend_panel", "TextureWorkflowUpscaleBackendPanelMixin", ("_build_upscale_backend_section", "_build_upscale_backend_body", "_build_upscale_backend_selector", "_build_chainner_backend_page", "_build_upscale_policy_controls", "_build_upscale_policy_layout")),
    ("cdmw.ui.texture_workflow.workflow_profiles_ui", "TextureWorkflowProfilesUiMixin", ("_build_workflow_profiles_section", "_build_workflow_profiles_body", "_build_workflow_profiles_group", "_build_workflow_rules_group", "_build_workflow_matches_group")),
)

_LAZY_ATTR_TO_MIXIN: dict[str, tuple[str, str]] = {
    attr: (module_name, class_name)
    for module_name, class_name, attrs in _LAZY_MIXIN_SPECS
    for attr in attrs
}


def _attach_lazy_mixin(target_cls: type, module_name: str, class_name: str) -> None:
    mixin_cls = getattr(importlib.import_module(module_name), class_name)
    for base in mixin_cls.__mro__:
        if not base.__module__.startswith("cdmw."):
            continue
        for attr_name, raw_value in base.__dict__.items():
            if attr_name.startswith("__") and attr_name.endswith("__"):
                continue
            if attr_name not in target_cls.__dict__:
                setattr(target_cls, attr_name, raw_value)


class TexturesWorkspace(
    TextureJobUiMixin,
    TextureWorkflowEditorBridgeMixin,
    TextureWorkflowPathsPanelMixin,
    TextureWorkflowProgressPanelMixin,
    TextureWorkflowShellControlsMixin,
    TextureWorkflowSetupPanelMixin,
    TextureWorkflowSetupOverviewPanelMixin,
    TextureWorkflowProfilesPanelMixin,
    TextureWorkflowWorkerMixin,
    TextureWorkspaceLayoutMixin,
    QWidget,
):
    def __init__(self, shell) -> None:
        super().__init__(shell)
        self.shell = shell
        self.job = TextureJob()
        self._last_build_unknown_review_result = None

    def __getattr__(self, name: str):
        target = _LAZY_ATTR_TO_MIXIN.get(name)
        if target is None:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
        module_name, class_name = target
        _attach_lazy_mixin(TexturesWorkspace, module_name, class_name)
        return getattr(self, name)

    @property
    def textures(self):
        return self

    @property
    def archive(self):
        return self.shell.archive

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if hasattr(self, "mode_controls"):
            self.set_texture_mode(self.job.mode)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self, self._fit_upscale_sidebar)
