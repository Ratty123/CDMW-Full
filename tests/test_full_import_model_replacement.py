from __future__ import annotations

from pathlib import Path

from cdmw.modding.full_import_model_replacement import (
    FULL_IMPORT_MODEL_REPLACEMENT_PROFILE,
    apply_full_import_model_replacement_preset,
    full_import_model_replacement_external_file_filter,
)
from cdmw.modding.static_mesh_replacer import (
    StaticMeshReplacementOptions,
    StaticReplacementTransform,
    StaticSubmeshMapping,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _source(*parts: str) -> str:
    return (REPO_ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def test_full_import_preset_sets_source_authority_defaults() -> None:
    mapping = StaticSubmeshMapping(
        target_submesh_index=1,
        target_submesh_name="blade",
        source_submesh_indices=[0, 2],
        target_material_slot_index=1,
    )
    options = apply_full_import_model_replacement_preset(
        StaticMeshReplacementOptions(
            submesh_mappings=[mapping],
            transform=StaticReplacementTransform(
                alignment_mode="manual",
                scale_to_original_length=False,
                scale=0.5,
            ),
            texture_output_size_mode="target",
            complete_swap_material_profile="arm_standard",
        )
    )

    assert options.submesh_mappings == [mapping]
    assert options.rebuild_material_sidecar is True
    assert options.complete_external_swap is True
    assert options.full_import_model_replacement is True
    assert options.neutralize_inherited_material_layers is True
    assert options.complete_external_material_reset is True
    assert options.enable_missing_base_color_parameters is True
    assert options.prune_unmapped_original_texture_parameters is True
    assert options.prune_removed_target_texture_parameters is True
    assert options.texture_output_size_mode == "source"
    assert options.complete_swap_atlas_mode == "auto_when_needed"
    assert options.complete_swap_material_profile == FULL_IMPORT_MODEL_REPLACEMENT_PROFILE
    assert options.accent_glow_strength == 0.0
    assert options.transform.alignment_mode == "manual"
    assert options.transform.scale == 0.5
    assert options.transform.scale_to_original_length is True


def test_full_import_entry_point_is_not_user_exposed() -> None:
    source = "\n".join(
        (
            _source("cdmw", "ui", "archive_browser", "preview_layout.py"),
            _source("cdmw", "ui", "archive_browser", "action_controls.py"),
            _source("cdmw", "ui", "archive_browser", "actions.py"),
            _source("cdmw", "ui", "archive_browser", "import_actions.py"),
            _source("cdmw", "ui", "archive_browser", "mesh_launch_flow.py"),
            _source("cdmw", "ui", "shell", "signal_wiring.py"),
        )
    )
    main_window_source = _source("cdmw", "ui", "main_window.py")

    assert "archive_model_full_import_button" not in source
    assert "_full_import_current_archive_model_replacement" not in source
    assert "_start_full_import_model_replacement" not in source
    assert '"Full Import Model Replacement..."' not in source
    assert "Full Import Model Replacement" not in main_window_source


def test_full_import_backend_preset_is_retained_but_not_launched_from_app_ui() -> None:
    source = "\n".join(
        (
            _source("cdmw", "ui", "archive_browser", "mesh_import_export.py"),
            _source("cdmw", "ui", "archive_browser", "mesh_patch_flow.py"),
            _source("cdmw", "ui", "archive_browser", "static_replacement_dialog.py"),
            _source("cdmw", "ui", "archive_browser", "static_replacement_dialog_prompt.py"),
            _source("cdmw", "ui", "archive_browser", "static_replacement_dialog_callback_factories.py"),
            _source("cdmw", "ui", "archive_browser", "static_replacement_dialog_workflow_shell.py"),
        )
    )

    assert "full_import_model_replacement=bool(setup.full_import_model_replacement)" in source
    assert "apply_full_import_model_replacement_preset(options)" in source
    assert "setTabVisible" in source
    assert "control_tabs.setTabVisible(control_tabs.indexOf(mesh_edit_tab), False)" in source
    assert "control_tabs.setTabVisible(control_tabs.indexOf(textures_tab), False)" in source
    assert "for advanced_tab in (parts_tab,):" in source
    assert "def _start_full_import_model_replacement" not in _source(
        "cdmw", "ui", "archive_browser", "mesh_launch_flow.py"
    )


def test_full_import_locks_advanced_ui_but_leaves_transform_live() -> None:
    setup_source = _source("cdmw", "ui", "archive_browser", "static_replacement_dialog_ui_sections.py")
    callback_source = _source("cdmw", "ui", "archive_browser", "static_replacement_dialog_callback_factories.py")

    assert "Full Import Model Replacement preset locked" in setup_source
    assert "Only placement transform is editable" in setup_source
    assert "alignment_mode_combo.setCurrentIndex(max(0, alignment_mode_combo.findData(\"manual\")))" in setup_source
    assert "scale_to_length_checkbox.setChecked(True)" in setup_source
    assert "flip_direction_checkbox.setChecked(False)" in setup_source
    assert "true_source_basic_group.setVisible(False)" in setup_source
    assert "manual_profile_group.setVisible(False)" in setup_source
    assert "setup_texture_orientation_widget.setVisible(False)" in setup_source
    assert "if modify_original_clone_mode:" in callback_source
    assert "if modify_original_clone_mode or bool(context.get(\"full_import_model_replacement\")):" not in callback_source
    assert "Material Authority tuning is locked by Full Import Model Replacement." in callback_source


def test_full_import_build_and_transform_callbacks_do_not_stay_busy_on_exceptions() -> None:
    source = _source("cdmw", "ui", "archive_browser", "static_replacement_dialog_callback_factories.py")
    prompt_source = _source("cdmw", "ui", "archive_browser", "static_replacement_dialog_prompt.py")

    accept_start = source.index("def _accept_static_options_after_status_paint() -> None:")
    accept_end = source.index("options_route = _alignment_build_options_route_helper", accept_start)
    accept_block = source[accept_start:accept_end]
    assert "try:" in accept_block
    assert "except Exception as exc:" in accept_block
    assert "_finish_alignment_build_state(_alignment_build_failed_status_helper(exc), False)" in accept_block

    assert "stop_worker = context.get(\"_alignment_d3d11_stop_worker\")" in source
    assert "if callable(stop_worker):\n            stop_worker()" in source
    assert "if callable(_current_alignment_transform_generation)" in source
    assert "if callable(_alignment_d3d11_preview_active)" in source
    assert "if not callable(_part_source_indices_for_commit_helper):\n            return []" in source
    assert "if callable(_alignment_geometry_tab_active)" in source
    assert "if callable(_replay_alignment_d3d11_fast_transform):\n                    _replay_alignment_d3d11_fast_transform()" in source
    preview_mode_start = source.index("def create_alignment_preview_mode_callbacks")
    preview_mode_end = source.index("def create_alignment_preview_model_callbacks", preview_mode_start)
    preview_mode_source = source[preview_mode_start:preview_mode_end]
    assert "def _d3d11_preview_active() -> bool:" in preview_mode_source
    assert "if not callable(_alignment_d3d11_preview_active):\n            return False" in preview_mode_source
    assert "d3d11_active=_alignment_d3d11_preview_active()" not in preview_mode_source
    assert "def _sync_highlight_sets_when_ready(*args, **kwargs):" in prompt_source
    assert "if callable(callback):\n            return callback(*args, **kwargs)" in prompt_source


def test_texture_uv_callbacks_are_created_after_controls_exist() -> None:
    source = _source("cdmw", "ui", "archive_browser", "static_replacement_dialog_ui_sections.py")

    combo_index = source.index("texture_transform_material_combo = QComboBox()")
    loading_index = source.index("texture_transform_controls_loading = _texture_transform_controls_loading_initial_state_helper()")
    callback_index = source.index("alignment_texture_detail_uv_callbacks = create_alignment_texture_detail_uv_callbacks")
    connect_index = source.index("texture_transform_material_combo.currentIndexChanged.connect")
    assert combo_index < loading_index < callback_index < connect_index


def test_full_import_setup_missing_advanced_callbacks_do_not_abort_builder() -> None:
    routing_source = _source("cdmw", "ui", "archive_browser", "static_replacement_dialog_routing_callbacks.py")
    texture_callback_source = _source("cdmw", "ui", "archive_browser", "static_replacement_dialog_texture_callbacks.py")

    assert "if not callable(_original_part_texture_intent_rows_helper):\n            return []" in routing_source
    assert "except RuntimeError:\n            return" in texture_callback_source


def test_full_import_blocks_missing_or_unmapped_sidecar_authority() -> None:
    source = _source("cdmw", "core", "archive_mesh_import_preview.py")

    assert "full_import_model_replacement" in source
    assert "requires a target material sidecar" in source
    assert "requires generated target material sidecar output" in source
    assert "could not generate a patched target material sidecar" in source


def test_full_import_file_filter_accepts_external_sources_only() -> None:
    file_filter = full_import_model_replacement_external_file_filter()

    assert "*.obj" in file_filter
    assert "*.dae" in file_filter
    assert "*.gltf" in file_filter
    assert "*.glb" in file_filter
    assert "*.zip" in file_filter
    assert "*.pac" not in file_filter
    assert "*.pam" not in file_filter
