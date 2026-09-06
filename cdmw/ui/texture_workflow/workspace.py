"""Explicit texture ownership for the workbench."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from cdmw.ui.texture_workflow.config_collection import TextureWorkflowConfigCollectionMixin
from cdmw.ui.texture_workflow.dds_output_panel import TextureWorkflowDdsOutputPanelMixin
from cdmw.ui.texture_workflow.editor_bridge import TextureWorkflowEditorBridgeMixin
from cdmw.ui.texture_workflow.editor_handoff import TextureWorkflowEditorHandoffMixin
from cdmw.ui.texture_workflow.paths_panel import TextureWorkflowPathsPanelMixin
from cdmw.ui.texture_workflow.progress_panel import TextureWorkflowProgressPanelMixin
from cdmw.ui.texture_workflow.settings_panel import TextureWorkflowSettingsPanelMixin
from cdmw.ui.texture_workflow.shell_controls import TextureWorkflowShellControlsMixin
from cdmw.ui.texture_workflow.setup_panel import TextureWorkflowSetupPanelMixin
from cdmw.ui.texture_workflow.setup_overview_panel import TextureWorkflowSetupOverviewPanelMixin
from cdmw.ui.texture_workflow.upscale_backend_panel import TextureWorkflowUpscaleBackendPanelMixin
from cdmw.ui.texture_workflow.workflow_profiles_panel import TextureWorkflowProfilesPanelMixin
from cdmw.ui.texture_workflow.workflow_profiles_ui import TextureWorkflowProfilesUiMixin
from cdmw.ui.texture_workflow.workers import TextureWorkflowWorkerMixin
from cdmw.ui.shell.texture_workspace_layout import TextureWorkspaceLayoutMixin
from cdmw.ui.texture_workflow.job import TextureJob
from cdmw.ui.texture_workflow.workspace_ui import TextureJobUiMixin
from cdmw.ui.texture_workflow.job_operations import TextureJobOperationsMixin
from cdmw.ui.texture_workflow.job_review import TextureJobReviewMixin


class TexturesWorkspace(
    TextureJobReviewMixin,
    TextureJobOperationsMixin,
    TextureJobUiMixin,
    TextureWorkflowConfigCollectionMixin,
    TextureWorkflowDdsOutputPanelMixin,
    TextureWorkflowEditorBridgeMixin,
    TextureWorkflowEditorHandoffMixin,
    TextureWorkflowPathsPanelMixin,
    TextureWorkflowProgressPanelMixin,
    TextureWorkflowSettingsPanelMixin,
    TextureWorkflowShellControlsMixin,
    TextureWorkflowSetupPanelMixin,
    TextureWorkflowSetupOverviewPanelMixin,
    TextureWorkflowUpscaleBackendPanelMixin,
    TextureWorkflowProfilesPanelMixin,
    TextureWorkflowProfilesUiMixin,
    TextureWorkflowWorkerMixin,
    TextureWorkspaceLayoutMixin,
    QWidget,
):
    def __init__(self, shell) -> None:
        super().__init__(shell)
        self.shell = shell
        self.job = TextureJob()
        self._last_build_unknown_review_result = None

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
