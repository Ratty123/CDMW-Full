"""Persist lazily constructed Texture Workflow panels."""

from __future__ import annotations

import json
from typing import List, Sequence

from cdmw.constants import (
    DDS_SIZE_MODE_ORIGINAL,
    DEFAULT_UPSCALE_BACKEND,
    DEFAULT_UPSCALE_POST_CORRECTION,
    DEFAULT_UPSCALE_TEXTURE_PRESET,
    ENABLE_AUTOMATIC_TEXTURE_RULES,
    ENABLE_MOD_READY_LOOSE_EXPORT,
    ENABLE_UNSAFE_TECHNICAL_OVERRIDE,
    MOD_READY_CREATE_NO_ENCRYPT,
    MOD_READY_EXPORT_ROOT,
    MOD_READY_PACKAGE_AUTHOR,
    MOD_READY_PACKAGE_DESCRIPTION,
    MOD_READY_PACKAGE_NEXUS_URL,
    MOD_READY_PACKAGE_TITLE,
    MOD_READY_PACKAGE_VERSION,
    REALESRGAN_NCNN_EXE_PATH,
    REALESRGAN_NCNN_EXTRA_ARGS,
    REALESRGAN_NCNN_MODEL_DIR,
    REALESRGAN_NCNN_MODEL_NAME,
    REALESRGAN_NCNN_SCALE,
    REALESRGAN_NCNN_TILE_SIZE,
    RETRY_SMALLER_TILE_ON_FAILURE,
    UPSCALE_BACKEND_CHAINNER,
    UPSCALE_BACKEND_NONE,
    UPSCALE_BACKEND_REALESRGAN_NCNN,
)
from cdmw.domain.packages.export_policy import MOD_PACKAGE_MANAGER_PROFILES, mod_package_export_options_for_manager
from cdmw.domain.textures.profiles import (
    build_default_texture_workflow_profiles,
    build_default_texture_workflow_rules,
    should_seed_default_texture_workflow_state,
    upgrade_default_texture_workflow_state,
)
from cdmw.domain.textures.rules import (
    coerce_texture_workflow_profiles,
    coerce_texture_workflow_rules,
    migrate_legacy_texture_rules_to_structured,
)


def finish_texture_workflow_panel_body(workspace, panel: str) -> None:
    if not getattr(workspace.shell, "_settings_ready", False):
        return
    from cdmw.models import default_config
    from cdmw.ui.shell.settings_autosave import SettingsAutosaveMixin

    load_texture_workflow_panel_settings(workspace, panel, default_config())
    section_name = {
        "asset_authoring": "asset_authoring_section",
        "dds_output": "dds_output_section",
        "filters": "filters_section",
        "settings": "settings_section",
        "chainner": "chainner_section",
    }[panel]
    workspace.shell.ui_localizer.apply(getattr(workspace, section_name).body_frame)
    if panel == "filters":
        workspace.shell.ui_localizer.apply(workspace.workflow_profiles_dialog)
    SettingsAutosaveMixin._connect_texture_workflow_panel_auto_save(workspace.shell, panel)


def load_asset_authoring_panel_settings(workspace, defaults) -> None:
    del defaults
    workspace.openimageio_source_path_edit.setText(
        str(workspace.shell.settings.value("asset_authoring/oiio_source_path", "") or "")
    )
    workspace.openimageio_output_path_edit.setText(
        str(workspace.shell.settings.value("asset_authoring/oiio_output_path", "") or "")
    )
    workspace.openimageio_compare_path_edit.setText(
        str(workspace.shell.settings.value("asset_authoring/oiio_compare_path", "") or "")
    )


