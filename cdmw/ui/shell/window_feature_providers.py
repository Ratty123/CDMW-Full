from __future__ import annotations

from cdmw.ui.shell.window_feature_controller import LazyFeatureProvider
from cdmw.ui.shell.window_feature_provider_members import PROVIDER_MEMBERS, PROVIDER_METHOD_ARITIES


_PROVIDER_DECLARATIONS = r"""
from cdmw.ui.archive_browser.action_controls import ArchiveBrowserActionControlsMixin
from cdmw.ui.archive_browser.actions import ArchiveBrowserActionMixin
from cdmw.ui.archive_browser.appearance_common import ArchiveAppearanceCommonMixin
from cdmw.ui.archive_browser.appearance_composite import ArchiveAppearanceCompositeMixin
from cdmw.ui.archive_browser.appearance_swap import ArchiveAppearanceSwapMixin
from cdmw.ui.archive_browser.asset_catalog import ArchiveAssetCatalogMixin
from cdmw.ui.archive_browser.asset_catalog_dialog import ArchiveAssetCatalogDialogMixin
from cdmw.ui.archive_browser.asset_catalog_scope import ArchiveAssetCatalogScopeMixin
from cdmw.ui.archive_browser.asset_family_dialog import ArchiveAssetFamilyDialogMixin
from cdmw.ui.archive_browser.asset_family_layout import ArchiveAssetFamilyLayoutMixin
from cdmw.ui.archive_browser.asset_family_panel import ArchiveAssetFamilyPanelMixin
from cdmw.ui.archive_browser.asset_family_references import ArchiveAssetFamilyReferenceMixin
from cdmw.ui.archive_browser.attachment_batch import ArchiveAttachmentBatchMixin
from cdmw.ui.archive_browser.attachment_donor_picker_dialog import ArchiveAttachmentDonorPickerDialogMixin
from cdmw.ui.archive_browser.attachment_icons import ArchiveAttachmentIconMixin
from cdmw.ui.archive_browser.attachment_loose_files import ArchiveAttachmentLooseFileMixin
from cdmw.ui.archive_browser.attachment_package import ArchiveAttachmentPackageMixin
from cdmw.ui.archive_browser.attachment_placement_diff_dialog import ArchiveAttachmentPlacementDiffDialogMixin
from cdmw.ui.archive_browser.attachment_plan import ArchiveAttachmentPlanMixin
from cdmw.ui.archive_browser.attachment_safe_placement_dialog import ArchiveAttachmentSafePlacementDialogMixin
from cdmw.ui.archive_browser.attachment_socket_editor import ArchiveAttachmentSocketEditorMixin
from cdmw.ui.archive_browser.attachment_visual_dialog import ArchiveAttachmentVisualDialogMixin
from cdmw.ui.archive_browser.attachment_visual_payload import ArchiveAttachmentVisualPayloadMixin
from cdmw.ui.archive_browser.binary_sidecar_actions import ArchiveBinarySidecarActionsMixin
from cdmw.ui.archive_browser.character_dependency_export import ArchiveCharacterDependencyExportMixin
from cdmw.ui.archive_browser.controller import ArchiveBrowserRowPayloadMixin, ArchiveBrowserTreeControllerMixin
from cdmw.ui.archive_browser.controls_panel import ArchiveControlsPanelMixin
from cdmw.ui.archive_browser.extraction import ArchiveExtractionMixin
from cdmw.ui.archive_browser.files_panel import ArchiveFilesPanelMixin
from cdmw.ui.archive_browser.filter_controls import ArchiveFilterControlsMixin
from cdmw.ui.archive_browser.filter_workers import ArchiveFilterWorkerMixin
from cdmw.ui.archive_browser.filters import ArchiveFilterStateMixin
from cdmw.ui.archive_browser.header import ArchiveBrowserHeaderMixin
from cdmw.ui.archive_browser.hkx_document_actions import ArchiveHkxDocumentActionsMixin
from cdmw.ui.archive_browser.hkx_editor_dialog import ArchiveHkxEditorDialogMixin
from cdmw.ui.archive_browser.icon_pipeline import ArchiveIconPipelineMixin
from cdmw.ui.archive_browser.import_actions import ArchiveImportActionsMixin
from cdmw.ui.archive_browser.index_workers import ArchiveIndexWorkerMixin
from cdmw.ui.archive_browser.material_sidecar_actions import ArchiveMaterialSidecarActionsMixin
from cdmw.ui.archive_browser.material_sidecar_editor_dialog import ArchiveMaterialSidecarEditorMixin
from cdmw.ui.archive_browser.mesh_builder_lifecycle import ArchiveMeshBuilderLifecycleMixin
from cdmw.ui.archive_browser.mesh_dds_preview import ArchiveMeshDdsPreviewMixin
from cdmw.ui.archive_browser.mesh_direct_patch import ArchiveMeshDirectPatchMixin
from cdmw.ui.archive_browser.mesh_import_export import ArchiveMeshImportExportMixin
from cdmw.ui.archive_browser.mesh_launch_flow import ArchiveMeshLaunchFlowMixin
from cdmw.ui.archive_browser.mesh_modify_original import ArchiveMeshModifyOriginalMixin
from cdmw.ui.archive_browser.mesh_patch_flow import ArchiveMeshPatchFlowMixin
from cdmw.ui.archive_browser.mesh_setup_helpers import ArchiveMeshSetupHelperMixin
from cdmw.ui.archive_browser.mesh_swap_scope_dialog import ArchiveMeshSwapScopeDialogMixin
from cdmw.ui.archive_browser.mesh_swap_support import ArchiveMeshSwapSupportMixin
from cdmw.ui.archive_browser.mod_ready_export import ArchiveModReadyExportMixin
from cdmw.ui.archive_browser.patch_actions import ArchivePatchActionsMixin
from cdmw.ui.archive_browser.prefab_inspector_actions import ArchivePrefabInspectorActionsMixin
from cdmw.ui.archive_browser.prefab_json_actions import ArchivePrefabJsonActionsMixin
from cdmw.ui.archive_browser.preview_cache import ArchivePreviewCacheMixin
from cdmw.ui.archive_browser.preview_core_prewarm import ArchivePreviewCorePrewarmMixin
from cdmw.ui.archive_browser.preview_d3d11_parts import ArchivePreviewD3D11PartsMixin
from cdmw.ui.archive_browser.preview_dotnet_lifecycle import ArchivePreviewDotNetLifecycleMixin
from cdmw.ui.archive_browser.preview_details import ArchivePreviewDetailsMixin
from cdmw.ui.archive_browser.preview_layout import ArchivePreviewLayoutMixin
from cdmw.ui.archive_browser.preview_loading import ArchivePreviewLoadingMixin
from cdmw.ui.archive_browser.preview_memory import ArchivePreviewMemoryAuditMixin
from cdmw.ui.archive_browser.preview_native_core import ArchivePreviewNativeCoreLifecycleMixin
from cdmw.ui.archive_browser.preview_panel import ArchivePreviewTextToolsMixin
from cdmw.ui.archive_browser.preview_renderer_controls import ArchivePreviewRendererControlsMixin
from cdmw.ui.archive_browser.preview_result import ArchivePreviewResultMixin
from cdmw.ui.archive_browser.preview_settings import ArchivePreviewSettingsMixin
from cdmw.ui.archive_browser.preview_state import ArchivePreviewStateMixin
from cdmw.ui.archive_browser.preview_timing import ArchivePreviewTimingMixin
from cdmw.ui.archive_browser.preview_zoom import ArchivePreviewZoomMixin
from cdmw.ui.archive_browser.progress import ArchiveProgressMixin
from cdmw.ui.archive_browser.reference_export import ArchiveReferenceExportMixin
from cdmw.ui.archive_browser.reference_preview import ArchiveReferencePreviewMixin
from cdmw.ui.archive_browser.render_lifecycle import ArchiveRenderLifecycleMixin
from cdmw.ui.archive_browser.scan_lifecycle import ArchiveScanLifecycleMixin
from cdmw.ui.archive_browser.sidecar_index import ArchiveSidecarIndexMixin
from cdmw.ui.archive_browser.source_mix_actions import ArchiveSourceMixActionsMixin
from cdmw.ui.archive_browser.source_mix_overlay import ArchiveSourceMixOverlayMixin
from cdmw.ui.archive_browser.source_picker_dialog import ArchiveSourcePickerDialogMixin
from cdmw.ui.archive_browser.static_replacement_dialog import ArchiveStaticReplacementDialogMixin
from cdmw.ui.archive_browser.ui_formatting import ArchiveUiFormattingMixin
from cdmw.ui.archive_browser.virtual_path_lookup import ArchiveVirtualPathLookupMixin
from cdmw.ui.archive_browser.weapon_placement_studio import ArchiveWeaponPlacementStudioMixin
from cdmw.ui.archive_browser.workers import ArchivePreviewWorkerMixin, ArchiveWorkerLifecycleMixin
from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin
from cdmw.ui.shell.about_controller import AboutControllerMixin
from cdmw.ui.shell.about_documentation import AboutDocumentationMixin
from cdmw.ui.shell.close_controller import CloseControllerMixin
from cdmw.ui.shell.dashboard_controller import DashboardControllerMixin
from cdmw.ui.shell.language_controller import LanguageControllerMixin
from cdmw.ui.shell.log_controller import LogControllerMixin
from cdmw.ui.shell.menus import ShellMenusMixin
from cdmw.ui.shell.model_library_bridge import ModelLibraryShellBridgeMixin
from cdmw.ui.shell.navigation_controller import NavigationControllerMixin
from cdmw.ui.shell.path_controller import PathControllerMixin
from cdmw.ui.shell.profile_controller import ProfileControllerMixin
from cdmw.ui.shell.responsiveness_controller import ResponsivenessControllerMixin
from cdmw.ui.shell.root_layout import ShellRootLayoutMixin
from cdmw.ui.shell.settings_autosave import SettingsAutosaveMixin
from cdmw.ui.shell.settings_persistence import SettingsPersistenceMixin
from cdmw.ui.shell.signal_wiring import ShellSignalWiringMixin
from cdmw.ui.shell.startup_controller import StartupPromptMixin
from cdmw.ui.shell.startup_restore import ShellStartupRestoreMixin
from cdmw.ui.shell.support_dialog import SupportDialogMixin
from cdmw.ui.shell.tool_tabs import ShellToolTabsMixin
from cdmw.ui.shell.utility_controller import UtilityControllerMixin
from cdmw.ui.shell.window_bootstrap_state import ShellWindowBootstrapStateMixin
from cdmw.ui.shell.window_runtime_state import ShellWindowRuntimeStateMixin
from cdmw.ui.shell.workspace_controller import WorkspaceControllerMixin
from cdmw.ui.shell.workspace_layout import ShellWorkspaceLayoutMixin
from cdmw.ui.shell.theme_controller import ThemeControllerMixin
from cdmw.ui.texture_workflow.compare_panel import TextureWorkflowComparePanelMixin
from cdmw.ui.texture_workflow.compare_preview import TextureWorkflowComparePreviewMixin
from cdmw.ui.texture_workflow.config_collection import TextureWorkflowConfigCollectionMixin
from cdmw.ui.texture_workflow.dds_output_panel import TextureWorkflowDdsOutputPanelMixin
from cdmw.ui.texture_workflow.editor_bridge import TextureWorkflowEditorBridgeMixin
from cdmw.ui.texture_workflow.editor_handoff import TextureWorkflowEditorHandoffMixin
from cdmw.ui.texture_workflow.paths_panel import TextureWorkflowPathsPanelMixin
from cdmw.ui.texture_workflow.progress_panel import TextureWorkflowProgressPanelMixin
from cdmw.ui.texture_workflow.settings_panel import TextureWorkflowSettingsPanelMixin
from cdmw.ui.texture_workflow.setup_overview_panel import TextureWorkflowSetupOverviewPanelMixin
from cdmw.ui.texture_workflow.setup_panel import TextureWorkflowSetupPanelMixin
from cdmw.ui.texture_workflow.shell_controls import TextureWorkflowShellControlsMixin
from cdmw.ui.texture_workflow.upscale_backend_panel import TextureWorkflowUpscaleBackendPanelMixin
from cdmw.ui.texture_workflow.workflow_profiles_panel import TextureWorkflowProfilesPanelMixin
from cdmw.ui.texture_workflow.workflow_profiles_ui import TextureWorkflowProfilesUiMixin
from cdmw.ui.texture_workflow.workers import TextureWorkflowWorkerMixin
from cdmw.ui.tools.mod_package_retrofit import ArchiveModPackageRetrofitDialogMixin


SHELL_FEATURE_PROVIDERS = (
    AboutControllerMixin,
    AboutDocumentationMixin,
    SupportDialogMixin,
    ShellMenusMixin,
    ShellRootLayoutMixin,
    ShellSignalWiringMixin,
    ShellStartupRestoreMixin,
    ShellToolTabsMixin,
    ShellWorkspaceLayoutMixin,
    ShellWindowBootstrapStateMixin,
    ShellWindowRuntimeStateMixin,
    SettingsPersistenceMixin,
    SettingsAutosaveMixin,
    CloseControllerMixin,
    ResponsivenessControllerMixin,
    LogControllerMixin,
    ThemeControllerMixin,
    LanguageControllerMixin,
    StartupPromptMixin,
    PathControllerMixin,
    UtilityControllerMixin,
    WorkspaceControllerMixin,
    ProfileControllerMixin,
    NavigationControllerMixin,
    DashboardControllerMixin,
    ModelLibraryShellBridgeMixin,
)

ARCHIVE_FEATURE_PROVIDERS = (
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
    ArchiveWeaponPlacementStudioMixin,
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
)

TEXTURE_FEATURE_PROVIDERS = (
    TextureWorkflowComparePanelMixin,
    TextureWorkflowConfigCollectionMixin,
    TextureWorkflowComparePreviewMixin,
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
)

MESH_FEATURE_PROVIDERS = (MeshEditorShellBridgeMixin,)
"""


