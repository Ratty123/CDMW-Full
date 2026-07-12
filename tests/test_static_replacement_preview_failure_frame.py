from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from cdmw.ui.archive_browser.static_replacement_dialog_remaining_callbacks import (
    create_alignment_static_preview_refresh_callbacks,
)


def test_failed_overlay_build_keeps_last_original_frame_preview() -> None:
    independently_normalized_source = object()
    original_reference = object()
    replacement_mesh = object()
    original_mesh = object()
    build_preview = MagicMock(side_effect=RuntimeError("preview build failed"))
    clone_preview = MagicMock()
    record_runtime_event = MagicMock()
    set_loading = MagicMock()
    set_performance = MagicMock()
    clear_pending = MagicMock()
    side_by_side = MagicMock()
    overlay = MagicMock()
    replacement_only = MagicMock()
    preview_mode_combo = MagicMock()
    preview_mode_combo.currentData.return_value = "overlay"
    mesh_edit_enabled_checkbox = MagicMock()
    mesh_edit_enabled_checkbox.isChecked.return_value = False
    zero_spin = MagicMock()
    zero_spin.value.return_value = 0.0
    edge_relief_source_combo = MagicMock()
    edge_relief_source_combo.currentData.return_value = "hybrid"
    late_transform_controls: dict[str, object] = {}
    route = SimpleNamespace(
        require_original_reference=False,
        mesh_edit_direct_source_preview=False,
        replacement_only_direct_source_preview=False,
        source_owned_direct_source_preview=False,
        can_build_source_geometry=True,
    )
    failed_presentation = SimpleNamespace(summary="failed", details="preview build failed")
    context: dict[str, object] = {
        "_get_replacement_preview_model": lambda: independently_normalized_source,
        "_get_replacement_mesh_for_mapping": lambda: replacement_mesh,
        "_get_replacement_mesh_base_for_mapping": lambda: None,
        "_get_original_reference_preview_model": lambda: original_reference,
        "_get_texture_sets": lambda: (),
        "_get_texture_override_preview_specs": lambda: (),
        "_record_runtime_event": record_runtime_event,
        "_set_alignment_d3d11_loading": set_loading,
        "_set_preview_performance_status": set_performance,
        "_clear_source_parts_preview_rebuild_pending": clear_pending,
        "_alignment_d3d11_alignment_preview_failed_performance_helper": lambda _message: failed_presentation,
        "_current_alignment_transform_generation": lambda: 1,
        "_alignment_mesh_edit_tab_active": lambda: False,
        "_modify_original_texture_tuning_enabled": lambda: False,
        "_complete_external_swap_enabled": lambda: False,
        "_current_complete_swap_material_profile_token": lambda: "",
        "_current_dialog_mappings_for_preview": lambda: (),
        "_current_static_placement_snapshot": lambda *_args, **_kwargs: {},
        "_mapped_source_indices": lambda _mappings: (),
        "_original_texture_preview_material_preview_enabled_helper": lambda *_args: False,
        "_static_preview_refresh_route_state_helper": lambda **_kwargs: route,
        "_alignment_d3d11_record_direct_source_preview_flags_helper": lambda *_args, **_kwargs: False,
        "_direct_source_preview_indices_helper": lambda *_args, **_kwargs: (),
        "_should_use_direct_source_preview_helper": lambda *_args, **_kwargs: False,
        "_static_options_from_placement_snapshot": lambda *_args, **_kwargs: object(),
        "_alignment_preview_source_face_limit": lambda: 0,
        "_clone_preview_model": clone_preview,
        "build_static_replacement_preview_mesh": build_preview,
        "preview_mode_combo": preview_mode_combo,
        "mesh_edit_enabled_checkbox": mesh_edit_enabled_checkbox,
        "preview_controls_ready": {"ready": True},
        "direct_source_preview_index_map": {},
        "source_overlay_preview_index_map": {},
        "source_selection_overlay_preview_index_map": {},
        "source_selection_overlay_editor_id_map": {},
        "preview_submesh_index_map": {},
        "static_preview_geometry_cache": {},
        "static_preview_prepared_cache": {},
        "appended_source_indices": (),
        "original_mesh_for_mapping": original_mesh,
        "original_texture_preview_state": object(),
        "static_dialog_preview": side_by_side,
        "overlay_dialog_preview": overlay,
        "replacement_only_preview": replacement_only,
        "prompt_shell_context": late_transform_controls,
        "global_gloss_reduction_spin": None,
        "edge_relief_spin": None,
        "edge_relief_source_combo": None,
        "accent_glow_spin": None,
        "auto_brightness_spin": None,
        "source_brightness_spin": None,
        "tone_contrast_spin": None,
        "material_authority_preview_signature_state": {},
        "material_authority_preview_texture_slots": {},
        "texture_overrides_dirty": {"dirty": False},
        "modify_original_clone_mode": False,
        "defer_original_texture_preview": False,
        "dialog_title": "Mesh Import",
        "entry": SimpleNamespace(path="target.pac"),
        "time": time,
    }
    callbacks = create_alignment_static_preview_refresh_callbacks(context)
    late_transform_controls.update(
        {
            "global_gloss_reduction_spin": zero_spin,
            "edge_relief_spin": zero_spin,
            "edge_relief_source_combo": edge_relief_source_combo,
            "accent_glow_spin": zero_spin,
            "auto_brightness_spin": zero_spin,
            "source_brightness_spin": zero_spin,
            "tone_contrast_spin": zero_spin,
        }
    )

    callbacks._safe_refresh_static_dialog_preview()

    build_preview.assert_called_once()
    clone_preview.assert_not_called()
    for widget in (side_by_side, overlay, replacement_only):
        widget.set_model.assert_not_called()
        widget.set_model_preserving_view.assert_not_called()
    assert record_runtime_event.call_args.args[0] == "mesh_alignment_preview_refresh_failed"
    assert record_runtime_event.call_args.kwargs["message"] == "preview build failed"
    set_loading.assert_called_once_with(False, "Preview failed: preview build failed")
    set_performance.assert_called_once_with("failed", details="preview build failed")
    clear_pending.assert_called_once_with()