def load_dds_output_panel_settings(workspace, defaults) -> None:
    size_mode_value = workspace.shell.settings.value("dds_output/size_mode")
    if size_mode_value is None:
        old_keep_original_size = workspace.shell._read_bool("settings/keep_original_size", False)
        size_mode_value = DDS_SIZE_MODE_ORIGINAL if old_keep_original_size else defaults.dds_size_mode
    workspace._set_combo_by_value(
        workspace.dds_format_mode_combo,
        str(workspace.shell.settings.value("dds_output/format_mode", defaults.dds_format_mode)),
    )
    workspace._set_combo_by_value(
        workspace.dds_custom_format_combo,
        str(workspace.shell.settings.value("dds_output/custom_format", defaults.dds_custom_format)),
    )
    workspace._set_combo_by_value(workspace.dds_size_mode_combo, str(size_mode_value))
    workspace.dds_custom_width_spin.setValue(int(workspace.shell.settings.value("dds_output/custom_width", defaults.dds_custom_width)))
    workspace.dds_custom_height_spin.setValue(int(workspace.shell.settings.value("dds_output/custom_height", defaults.dds_custom_height)))
    workspace._set_combo_by_value(
        workspace.dds_mip_mode_combo,
        str(workspace.shell.settings.value("dds_output/mip_mode", defaults.dds_mip_mode)),
    )
    workspace.dds_custom_mip_spin.setValue(
        int(workspace.shell.settings.value("dds_output/custom_mip_count", defaults.dds_custom_mip_count))
    )
    workspace.enable_dds_staging_checkbox.setChecked(
        workspace.shell._read_bool("settings/enable_dds_staging", defaults.enable_dds_staging)
    )


def load_workflow_settings_panel_settings(workspace, defaults) -> None:
    workspace.dry_run_checkbox.setChecked(workspace.shell._read_bool("settings/dry_run", defaults.dry_run))
    workspace.enable_incremental_resume_checkbox.setChecked(
        workspace.shell._read_bool("settings/enable_incremental_resume", defaults.enable_incremental_resume)
    )
    workspace.csv_log_enabled_checkbox.setChecked(workspace.shell._read_bool("settings/csv_log_enabled", defaults.csv_log_enabled))
    workspace.csv_log_path_edit.setText(workspace.shell.settings.value("settings/csv_log_path", defaults.csv_log_path))
    workspace.unique_basename_checkbox.setChecked(
        workspace.shell._read_bool("settings/allow_unique_basename_fallback", defaults.allow_unique_basename_fallback)
    )
    workspace.overwrite_existing_checkbox.setChecked(
        workspace.shell._read_bool("settings/overwrite_existing_dds", defaults.overwrite_existing_dds)
    )


def load_workflow_profiles_state(workspace, defaults) -> None:
    legacy_text = str(workspace.shell.settings.value("settings/texture_rules_text", getattr(defaults, "texture_rules_text", "")) or "")
    profiles_json = str(workspace.shell.settings.value("settings/workflow_profiles_json", "") or "")
    rules_json = str(workspace.shell.settings.value("settings/workflow_rules_json", "") or "")
    loaded_profiles: Sequence[object] = ()
    loaded_rules: Sequence[object] = ()
    try:
        parsed_profiles = json.loads(profiles_json) if profiles_json.strip() else []
        if isinstance(parsed_profiles, list):
            loaded_profiles = parsed_profiles
    except Exception:
        pass
    try:
        parsed_rules = json.loads(rules_json) if rules_json.strip() else []
        if isinstance(parsed_rules, list):
            loaded_rules = parsed_rules
    except Exception:
        pass
    workspace.texture_rules_legacy_text = legacy_text
    workspace.workflow_profiles_state = list(coerce_texture_workflow_profiles(loaded_profiles))
    workspace.texture_rules_state = list(coerce_texture_workflow_rules(loaded_rules))
    if not workspace.workflow_profiles_state and not workspace.texture_rules_state and legacy_text.strip():
        profiles, rules = migrate_legacy_texture_rules_to_structured(legacy_text)
        workspace.workflow_profiles_state = list(profiles)
        workspace.texture_rules_state = list(rules)
    elif should_seed_default_texture_workflow_state(workspace.workflow_profiles_state, workspace.texture_rules_state):
        workspace.workflow_profiles_state = list(build_default_texture_workflow_profiles())
        workspace.texture_rules_state = list(build_default_texture_workflow_rules())
    profiles, rules = upgrade_default_texture_workflow_state(workspace.workflow_profiles_state, workspace.texture_rules_state)
    workspace.workflow_profiles_state = list(profiles)
    workspace.texture_rules_state = list(rules)


def load_workflow_profiles_panel_settings(workspace, defaults) -> None:
    workspace.filters_edit.setPlainText(workspace.shell.settings.value("settings/include_filters", defaults.include_filters))


