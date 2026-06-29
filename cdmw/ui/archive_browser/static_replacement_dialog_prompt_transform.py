"""Transform-section binding for static replacement prompt."""

from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dialog_prompt_deps import (
    install_static_replacement_prompt_dependencies,
)
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_open import (
    finish_static_replacement_prompt_open,
)

install_static_replacement_prompt_dependencies(globals())


def finish_static_replacement_prompt_transform(context: dict[str, object]) -> None:
    alignment_setup_options_transform_section = create_alignment_setup_options_transform_section(context)
    (
        _alignment_custom_icon_override_spec, _basic_controls_profile_enabled, _capture_static_preview_baked_transform_state, _coerce_manual_profile_values,
        _complete_external_swap_enabled, _complete_external_swap_mappings, _current_complete_swap_material_profile_token, _current_manual_material_profile_values, _current_material_authority_preview_profile,
        _material_authority_preview_inactive_reason, _material_authority_preview_signature, _modify_original_texture_tuning_enabled,
        _queue_material_authority_adjustment_preview_refresh, _queue_part_transform_preview_update,
        _refresh_manual_material_profile_panel, _refresh_manual_profile_control_effects, _refresh_sidecar_option_state, _replay_alignment_d3d11_fast_transform,
        _save_complete_swap_material_profile, _save_manual_profile_presets, _select_complete_swap_material_profile, _set_manual_profile_dirty,
        _spin_with_slider, _sync_alignment_transform_slider_from_spin, accent_glow_slider, accent_glow_spin,
        alignment_mode_combo, alignment_transform_control_text, alignment_transform_sliders, auto_brightness_slider,
        auto_brightness_spin, channel_value, column, complete_external_swap_checkbox,
        complete_swap_material_profile_combo, complete_swap_profile_store_path, custom_icon_checkbox, custom_icon_file_button,
        custom_icon_folder_button, custom_icon_library_button, custom_icon_source_edit, custom_icon_status,
        custom_icon_target_combo, custom_icon_target_entries, custom_icon_target_graph, edge_relief_slider,
        edge_relief_source_combo, edge_relief_spin, external_material_reset_checkbox, flip_direction_checkbox,
        global_gloss_reduction_hint, global_gloss_reduction_slider, global_gloss_reduction_spin, inject_base_color_checkbox,
        manual_profile_apply_button, manual_profile_change_status, manual_profile_control_text, manual_profile_control_tooltips,
        manual_profile_controls, manual_profile_default_values, manual_profile_dirty, manual_profile_effect_widgets,
        manual_profile_group, manual_profile_layout, manual_profile_preset_combo, manual_profile_preset_details_edit,
        manual_profile_preset_name_edit, manual_profile_preset_recommended_edit, manual_profile_presets, manual_profile_presets_key,
        manual_profile_ready, manual_profile_saved_values, manual_profile_settings_key, material_authority_section,
        modify_original_texture_tuning_checkbox, modify_original_texture_tuning_enabled_key,
        modify_original_texture_tuning_section, object_name,
        offset_x_spin, offset_y_spin, offset_z_spin, part_glow_color_checkbox,
        part_glow_color_pick_button, part_glow_color_spins, profile_name, prune_unmapped_original_dds_checkbox,
        rebuild_sidecar_checkbox, rotate_x_spin, rotate_y_spin, rotate_z_spin,
        save_generated_icon_to_library_checkbox, scale_link_checkbox, scale_spins, scale_syncing,
        scale_to_length_checkbox, scale_x_spin, scale_y_spin, scale_z_spin,
        setup_texture_flip_u_checkbox, setup_texture_flip_v_checkbox, setup_texture_rotate_combo, slider_maximum,
        slider_minimum, slider_scale, source_brightness_slider, source_brightness_spin,
        source_color_faithful_checkbox, texture_output_size_combo, tilt_step_spin, tone_contrast_slider,
        tone_contrast_spin, tooltip, transform_layout, transform_layout_specs,
        transform_slider_specs, true_source_basic_group, true_source_basic_hint, true_source_basic_reset_button,
        unsafe_material_preflight_checkbox, width,
    ) = static_replacement_section_values(
        alignment_setup_options_transform_section,
        (
            "_alignment_custom_icon_override_spec", "_basic_controls_profile_enabled", "_capture_static_preview_baked_transform_state", "_coerce_manual_profile_values",
            "_complete_external_swap_enabled", "_complete_external_swap_mappings", "_current_complete_swap_material_profile_token", "_current_manual_material_profile_values", "_current_material_authority_preview_profile",
            "_material_authority_preview_inactive_reason", "_material_authority_preview_signature", "_modify_original_texture_tuning_enabled",
            "_queue_material_authority_adjustment_preview_refresh", "_queue_part_transform_preview_update",
            "_refresh_manual_material_profile_panel", "_refresh_manual_profile_control_effects", "_refresh_sidecar_option_state", "_replay_alignment_d3d11_fast_transform",
            "_save_complete_swap_material_profile", "_save_manual_profile_presets", "_select_complete_swap_material_profile", "_set_manual_profile_dirty",
            "_spin_with_slider", "_sync_alignment_transform_slider_from_spin", "accent_glow_slider", "accent_glow_spin",
            "alignment_mode_combo", "alignment_transform_control_text", "alignment_transform_sliders", "auto_brightness_slider",
            "auto_brightness_spin", "channel_value", "column", "complete_external_swap_checkbox",
            "complete_swap_material_profile_combo", "complete_swap_profile_store_path", "custom_icon_checkbox", "custom_icon_file_button",
            "custom_icon_folder_button", "custom_icon_library_button", "custom_icon_source_edit", "custom_icon_status",
            "custom_icon_target_combo", "custom_icon_target_entries", "custom_icon_target_graph", "edge_relief_slider",
            "edge_relief_source_combo", "edge_relief_spin", "external_material_reset_checkbox", "flip_direction_checkbox",
            "global_gloss_reduction_hint", "global_gloss_reduction_slider", "global_gloss_reduction_spin", "inject_base_color_checkbox",
            "manual_profile_apply_button", "manual_profile_change_status", "manual_profile_control_text", "manual_profile_control_tooltips",
            "manual_profile_controls", "manual_profile_default_values", "manual_profile_dirty", "manual_profile_effect_widgets",
            "manual_profile_group", "manual_profile_layout", "manual_profile_preset_combo", "manual_profile_preset_details_edit",
            "manual_profile_preset_name_edit", "manual_profile_preset_recommended_edit", "manual_profile_presets", "manual_profile_presets_key",
            "manual_profile_ready", "manual_profile_saved_values", "manual_profile_settings_key", "material_authority_section",
            "modify_original_texture_tuning_checkbox", "modify_original_texture_tuning_enabled_key",
            "modify_original_texture_tuning_section", "object_name",
            "offset_x_spin", "offset_y_spin", "offset_z_spin", "part_glow_color_checkbox",
            "part_glow_color_pick_button", "part_glow_color_spins", "profile_name", "prune_unmapped_original_dds_checkbox",
            "rebuild_sidecar_checkbox", "rotate_x_spin", "rotate_y_spin", "rotate_z_spin",
            "save_generated_icon_to_library_checkbox", "scale_link_checkbox", "scale_spins", "scale_syncing",
            "scale_to_length_checkbox", "scale_x_spin", "scale_y_spin", "scale_z_spin",
            "setup_texture_flip_u_checkbox", "setup_texture_flip_v_checkbox", "setup_texture_rotate_combo", "slider_maximum",
            "slider_minimum", "slider_scale", "source_brightness_slider", "source_brightness_spin",
            "source_color_faithful_checkbox", "texture_output_size_combo", "tilt_step_spin", "tone_contrast_slider",
            "tone_contrast_spin", "tooltip", "transform_layout", "transform_layout_specs",
            "transform_slider_specs", "true_source_basic_group", "true_source_basic_hint", "true_source_basic_reset_button",
            "unsafe_material_preflight_checkbox", "width",
        ),
    )
    context.update(locals())
    finish_static_replacement_prompt_open(context)


__all__ = ["finish_static_replacement_prompt_transform"]