def _lazy_provider_groups(source: str) -> dict[str, tuple[LazyFeatureProvider, ...]]:
    aliases: dict[str, LazyFeatureProvider] = {}
    groups: dict[str, tuple[LazyFeatureProvider, ...]] = {}
    current_name = ""
    current: list[LazyFeatureProvider] = []
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if line.startswith("from ") and " import " in line:
            module_name, imported_names = line[5:].split(" import ", 1)
            for class_name in (name.strip() for name in imported_names.split(",")):
                key = (module_name, class_name)
                aliases[class_name] = LazyFeatureProvider(
                    module_name,
                    class_name,
                    PROVIDER_MEMBERS[key],
                    PROVIDER_METHOD_ARITIES[key],
                )
            continue
        if current_name:
            if line == ")":
                groups[current_name] = tuple(current)
                current_name = ""
                current = []
            elif line:
                current.append(aliases[line.removesuffix(",")])
            continue
        if "_FEATURE_PROVIDERS = (" not in line:
            continue
        current_name, declaration = (part.strip() for part in line.split("=", 1))
        inline = declaration.removeprefix("(")
        if inline.endswith(")"):
            names = (name.strip() for name in inline[:-1].split(","))
            groups[current_name] = tuple(aliases[name] for name in names if name)
            current_name = ""
    return groups


_GROUPS = _lazy_provider_groups(_PROVIDER_DECLARATIONS)
SHELL_FEATURE_PROVIDERS = _GROUPS["SHELL_FEATURE_PROVIDERS"]
ARCHIVE_FEATURE_PROVIDERS = _GROUPS["ARCHIVE_FEATURE_PROVIDERS"]
TEXTURE_FEATURE_PROVIDERS = _GROUPS["TEXTURE_FEATURE_PROVIDERS"]
MESH_FEATURE_PROVIDERS = _GROUPS["MESH_FEATURE_PROVIDERS"]
del _GROUPS


__all__ = [
    "ARCHIVE_FEATURE_PROVIDERS",
    "MESH_FEATURE_PROVIDERS",
    "SHELL_FEATURE_PROVIDERS",
    "TEXTURE_FEATURE_PROVIDERS",
]