def _load_direct_upscale_panel_settings(workspace, defaults) -> None:
    saved_backend = str(workspace.shell.settings.value("upscale/backend", "") or "").strip()
    if saved_backend not in {
        UPSCALE_BACKEND_NONE,
        UPSCALE_BACKEND_CHAINNER,
        UPSCALE_BACKEND_REALESRGAN_NCNN,
    }:
        saved_backend = UPSCALE_BACKEND_CHAINNER if workspace.shell._read_bool("chainner/enabled", defaults.enable_chainner) else DEFAULT_UPSCALE_BACKEND
    workspace._set_combo_by_value(workspace.upscale_backend_combo, saved_backend)
    workspace.chainner_exe_path_edit.setText(
        workspace.shell.settings.value("chainner/exe_path", defaults.chainner_exe_path)
    )
    workspace.chainner_chain_path_edit.setText(
        workspace.shell.settings.value("chainner/chain_path", defaults.chainner_chain_path)
    )
    workspace.chainner_override_edit.setPlainText(
        workspace.shell.settings.value("chainner/override_json", defaults.chainner_override_json)
    )
    workspace.ncnn_exe_path_edit.setText(
        workspace.shell.settings.value("ncnn/exe_path", getattr(defaults, "ncnn_exe_path", REALESRGAN_NCNN_EXE_PATH))
    )
    workspace.ncnn_model_dir_edit.setText(
        workspace.shell.settings.value("ncnn/model_dir", getattr(defaults, "ncnn_model_dir", REALESRGAN_NCNN_MODEL_DIR))
    )
    workspace.ncnn_extra_args_edit.setText(
        str(workspace.shell.settings.value("ncnn/extra_args", getattr(defaults, "ncnn_extra_args", REALESRGAN_NCNN_EXTRA_ARGS)))
    )
    workspace.ncnn_scale_spin.setValue(
        int(workspace.shell.settings.value("ncnn/scale", getattr(defaults, "ncnn_scale", REALESRGAN_NCNN_SCALE)))
    )
    workspace.ncnn_tile_size_spin.setValue(
        int(workspace.shell.settings.value("ncnn/tile_size", getattr(defaults, "ncnn_tile_size", REALESRGAN_NCNN_TILE_SIZE)))
    )
    workspace._set_combo_by_value(
        workspace.upscale_post_correction_combo,
        str(
            workspace.shell.settings.value(
                "upscale/post_correction_mode",
                getattr(defaults, "upscale_post_correction_mode", DEFAULT_UPSCALE_POST_CORRECTION),
            )
        ),
    )
    workspace._set_combo_by_value(
        workspace.upscale_texture_preset_combo,
        str(
            workspace.shell.settings.value(
                "ncnn/texture_preset",
                getattr(defaults, "upscale_texture_preset", DEFAULT_UPSCALE_TEXTURE_PRESET),
            )
        ),
    )
    workspace._refresh_ncnn_model_picker(
        preferred_name=str(
            workspace.shell.settings.value(
                "ncnn/model_name",
                getattr(defaults, "ncnn_model_name", REALESRGAN_NCNN_MODEL_NAME),
            )
        )
    )
    workspace.enable_automatic_texture_rules_checkbox.setChecked(
        workspace.shell._read_bool(
            "upscale/automatic_texture_rules",
            getattr(defaults, "enable_automatic_texture_rules", ENABLE_AUTOMATIC_TEXTURE_RULES),
        )
    )
    workspace.enable_unsafe_technical_override_checkbox.setChecked(
        workspace.shell._read_bool(
            "upscale/unsafe_technical_override",
            getattr(defaults, "enable_unsafe_technical_override", ENABLE_UNSAFE_TECHNICAL_OVERRIDE),
        )
    )
    workspace.retry_smaller_tile_checkbox.setChecked(
        workspace.shell._read_bool(
            "upscale/retry_smaller_tile",
            getattr(defaults, "retry_smaller_tile_on_failure", RETRY_SMALLER_TILE_ON_FAILURE),
        )
    )
