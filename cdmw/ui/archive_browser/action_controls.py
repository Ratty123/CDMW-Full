"""Archive model action enablement and tooltip state."""

from __future__ import annotations

from typing import Optional

from cdmw.models import ArchiveEntry
from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_D3D11


class ArchiveBrowserActionControlsMixin:
    """Synchronize Archive Browser action buttons with the current selection."""

    def _update_archive_model_action_controls(self, preview_model: Optional[object]) -> None:
        current_entry = self._current_archive_entry()
        mesh_entry = self._current_archive_mesh_entry()
        hkx_entry = self._current_archive_hkx_entry()
        binary_sidecar_entry = self._current_archive_binary_sidecar_entry()
        controls_enabled = self.worker_thread is None
        has_current_entry = isinstance(current_entry, ArchiveEntry)
        can_mesh_actions = mesh_entry is not None
        can_hkx_actions = hkx_entry is not None
        hkx_placement_candidates = self._current_archive_hkx_placement_candidates()
        can_hkx_placement = bool(hkx_placement_candidates)
        can_binary_sidecar_actions = binary_sidecar_entry is not None
        can_export_preview = preview_model is not None and not self.archive_preview_showing_loose
        supports_textures = can_export_preview and self._archive_model_preview_supports_textures(preview_model)
        can_family_actions = self._archive_entry_supports_family_context_actions(current_entry)
        appearance_entry = current_entry
        appearance_extensions = {".app_xml", ".pac", ".pam", ".pamlod", ".prefab", ".pappt", ".prefabdata_xml"}
        can_appearance_composite = (
            isinstance(appearance_entry, ArchiveEntry)
            and str(appearance_entry.extension or "").lower() in appearance_extensions
        )
        busy_reason = "wait for the current background task to finish"
        mesh_reason = busy_reason if not controls_enabled else "select a mesh/model archive entry first"
        hkx_reason = busy_reason if not controls_enabled else "select a .hkx or .hkt archive entry first"
        hkx_placement_reason = (
            busy_reason
            if not controls_enabled
            else "select a .hkx/.hkt file, or a .pac/.pam/.pamlod model with a related HKX/HKT file, first"
        )
        sidecar_reason = (
            busy_reason
            if not controls_enabled
            else "select a structured sidecar/metadata archive entry first"
        )
        current_entry_reason = busy_reason if not controls_enabled else "select an archive file first"
        family_reason = (
            busy_reason
            if not controls_enabled
            else "select an archive file with recoverable asset-family relationships first"
        )
        appearance_reason = (
            busy_reason
            if not controls_enabled
            else "select an .app_xml, .pac/.pam/.pamlod, .prefabdata_xml, .prefab, or .pappt file first"
        )
        self._set_action_button_state(
            self.archive_action_preview_button,
            controls_enabled and has_current_entry,
            "Render the selected archive file in Archive Preview.",
            current_entry_reason,
        )
        self._set_action_button_state(
            self.archive_action_open_preview_window_button,
            controls_enabled and has_current_entry,
            "Open the selected archive file in a separate preview window.",
            current_entry_reason,
        )
        self._set_action_button_state(
            self.archive_action_copy_filename_button,
            has_current_entry,
            "Copy only the archive file name, without folders.",
            "select an archive file first",
        )
        self._set_action_button_state(
            self.archive_action_export_file_button,
            controls_enabled and has_current_entry,
            "Export the selected archive file bytes to a chosen location.",
            current_entry_reason,
        )
        self._set_action_button_state(
            self.archive_action_extract_file_button,
            controls_enabled and has_current_entry,
            "Extract the selected archive file through the Archive Extract workflow.",
            current_entry_reason,
        )
        self._set_action_button_state(
            self.archive_action_show_only_file_button,
            has_current_entry,
            "Scope the Archive Browser to only the selected file.",
            "select an archive file first",
        )
        self._set_action_button_state(
            self.archive_action_asset_family_button,
            controls_enabled and can_family_actions,
            "Open the recovered asset family for the selected archive file.",
            family_reason,
        )
        self._set_action_button_state(
            self.archive_action_filter_to_family_button,
            controls_enabled and can_family_actions,
            "Filter Archive Files to the required/recommended files in this Asset Family.",
            family_reason,
        )
        self._set_action_button_state(
            self.archive_action_export_family_button,
            controls_enabled and can_family_actions,
            "Export the resolved files in the selected asset family.",
            family_reason,
        )
        self._set_action_button_state(
            self.archive_action_character_dependency_button,
            controls_enabled and can_mesh_actions,
            "Collect the selected body/model with its strict appearance, prefab, material, texture, skeleton, physics, and motion dependencies.",
            mesh_reason,
        )
        self._set_action_button_state(
            self.archive_model_export_obj_button,
            controls_enabled and (can_mesh_actions or can_export_preview),
            "Export the selected archive mesh, or the currently shown model preview, as OBJ.",
            busy_reason if not controls_enabled else "select a mesh entry or open a model preview first",
        )
        self._set_action_button_state(
            self.archive_model_export_fbx_button,
            controls_enabled and can_mesh_actions,
            "Export the selected archive mesh as FBX. PAC exports also try to attach the matching PAB skeleton.",
            mesh_reason,
        )
        self._set_action_button_state(
            self.archive_model_open_mesh_editor_button,
            controls_enabled and can_mesh_actions,
            "Open the selected archive mesh directly in the resident mesh-authoring workspace.",
            mesh_reason,
        )
        self._set_action_button_state(
            self.archive_appearance_composite_button,
            controls_enabled and can_appearance_composite,
            "Preview a read-only app XML appearance composite or selected prefab/socket model evidence. "
            "Multi-select one app XML and one PAC/PAM/PAMLOD to preview a what-if component replacement. No game files are modified.",
            appearance_reason,
        )
        self._set_action_button_state(
            self.archive_hkx_export_json_button,
            controls_enabled and can_hkx_actions,
            "Export a documented editable JSON patch for decoded Crimson Desert HKX geometry.",
            hkx_reason,
        )
        self._set_action_button_state(
            self.archive_hkx_import_json_button,
            controls_enabled and can_hkx_actions,
            "Apply fixed-size numeric edits from an exported HKX JSON patch and write a mod-ready loose HKX package.",
            hkx_reason,
        )
        self._set_action_button_state(
            self.archive_hkx_export_xml_button,
            controls_enabled and can_hkx_actions,
            "Export a documented CDMW XML patch for decoded Crimson Desert HKX geometry.",
            hkx_reason,
        )
        self._set_action_button_state(
            self.archive_hkx_export_havok_xml_view_button,
            controls_enabled and can_hkx_actions,
            "Export a read-only hkpackfile/hkobject/hkparam XML view for browsing with Havok-style tools.",
            hkx_reason,
        )
        self._set_action_button_state(
            self.archive_hkx_import_xml_button,
            controls_enabled and can_hkx_actions,
            "Apply fixed-size numeric edits from a CDMW HKX XML patch and write a mod-ready loose HKX package.",
            hkx_reason,
        )
        self._set_action_button_state(
            self.archive_hkx_edit_button,
            controls_enabled and can_hkx_actions,
            "Open an editable HKX patch in-app, then write supported edits as a mod-ready loose HKX package.",
            hkx_reason,
        )
        self._set_action_button_state(
            self.archive_hkx_placement_button,
            controls_enabled and can_hkx_placement,
            "Edit the related HKX/HKT directly on Placement. If the selected model has multiple HKX/HKT files, choose which one to inspect.",
            hkx_placement_reason,
        )
        self._set_action_button_state(
            self.archive_sidecar_export_json_button,
            controls_enabled and can_binary_sidecar_actions,
            "Export an experimental read-only JSON decode document for structured metadata/animation sidecars.",
            sidecar_reason,
        )
        self._set_action_button_state(
            self.archive_sidecar_inspect_button,
            controls_enabled and can_binary_sidecar_actions,
            "Inspect structured metadata/animation binaries in-app. Editing stays disabled until the schema is proven safe.",
            sidecar_reason,
        )
        self._sync_archive_model_action_menu_buttons()
        self.archive_model_preview_settings_button.setEnabled(True)
        d3d11_backend_active = self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11
        current_result = getattr(self, "current_archive_preview_result", None)
        resident_texture_action_available = bool(
            not self.archive_preview_showing_loose
            and mesh_entry is not None
            and (
                str(getattr(current_result, "dotnet_preview_package_path", "") or "").strip()
                or getattr(self, "archive_isolated_renderer_active_package", None) is not None
            )
        )
        self._sync_archive_model_toolbar_toggles(
            resident_available=bool(d3d11_backend_active and resident_texture_action_available),
            controls_enabled=bool(controls_enabled),
        )
        preview_settings = self._current_model_preview_render_settings()
        for widget in self._archive_model_preview_widgets():
            if hasattr(widget, "set_use_textures"):
                widget.set_use_textures(bool(preview_settings.use_textures_by_default and supports_textures))
            if hasattr(widget, "set_high_quality_textures"):
                widget.set_high_quality_textures(bool(preview_settings.high_quality_by_default and supports_textures))
        self._sync_archive_model_preview_debug_controls(preview_model)
        self._update_archive_texture_reference_action_controls()
