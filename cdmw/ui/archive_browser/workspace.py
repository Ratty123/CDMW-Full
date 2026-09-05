"""Explicit archive ownership for the workbench."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from cdmw.ui.archive_browser.workers import ArchiveWorkerLifecycleMixin
from cdmw.ui.archive_browser.workers import ArchivePreviewWorkerMixin
from cdmw.ui.archive_browser.preview_details import ArchivePreviewDetailsMixin
from cdmw.ui.archive_browser.preview_layout import ArchivePreviewLayoutMixin
from cdmw.ui.archive_browser.preview_loading import ArchivePreviewLoadingMixin
from cdmw.ui.archive_browser.preview_memory import ArchivePreviewMemoryAuditMixin
from cdmw.ui.archive_browser.preview_native_core import ArchivePreviewNativeCoreLifecycleMixin
from cdmw.ui.archive_browser.preview_renderer_controls import ArchivePreviewRendererControlsMixin
from cdmw.ui.archive_browser.preview_result import ArchivePreviewResultMixin
from cdmw.ui.archive_browser.preview_settings import ArchivePreviewSettingsMixin
from cdmw.ui.archive_browser.preview_d3d11_parts import ArchivePreviewD3D11PartsMixin
from cdmw.ui.archive_browser.preview_dotnet_lifecycle import ArchivePreviewDotNetLifecycleMixin
from cdmw.ui.archive_browser.preview_state import ArchivePreviewStateMixin
from cdmw.ui.archive_browser.preview_timing import ArchivePreviewTimingMixin
from cdmw.ui.archive_browser.preview_zoom import ArchivePreviewZoomMixin
from cdmw.ui.archive_browser.progress import ArchiveProgressMixin
from cdmw.ui.archive_browser.scan_lifecycle import ArchiveScanLifecycleMixin
from cdmw.ui.archive_browser.index_workers import ArchiveIndexWorkerMixin
from cdmw.ui.archive_browser.sidecar_index import ArchiveSidecarIndexMixin
from cdmw.ui.archive_browser.render_lifecycle import ArchiveRenderLifecycleMixin
from cdmw.ui.archive_browser.filter_workers import ArchiveFilterWorkerMixin
from cdmw.ui.archive_browser.filters import ArchiveFilterStateMixin
from cdmw.ui.archive_browser.filter_controls import ArchiveFilterControlsMixin
from cdmw.ui.archive_browser.files_panel import ArchiveFilesPanelMixin
from cdmw.ui.archive_browser.ui_formatting import ArchiveUiFormattingMixin
from cdmw.ui.archive_browser.virtual_path_lookup import ArchiveVirtualPathLookupMixin
from cdmw.ui.archive_browser.asset_catalog import ArchiveAssetCatalogMixin
from cdmw.ui.archive_browser.asset_catalog_scope import ArchiveAssetCatalogScopeMixin
from cdmw.ui.archive_browser.asset_catalog_dialog import ArchiveAssetCatalogDialogMixin
from cdmw.ui.archive_browser.character_dependency_export import ArchiveCharacterDependencyExportMixin
from cdmw.ui.archive_browser.controls_panel import ArchiveControlsPanelMixin
from cdmw.ui.archive_browser.extraction import ArchiveExtractionMixin
from cdmw.ui.archive_browser.icon_pipeline import ArchiveIconPipelineMixin
from cdmw.ui.archive_browser.material_sidecar_actions import ArchiveMaterialSidecarActionsMixin
from cdmw.ui.archive_browser.material_sidecar_editor_dialog import ArchiveMaterialSidecarEditorMixin
from cdmw.ui.archive_browser.mod_ready_export import ArchiveModReadyExportMixin
from cdmw.ui.tools.mod_package_retrofit import ArchiveModPackageRetrofitDialogMixin
from cdmw.ui.archive_browser.header import ArchiveBrowserHeaderMixin
from cdmw.ui.archive_browser.controller import ArchiveBrowserRowPayloadMixin
from cdmw.ui.archive_browser.controller import ArchiveBrowserTreeControllerMixin
from cdmw.ui.archive_browser.actions import ArchiveBrowserActionMixin
from cdmw.ui.archive_browser.action_controls import ArchiveBrowserActionControlsMixin
from cdmw.ui.archive_browser.appearance_common import ArchiveAppearanceCommonMixin
from cdmw.ui.archive_browser.appearance_composite import ArchiveAppearanceCompositeMixin
from cdmw.ui.archive_browser.appearance_swap import ArchiveAppearanceSwapMixin
from cdmw.ui.archive_browser.binary_sidecar_actions import ArchiveBinarySidecarActionsMixin
from cdmw.ui.archive_browser.prefab_inspector_actions import ArchivePrefabInspectorActionsMixin
from cdmw.ui.archive_browser.prefab_json_actions import ArchivePrefabJsonActionsMixin
from cdmw.ui.archive_browser.hkx_document_actions import ArchiveHkxDocumentActionsMixin
from cdmw.ui.archive_browser.hkx_editor_dialog import ArchiveHkxEditorDialogMixin
from cdmw.ui.archive_browser.static_replacement_dialog import ArchiveStaticReplacementDialogMixin
from cdmw.ui.archive_browser.mesh_modify_original import ArchiveMeshModifyOriginalMixin
from cdmw.ui.archive_browser.mesh_setup_helpers import ArchiveMeshSetupHelperMixin
from cdmw.ui.archive_browser.mesh_builder_lifecycle import ArchiveMeshBuilderLifecycleMixin
from cdmw.ui.archive_browser.mesh_dds_preview import ArchiveMeshDdsPreviewMixin
from cdmw.ui.archive_browser.mesh_direct_patch import ArchiveMeshDirectPatchMixin
from cdmw.ui.archive_browser.mesh_swap_support import ArchiveMeshSwapSupportMixin
from cdmw.ui.archive_browser.mesh_swap_scope_dialog import ArchiveMeshSwapScopeDialogMixin
from cdmw.ui.archive_browser.mesh_launch_flow import ArchiveMeshLaunchFlowMixin
from cdmw.ui.archive_browser.patch_actions import ArchivePatchActionsMixin
from cdmw.ui.archive_browser.mesh_patch_flow import ArchiveMeshPatchFlowMixin
from cdmw.ui.archive_browser.mesh_import_export import ArchiveMeshImportExportMixin
from cdmw.ui.archive_browser.import_actions import ArchiveImportActionsMixin
from cdmw.ui.archive_browser.attachment_batch import ArchiveAttachmentBatchMixin
from cdmw.ui.archive_browser.attachment_donor_picker_dialog import ArchiveAttachmentDonorPickerDialogMixin
from cdmw.ui.archive_browser.attachment_icons import ArchiveAttachmentIconMixin
from cdmw.ui.archive_browser.attachment_loose_files import ArchiveAttachmentLooseFileMixin
from cdmw.ui.archive_browser.attachment_package import ArchiveAttachmentPackageMixin
from cdmw.ui.archive_browser.attachment_plan import ArchiveAttachmentPlanMixin
from cdmw.ui.archive_browser.attachment_placement_diff_dialog import ArchiveAttachmentPlacementDiffDialogMixin
from cdmw.ui.archive_browser.attachment_safe_placement_dialog import ArchiveAttachmentSafePlacementDialogMixin
from cdmw.ui.archive_browser.attachment_socket_editor import ArchiveAttachmentSocketEditorMixin
from cdmw.ui.archive_browser.attachment_visual_dialog import ArchiveAttachmentVisualDialogMixin
from cdmw.ui.archive_browser.attachment_visual_payload import ArchiveAttachmentVisualPayloadMixin
from cdmw.ui.archive_browser.asset_family_references import ArchiveAssetFamilyReferenceMixin
from cdmw.ui.archive_browser.asset_family_dialog import ArchiveAssetFamilyDialogMixin
from cdmw.ui.archive_browser.asset_family_panel import ArchiveAssetFamilyPanelMixin
from cdmw.ui.archive_browser.asset_family_layout import ArchiveAssetFamilyLayoutMixin
from cdmw.ui.archive_browser.reference_export import ArchiveReferenceExportMixin
from cdmw.ui.archive_browser.reference_preview import ArchiveReferencePreviewMixin
from cdmw.ui.archive_browser.source_picker_dialog import ArchiveSourcePickerDialogMixin
from cdmw.ui.archive_browser.source_mix_actions import ArchiveSourceMixActionsMixin
from cdmw.ui.archive_browser.source_mix_overlay import ArchiveSourceMixOverlayMixin
from cdmw.ui.archive_browser.preview_cache import ArchivePreviewCacheMixin
from cdmw.ui.archive_browser.preview_core_prewarm import ArchivePreviewCorePrewarmMixin
from cdmw.ui.archive_browser.preview_panel import ArchivePreviewTextToolsMixin
from cdmw.ui.archive_browser.runtime_state import ArchiveRuntimeStateMixin
from cdmw.ui.archive_browser.workspace_layout import ArchiveWorkspaceLayoutMixin


class ArchiveBrowserWorkspace(
    ArchiveWorkerLifecycleMixin,
    ArchivePreviewWorkerMixin,
    ArchivePreviewDetailsMixin,
    ArchivePreviewLayoutMixin,
    ArchivePreviewLoadingMixin,
    ArchivePreviewMemoryAuditMixin,
    ArchivePreviewNativeCoreLifecycleMixin,
    ArchivePreviewRendererControlsMixin,
    ArchivePreviewResultMixin,
    ArchivePreviewSettingsMixin,
    ArchivePreviewD3D11PartsMixin,
    ArchivePreviewDotNetLifecycleMixin,
    ArchivePreviewStateMixin,
    ArchivePreviewTimingMixin,
    ArchivePreviewZoomMixin,
    ArchiveProgressMixin,
    ArchiveScanLifecycleMixin,
    ArchiveIndexWorkerMixin,
    ArchiveSidecarIndexMixin,
    ArchiveRenderLifecycleMixin,
    ArchiveFilterWorkerMixin,
    ArchiveFilterStateMixin,
    ArchiveFilterControlsMixin,
    ArchiveFilesPanelMixin,
    ArchiveUiFormattingMixin,
    ArchiveVirtualPathLookupMixin,
    ArchiveAssetCatalogMixin,
    ArchiveAssetCatalogScopeMixin,
    ArchiveAssetCatalogDialogMixin,
    ArchiveCharacterDependencyExportMixin,
    ArchiveControlsPanelMixin,
    ArchiveExtractionMixin,
    ArchiveIconPipelineMixin,
    ArchiveMaterialSidecarActionsMixin,
    ArchiveMaterialSidecarEditorMixin,
    ArchiveModReadyExportMixin,
    ArchiveModPackageRetrofitDialogMixin,
    ArchiveBrowserHeaderMixin,
    ArchiveBrowserRowPayloadMixin,
    ArchiveBrowserTreeControllerMixin,
    ArchiveBrowserActionMixin,
    ArchiveBrowserActionControlsMixin,
    ArchiveAppearanceCommonMixin,
    ArchiveAppearanceCompositeMixin,
    ArchiveAppearanceSwapMixin,
    ArchiveBinarySidecarActionsMixin,
    ArchivePrefabInspectorActionsMixin,
    ArchivePrefabJsonActionsMixin,
    ArchiveHkxDocumentActionsMixin,
    ArchiveHkxEditorDialogMixin,
    ArchiveStaticReplacementDialogMixin,
    ArchiveMeshModifyOriginalMixin,
    ArchiveMeshSetupHelperMixin,
    ArchiveMeshBuilderLifecycleMixin,
    ArchiveMeshDdsPreviewMixin,
    ArchiveMeshDirectPatchMixin,
    ArchiveMeshSwapSupportMixin,
    ArchiveMeshSwapScopeDialogMixin,
    ArchiveMeshLaunchFlowMixin,
    ArchivePatchActionsMixin,
    ArchiveMeshPatchFlowMixin,
    ArchiveMeshImportExportMixin,
    ArchiveImportActionsMixin,
    ArchiveAttachmentBatchMixin,
    ArchiveAttachmentDonorPickerDialogMixin,
    ArchiveAttachmentIconMixin,
    ArchiveAttachmentLooseFileMixin,
    ArchiveAttachmentPackageMixin,
    ArchiveAttachmentPlanMixin,
    ArchiveAttachmentPlacementDiffDialogMixin,
    ArchiveAttachmentSafePlacementDialogMixin,
    ArchiveAttachmentSocketEditorMixin,
    ArchiveAttachmentVisualDialogMixin,
    ArchiveAttachmentVisualPayloadMixin,
    ArchiveAssetFamilyReferenceMixin,
    ArchiveAssetFamilyDialogMixin,
    ArchiveAssetFamilyPanelMixin,
    ArchiveAssetFamilyLayoutMixin,
    ArchiveReferenceExportMixin,
    ArchiveReferencePreviewMixin,
    ArchiveSourcePickerDialogMixin,
    ArchiveSourceMixActionsMixin,
    ArchiveSourceMixOverlayMixin,
    ArchivePreviewCacheMixin,
    ArchivePreviewCorePrewarmMixin,
    ArchivePreviewTextToolsMixin,
    ArchiveRuntimeStateMixin,
    ArchiveWorkspaceLayoutMixin,
    QWidget,
):
    def __init__(self, shell) -> None:
        super().__init__(shell)
        self.shell = shell

    @property
    def archive(self):
        return self

    @property
    def textures(self):
        return self.shell.textures
