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
        material_sidecar_entry = self._current_or_related_material_sidecar_entry()
        can_family_actions = self._archive_entry_supports_family_context_actions(current_entry)
        selected_archive_entries = self._selected_archive_entries()
        appearance_entry = current_entry
        appearance_extensions = {".app_xml", ".pac", ".pam", ".pamlod", ".prefab", ".pappt", ".prefabdata_xml"}
        can_appearance_composite = (
            isinstance(appearance_entry, ArchiveEntry)
            and str(appearance_entry.extension or "").lower() in appearance_extensions
        )
        swap_selection_entries = list(selected_archive_entries)
        if isinstance(appearance_entry, ArchiveEntry) and all(
            self._appearance_composite_entry_key(existing) != self._appearance_composite_entry_key(appearance_entry)
            for existing in swap_selection_entries
        ):
            swap_selection_entries.append(appearance_entry)
        swap_app_count = sum(1 for entry in swap_selection_entries if str(entry.extension or "").lower() == ".app_xml")
        swap_model_count = sum(1 for entry in swap_selection_entries if str(entry.extension or "").lower() in {".pac", ".pam", ".pamlod"})
        can_appearance_swap = (
            isinstance(appearance_entry, ArchiveEntry)
            and str(appearance_entry.extension or "").lower() in {".app_xml", ".pac", ".pam", ".pamlod"}
        ) or (swap_app_count == 1 and swap_model_count == 1)
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
        material_reason = (
            busy_reason
            if not controls_enabled
            else "select a material sidecar, or a model with a resolved material sidecar, first"
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
        appearance_swap_reason = (
            busy_reason
            if not controls_enabled
            else "select one target body .app_xml and one donor .pac/.pam/.pamlod model, or select a donor model to search exact app XML matches"
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
            self.archive_action_source_mix_button,
            controls_enabled and has_current_entry,
            "Build a loose package by matching source files to the selected archive target family.",
            current_entry_reason,
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
            self.archive_model_import_preview_button,
            controls_enabled and can_mesh_actions,
            "Rebuild the selected archive mesh from OBJ, DAE, glTF, or GLB and preview it without writing files.",
            mesh_reason,
        )
        self._set_action_button_state(
            self.archive_model_import_dds_preview_button,
            controls_enabled and can_mesh_actions,
            "Apply one local DDS onto the current archive mesh preview without patching or exporting.",
            mesh_reason,
        )
        self._set_action_button_state(
            self.archive_model_import_patch_button,
            controls_enabled and can_mesh_actions,
            "Rebuild the selected archive mesh from OBJ, DAE, glTF, or GLB, then patch or export a loose package.",
            mesh_reason,
        )
        self._set_action_button_state(
            self.archive_model_modify_original_button,
            controls_enabled and can_mesh_actions,
            "Create a temporary editable clone from the selected archive mesh, then re-import it through Mesh Replacement Geometry.",
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
            self.archive_appearance_swap_button,
            controls_enabled and can_appearance_swap,
            "Appearance Armor Swap: select one target body app XML and one donor PAC/PAM/PAMLOD. "
            "Builds a mod-ready loose package; the target app XML, skeleton, ragdoll, and part-hide files are not patched.",
            appearance_swap_reason,
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
        pending_swap_target = self.pending_in_game_mesh_swap_target
        if pending_swap_target is not None and mesh_entry is not None:
            if self._same_archive_entry(mesh_entry, pending_swap_target):
                self.archive_model_swap_in_game_button.setText("Cancel Swap Target")
                swap_tooltip = f"Cancel the pending in-game mesh swap target: {pending_swap_target.path}"
                self._set_action_button_state(
                    self.archive_model_swap_in_game_button,
                    controls_enabled and can_mesh_actions,
                    swap_tooltip,
                    mesh_reason,
                )
            else:
                self.archive_model_swap_in_game_button.setText("Use as Swap Source...")
                swap_tooltip = f"Use the selected mesh as the source for pending target: {pending_swap_target.path}"
                self._set_action_button_state(
                    self.archive_model_swap_in_game_button,
                    controls_enabled and can_mesh_actions,
                    swap_tooltip,
                    mesh_reason,
                )
        else:
            self.archive_model_swap_in_game_button.setText("Start In-Game Swap...")
            self._set_action_button_state(
                self.archive_model_swap_in_game_button,
                controls_enabled and can_mesh_actions,
                "Set the selected archive mesh as the swap target, then choose the source mesh in the existing Archive Browser.",
                mesh_reason,
            )
        self._set_action_button_state(
            self.archive_material_values_button,
            controls_enabled and material_sidecar_entry is not None,
            "Read recognized values from a companion .pac_xml/.pam_xml/.pamlod_xml/.pami material sidecar and export edited values as a mod-ready package.",
            material_reason,
        )
        self._sync_archive_model_action_menu_buttons()
        self.archive_model_preview_settings_button.setEnabled(True)
        d3d11_backend_active = self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11
        self.archive_isolated_renderer_button.setText("Reload D3D11")
        self.archive_isolated_renderer_button.setVisible(bool(d3d11_backend_active and can_export_preview))
        self.archive_isolated_renderer_button.setEnabled(
            bool(d3d11_backend_active and can_export_preview and controls_enabled)
        )
        preview_settings = self._current_model_preview_render_settings()
        for widget in self._archive_model_preview_widgets():
            if hasattr(widget, "set_use_textures"):
                widget.set_use_textures(bool(preview_settings.use_textures_by_default and supports_textures))
            if hasattr(widget, "set_high_quality_textures"):
                widget.set_high_quality_textures(bool(preview_settings.high_quality_by_default and supports_textures))
        self._sync_archive_model_preview_debug_controls(preview_model)
        self._update_archive_texture_reference_action_controls()