def _load_mod_ready_panel_settings(workspace, defaults) -> None:
    workspace.enable_mod_ready_loose_export_checkbox.setChecked(
        workspace.shell._read_bool(
            "upscale/mod_ready_loose_export",
            getattr(defaults, "enable_mod_ready_loose_export", ENABLE_MOD_READY_LOOSE_EXPORT),
        )
    )
    workspace.mod_ready_export_root_edit.setText(
        workspace.shell.settings.value(
            "upscale/mod_ready_export_root",
            getattr(defaults, "mod_ready_export_root", MOD_READY_EXPORT_ROOT),
        )
    )
    workspace.mod_ready_create_no_encrypt_checkbox.setChecked(
        workspace.shell._read_bool(
            "upscale/mod_ready_create_no_encrypt",
            getattr(defaults, "mod_ready_create_no_encrypt_file", MOD_READY_CREATE_NO_ENCRYPT),
        )
    )
    workspace.mod_ready_package_title_edit.setText(
        str(
            workspace.shell.settings.value(
                "upscale/mod_ready_package_title",
                getattr(defaults, "mod_ready_package_title", MOD_READY_PACKAGE_TITLE),
            )
        )
    )
    workspace.mod_ready_package_version_edit.setText(
        str(
            workspace.shell.settings.value(
                "upscale/mod_ready_package_version",
                getattr(defaults, "mod_ready_package_version", MOD_READY_PACKAGE_VERSION),
            )
        )
    )
    workspace.mod_ready_package_author_edit.setText(
        str(
            workspace.shell.settings.value(
                "upscale/mod_ready_package_author",
                getattr(defaults, "mod_ready_package_author", MOD_READY_PACKAGE_AUTHOR),
            )
        )
    )
    workspace.mod_ready_package_description_edit.setText(
        str(
            workspace.shell.settings.value(
                "upscale/mod_ready_package_description",
                getattr(defaults, "mod_ready_package_description", MOD_READY_PACKAGE_DESCRIPTION),
            )
        )
    )
    workspace.mod_ready_package_nexus_url_edit.setText(
        str(
            workspace.shell.settings.value(
                "upscale/mod_ready_package_nexus_url",
                getattr(defaults, "mod_ready_package_nexus_url", MOD_READY_PACKAGE_NEXUS_URL),
            )
        )
    )
    mod_ready_profile_value = str(
        workspace.shell.settings.value("upscale/mod_ready_manager_profile", getattr(defaults, "mod_ready_manager_profile", "dmm"))
    )
    mod_ready_profile_defaults = mod_package_export_options_for_manager(mod_ready_profile_value)
    workspace._set_combo_by_value(
        workspace.mod_ready_manager_combo,
        mod_ready_profile_value,
    )
    saved_profile_values: List[str] = []
    try:
        loaded_profiles = json.loads(str(workspace.shell.settings.value("upscale/mod_ready_manager_profiles", "[]") or "[]"))
        if isinstance(loaded_profiles, list):
            saved_profile_values = [
                str(value or "").strip()
                for value in loaded_profiles
                if str(value or "").strip() in MOD_PACKAGE_MANAGER_PROFILES
            ]
    except Exception:
        saved_profile_values = []
    if not saved_profile_values:
        saved_profile_values = [mod_ready_profile_value if mod_ready_profile_value in MOD_PACKAGE_MANAGER_PROFILES else "dmm"]
    for profile, checkbox in workspace.mod_ready_profile_checkboxes.items():
        checkbox.setChecked(profile in set(saved_profile_values))
    workspace._set_combo_by_value(
        workspace.mod_ready_structure_combo,
        str(
            workspace.shell.settings.value(
                "upscale/mod_ready_package_structure",
                getattr(defaults, "mod_ready_package_structure", workspace._combo_value(workspace.mod_ready_structure_combo)),
            )
        ),
    )
    workspace.mod_ready_manifest_checkbox.setChecked(
        workspace.shell._read_bool(
            "upscale/mod_ready_manifest_json",
            getattr(defaults, "mod_ready_create_manifest_json", mod_ready_profile_defaults.create_manifest_json),
        )
    )
    workspace.mod_ready_mod_json_checkbox.setChecked(
        workspace.shell._read_bool(
            "upscale/mod_ready_mod_json",
            getattr(defaults, "mod_ready_create_mod_json", mod_ready_profile_defaults.create_mod_json),
        )
    )
    workspace.mod_ready_modinfo_checkbox.setChecked(
        workspace.shell._read_bool(
            "upscale/mod_ready_modinfo_json",
            getattr(defaults, "mod_ready_create_modinfo_json", mod_ready_profile_defaults.create_modinfo_json),
        )
    )
    workspace.mod_ready_info_json_checkbox.setChecked(
        workspace.shell._read_bool(
            "upscale/mod_ready_info_json",
            getattr(defaults, "mod_ready_create_info_json", mod_ready_profile_defaults.create_info_json),
        )
    )
    if (
        mod_ready_profile_value.strip().lower() == "universal"
        and not workspace.shell.settings.contains("upscale/mod_ready_metadata_defaults_minimized")
        and workspace.shell.settings.contains("upscale/mod_ready_mod_json")
        and workspace.mod_ready_mod_json_checkbox.isChecked()
        and workspace.mod_ready_modinfo_checkbox.isChecked()
        and workspace.mod_ready_info_json_checkbox.isChecked()
    ):
        workspace.mod_ready_mod_json_checkbox.setChecked(False)
        workspace.mod_ready_modinfo_checkbox.setChecked(False)
        workspace.mod_ready_info_json_checkbox.setChecked(False)
        workspace.shell.settings.setValue("upscale/mod_ready_mod_json", False)
        workspace.shell.settings.setValue("upscale/mod_ready_modinfo_json", False)
        workspace.shell.settings.setValue("upscale/mod_ready_info_json", False)
    workspace.shell.settings.setValue("upscale/mod_ready_metadata_defaults_minimized", True)
    workspace.mod_ready_zip_checkbox.setChecked(
        workspace.shell._read_bool("upscale/mod_ready_zip", getattr(defaults, "mod_ready_create_zip", False))
    )
    workspace._set_combo_by_value(
        workspace.mod_ready_conflict_mode_combo,
        str(workspace.shell.settings.value("upscale/mod_ready_conflict_mode", getattr(defaults, "mod_ready_conflict_mode", ""))),
    )
    workspace.mod_ready_target_language_edit.setText(
        str(workspace.shell.settings.value("upscale/mod_ready_target_language", getattr(defaults, "mod_ready_target_language", "")))
    )


