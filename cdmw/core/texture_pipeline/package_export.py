from __future__ import annotations

from pathlib import Path

from cdmw.core.mod_package import (
    ModPackageExportOptions,
    mod_package_export_options_for_manager,
    mod_package_export_options_for_profiles,
    mod_package_profile_uses_manager_metadata,
)
from cdmw.models import AppConfig
from cdmw.services.workspace_layout import default_mod_package_export_root

def resolve_default_mod_ready_export_root(output_root: Path) -> Path:
    return default_mod_package_export_root(output_root)


def build_mod_package_export_options_from_config(config: AppConfig) -> ModPackageExportOptions:
    profile = str(getattr(config, "mod_ready_manager_profile", "dmm") or "dmm").strip() or "dmm"
    raw_profiles = tuple(
        str(value or "").strip()
        for value in tuple(getattr(config, "mod_ready_manager_profiles", ()) or ())
        if str(value or "").strip()
    )
    selected_profiles = raw_profiles or (profile,)
    if raw_profiles:
        conflict_mode = str(getattr(config, "mod_ready_conflict_mode", "") or "").strip().lower()
        if conflict_mode not in {"", "override"}:
            conflict_mode = ""
        return mod_package_export_options_for_profiles(
            selected_profiles,
            create_zip=bool(getattr(config, "mod_ready_create_zip", False)),
            conflict_mode=conflict_mode,
            target_language=str(getattr(config, "mod_ready_target_language", "") or "").strip(),
        )
    defaults = mod_package_export_options_for_manager(profile)
    uses_manager_metadata = any(mod_package_profile_uses_manager_metadata(value) for value in selected_profiles)
    structure = str(getattr(config, "mod_ready_package_structure", "") or "").strip().lower()
    if structure not in {"game_relative", "files_wrapper", "custom_compact_paths", "dmm_texture", "field_json_v31"}:
        structure = defaults.structure
    conflict_mode = str(getattr(config, "mod_ready_conflict_mode", "") or "").strip().lower()
    if conflict_mode not in {"", "override"}:
        conflict_mode = ""
    if not uses_manager_metadata:
        conflict_mode = ""
        target_language = ""
    else:
        target_language = str(getattr(config, "mod_ready_target_language", "") or "").strip()
    return ModPackageExportOptions(
        manager_targets=defaults.manager_targets,
        export_profiles=selected_profiles,
        structure=structure,
        create_manifest_json=bool(getattr(config, "mod_ready_create_manifest_json", defaults.create_manifest_json)),
        create_mod_json=bool(getattr(config, "mod_ready_create_mod_json", defaults.create_mod_json)),
        create_modinfo_json=bool(getattr(config, "mod_ready_create_modinfo_json", defaults.create_modinfo_json)),
        create_info_json=bool(getattr(config, "mod_ready_create_info_json", defaults.create_info_json)),
        create_no_encrypt_file=bool(getattr(config, "mod_ready_create_no_encrypt_file", defaults.create_no_encrypt_file)),
        create_zip=bool(getattr(config, "mod_ready_create_zip", defaults.create_zip)),
        conflict_mode=conflict_mode,
        target_language=target_language,
        files_dir=defaults.files_dir,
    )