def load_upscale_panel_settings(workspace, defaults) -> None:
    _load_direct_upscale_panel_settings(workspace, defaults)
    _load_mod_ready_panel_settings(workspace, defaults)


def load_texture_workflow_panel_settings(workspace, panel: str, defaults) -> None:
    loaders = {
        "asset_authoring": load_asset_authoring_panel_settings,
        "dds_output": load_dds_output_panel_settings,
        "filters": load_workflow_profiles_panel_settings,
        "settings": load_workflow_settings_panel_settings,
        "chainner": load_upscale_panel_settings,
    }
    loader = loaders.get(panel)
    if loader is None:
        raise ValueError(f"Unknown Texture Workflow panel: {panel}")
    loader(workspace, defaults)
    if panel == "settings":
        workspace.shell._apply_csv_log_enabled_state()
    elif panel == "dds_output":
        workspace._apply_dds_staging_enabled_state()
        workspace._apply_dds_output_state()
    elif panel == "filters":
        if workspace.chainner_section.is_body_built():
            workspace._refresh_workflow_profile_ncnn_model_combo()
        workspace._refresh_workflow_profiles_tree()
        workspace._refresh_workflow_rules_tree()
        workspace._schedule_workflow_match_refresh()
    elif panel == "chainner":
        workspace._apply_mod_ready_export_state()
        workspace._refresh_chainner_chain_info()
        workspace._apply_upscale_backend_state()


def save_upscale_panel_settings(workspace) -> None:
    current_backend = workspace._current_upscale_backend()
    workspace.shell.settings.setValue("upscale/backend", current_backend)
    workspace.shell.settings.setValue("chainner/enabled", current_backend == UPSCALE_BACKEND_CHAINNER)
    workspace.shell.settings.setValue("chainner/exe_path", workspace.chainner_exe_path_edit.text())
    workspace.shell.settings.setValue("chainner/chain_path", workspace.chainner_chain_path_edit.text())
    workspace.shell.settings.setValue("chainner/override_json", workspace.chainner_override_edit.toPlainText())
    workspace.shell.settings.setValue("ncnn/exe_path", workspace.ncnn_exe_path_edit.text())
    workspace.shell.settings.setValue("ncnn/model_dir", workspace.ncnn_model_dir_edit.text())
    workspace.shell.settings.setValue("ncnn/model_name", workspace._combo_value(workspace.ncnn_model_combo))
    workspace.shell.settings.setValue("ncnn/scale", workspace.ncnn_scale_spin.value())
    workspace.shell.settings.setValue("ncnn/tile_size", workspace.ncnn_tile_size_spin.value())
    workspace.shell.settings.setValue("ncnn/extra_args", workspace.ncnn_extra_args_edit.text())
    workspace.shell.settings.setValue("upscale/post_correction_mode", workspace._combo_value(workspace.upscale_post_correction_combo))
    workspace.shell.settings.setValue("ncnn/texture_preset", workspace._combo_value(workspace.upscale_texture_preset_combo))
    workspace.shell.settings.setValue("upscale/automatic_texture_rules", workspace.enable_automatic_texture_rules_checkbox.isChecked())
    workspace.shell.settings.setValue("upscale/unsafe_technical_override", workspace.enable_unsafe_technical_override_checkbox.isChecked())
    workspace.shell.settings.setValue("upscale/retry_smaller_tile", workspace.retry_smaller_tile_checkbox.isChecked())
    workspace.shell.settings.setValue("upscale/mod_ready_loose_export", workspace.enable_mod_ready_loose_export_checkbox.isChecked())
    workspace.shell.settings.setValue("upscale/mod_ready_export_root", workspace.mod_ready_export_root_edit.text())
    workspace.shell.settings.setValue("upscale/mod_ready_create_no_encrypt", workspace.mod_ready_create_no_encrypt_checkbox.isChecked())
    workspace.shell.settings.setValue("upscale/mod_ready_package_title", workspace.mod_ready_package_title_edit.text())
    workspace.shell.settings.setValue("upscale/mod_ready_package_version", workspace.mod_ready_package_version_edit.text())
    workspace.shell.settings.setValue("upscale/mod_ready_package_author", workspace.mod_ready_package_author_edit.text())
    workspace.shell.settings.setValue("upscale/mod_ready_package_description", workspace.mod_ready_package_description_edit.text())
    workspace.shell.settings.setValue("upscale/mod_ready_package_nexus_url", workspace.mod_ready_package_nexus_url_edit.text())
    workspace.shell.settings.setValue("upscale/mod_ready_manager_profile", workspace._combo_value(workspace.mod_ready_manager_combo))
    workspace.shell.settings.setValue(
        "upscale/mod_ready_manager_profiles",
        json.dumps(
            [profile for profile, checkbox in workspace.mod_ready_profile_checkboxes.items() if checkbox.isChecked()],
            separators=(",", ":"),
        ),
    )
    workspace.shell.settings.setValue("upscale/mod_ready_package_structure", workspace._combo_value(workspace.mod_ready_structure_combo))
    workspace.shell.settings.setValue("upscale/mod_ready_manifest_json", workspace.mod_ready_manifest_checkbox.isChecked())
    workspace.shell.settings.setValue("upscale/mod_ready_mod_json", workspace.mod_ready_mod_json_checkbox.isChecked())
    workspace.shell.settings.setValue("upscale/mod_ready_modinfo_json", workspace.mod_ready_modinfo_checkbox.isChecked())
    workspace.shell.settings.setValue("upscale/mod_ready_info_json", workspace.mod_ready_info_json_checkbox.isChecked())
    workspace.shell.settings.setValue("upscale/mod_ready_zip", workspace.mod_ready_zip_checkbox.isChecked())
    workspace.shell.settings.setValue("upscale/mod_ready_conflict_mode", workspace._combo_value(workspace.mod_ready_conflict_mode_combo))
    workspace.shell.settings.setValue("upscale/mod_ready_target_language", workspace.mod_ready_target_language_edit.text())


__all__ = [
    "finish_texture_workflow_panel_body",
    "load_asset_authoring_panel_settings",
    "load_dds_output_panel_settings",
    "load_texture_workflow_panel_settings",
    "load_upscale_panel_settings",
    "load_workflow_profiles_panel_settings",
    "load_workflow_profiles_state",
    "load_workflow_settings_panel_settings",
    "save_upscale_panel_settings",
]
