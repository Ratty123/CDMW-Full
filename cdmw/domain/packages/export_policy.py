"""Immutable mod-package export options and manager-profile policy."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence


@dataclass(frozen=True, slots=True)
class ModPackageExportOptions:
    manager_targets: tuple[str, ...] = ("dmm",)
    export_profiles: tuple[str, ...] = ()
    output_profile_suffix: str = ""
    structure: str = "game_relative"
    create_manifest_json: bool = True
    create_mod_json: bool = False
    create_modinfo_json: bool = False
    create_info_json: bool = False
    create_no_encrypt_file: bool = True
    create_zip: bool = False
    create_texture_resolution_manifest: bool = False
    create_material_authority_report: bool = False
    create_active_file_authority_audit: bool = False
    conflict_mode: str = ""
    target_language: str = ""
    files_dir: str = "files"


@dataclass(frozen=True, slots=True)
class ModPackageMetadataArtifactInfo:
    key: str
    filename: str
    label: str
    description: str
    primary: bool = False


MOD_PACKAGE_STRUCTURES = frozenset(
    {"game_relative", "files_wrapper", "custom_compact_paths", "dmm_texture", "field_json_v31"}
)
MOD_PACKAGE_FILES_WRAPPER_STRUCTURES = frozenset({"files_wrapper", "custom_compact_paths"})
MOD_PACKAGE_MANAGER_PROFILES = ("dmm", "jmm", "cdumm", "crimson_sharp", "field_json")
MOD_PACKAGE_MANAGER_PROFILE_LABELS = {
    "dmm": "Definitive Mod Manager",
    "jmm": "JMM JSON",
    "cdumm": "CDUMM",
    "crimson_sharp": "Crimson Sharp",
    "field_json": "Field-JSON v3.1",
}

MOD_PACKAGE_METADATA_ARTIFACTS: tuple[ModPackageMetadataArtifactInfo, ...] = (
    ModPackageMetadataArtifactInfo(
        key="manifest_json",
        filename="manifest.json",
        label="manifest.json",
        description=(
            "Primary Crimson Desert Mod Workbench manifest. It records the package kind, metadata, "
            "selected layout, manager targets, files directory, and new_paths declarations."
        ),
        primary=True,
    ),
    ModPackageMetadataArtifactInfo(
        key="mod_json",
        filename="mod.json",
        label="mod.json",
        description="Compatibility metadata for mod managers that look for a mod.json descriptor.",
    ),
    ModPackageMetadataArtifactInfo(
        key="modinfo_json",
        filename="modinfo.json",
        label="modinfo.json",
        description=(
            "Compatibility metadata for managers such as CDUMM. It includes normal mod info and, "
            "when applicable, conflict mode and target language."
        ),
    ),
    ModPackageMetadataArtifactInfo(
        key="info_json",
        filename="info.json",
        label="info.json",
        description="Compatibility copy of the structured package metadata for managers that look for info.json.",
    ),
    ModPackageMetadataArtifactInfo(
        key="mod_field_json",
        filename="mod.field.json",
        label="mod.field.json",
        description="Field-JSON v3.1 asset manifest with DDS targets, vpaths, sizes, and SHA-256 hashes.",
    ),
    ModPackageMetadataArtifactInfo(
        key="no_encrypt",
        filename=".no_encrypt",
        label=".no_encrypt",
        description="Marker file used by some loose-file workflows to request non-encrypted handling.",
    ),
    ModPackageMetadataArtifactInfo(
        key="ready_zip",
        filename="Ready .zip",
        label="Ready .zip",
        description="Writes a zip beside the package folder containing the same generated package contents.",
    ),
)
MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY = {info.key: info for info in MOD_PACKAGE_METADATA_ARTIFACTS}
MOD_PACKAGE_METADATA_ARTIFACTS_BY_FILENAME = {
    info.filename: info for info in MOD_PACKAGE_METADATA_ARTIFACTS if info.filename != "Ready .zip"
}


def mod_package_profile_uses_manager_metadata(profile: str) -> bool:
    normalized = str(profile or "dmm").strip().lower()
    return normalized in {"cdumm", "ultimate", "ultimate_mods_manager"}


def normalize_mod_package_manager_profile(profile: str) -> str:
    normalized = str(profile or "dmm").strip().lower()
    aliases = {
        "field_json_v31": "field_json",
        "field-json": "field_json",
        "field_json_v3_1": "field_json",
        "json": "jmm",
        "jmm_json": "jmm",
        "crimson_browser": "crimson_sharp",
        "sharp": "crimson_sharp",
        "definitive": "dmm",
        "definitive_mod_manager": "dmm",
        "ultimate": "cdumm",
        "ultimate_mods_manager": "cdumm",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in MOD_PACKAGE_MANAGER_PROFILES else "dmm"


def normalize_mod_package_manager_targets(values: Sequence[str]) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_mod_package_manager_profile(str(value or ""))
        if not normalized or normalized in seen or normalized not in MOD_PACKAGE_MANAGER_PROFILES:
            continue
        seen.add(normalized)
        targets.append(normalized)
    return targets or ["dmm"]


def mod_package_export_options_for_manager(profile: str) -> ModPackageExportOptions:
    normalized = normalize_mod_package_manager_profile(profile)
    if normalized == "field_json":
        return ModPackageExportOptions(
            manager_targets=("field_json",),
            structure="field_json_v31",
            create_manifest_json=False,
            create_no_encrypt_file=False,
        )
    if normalized == "dmm":
        return ModPackageExportOptions(
            manager_targets=("dmm",),
            structure="dmm_texture",
            create_manifest_json=False,
            create_modinfo_json=True,
            create_no_encrypt_file=False,
        )
    if normalized == "jmm":
        return ModPackageExportOptions(
            manager_targets=("jmm",),
            create_manifest_json=False,
            create_no_encrypt_file=False,
        )
    if normalized == "cdumm":
        return ModPackageExportOptions(
            manager_targets=("cdumm",),
            structure="files_wrapper",
            create_modinfo_json=True,
        )
    if normalized == "crimson_sharp":
        return ModPackageExportOptions(
            manager_targets=("crimson_sharp",),
            structure="files_wrapper",
            create_mod_json=True,
        )
    return mod_package_export_options_for_manager("dmm")


def mod_package_export_options_for_profiles(
    profiles: Sequence[str],
    *,
    create_zip: bool = False,
    create_texture_resolution_manifest: bool = False,
    create_material_authority_report: bool = False,
    create_active_file_authority_audit: bool = False,
    conflict_mode: str = "",
    target_language: str = "",
) -> ModPackageExportOptions:
    selected_profiles: list[str] = []
    seen: set[str] = set()
    for value in tuple(profiles or ()):
        normalized = normalize_mod_package_manager_profile(str(value or ""))
        if normalized in seen:
            continue
        seen.add(normalized)
        selected_profiles.append(normalized)
    if not selected_profiles:
        selected_profiles.append("dmm")

    defaults = mod_package_export_options_for_manager(selected_profiles[0])
    uses_manager_metadata = any(mod_package_profile_uses_manager_metadata(profile) for profile in selected_profiles)
    return replace(
        defaults,
        export_profiles=tuple(selected_profiles) if len(selected_profiles) > 1 else (),
        create_zip=bool(create_zip),
        create_texture_resolution_manifest=bool(create_texture_resolution_manifest),
        create_material_authority_report=bool(create_material_authority_report),
        create_active_file_authority_audit=bool(create_active_file_authority_audit),
        conflict_mode=str(conflict_mode or "").strip() if uses_manager_metadata else "",
        target_language=str(target_language or "").strip() if uses_manager_metadata else "",
    )


def mod_package_expanded_export_options(
    options: ModPackageExportOptions,
    *,
    kind: str = "",
) -> tuple[tuple[str, ModPackageExportOptions], ...]:
    del kind
    selected_profiles: list[str] = []
    seen: set[str] = set()
    for value in tuple(options.export_profiles or ()):
        normalized = normalize_mod_package_manager_profile(value)
        if normalized in seen:
            continue
        seen.add(normalized)
        selected_profiles.append(normalized)
    if not selected_profiles:
        manager_targets = normalize_mod_package_manager_targets(options.manager_targets)
        selected_profiles = [manager_targets[0] if manager_targets else "dmm"]

    if len(selected_profiles) == 1:
        profile = selected_profiles[0]
        if tuple(options.export_profiles or ()):
            defaults = mod_package_export_options_for_manager(profile)
            return ((profile, replace(options, manager_targets=defaults.manager_targets, export_profiles=(), output_profile_suffix="")),)
        return ((profile, replace(options, export_profiles=())),)

    expanded: list[tuple[str, ModPackageExportOptions]] = []
    for profile in selected_profiles:
        defaults = mod_package_export_options_for_manager(profile)
        uses_manager_metadata = mod_package_profile_uses_manager_metadata(profile)
        expanded.append(
            (
                profile,
                replace(
                    defaults,
                    create_zip=bool(options.create_zip),
                    create_texture_resolution_manifest=bool(options.create_texture_resolution_manifest),
                    create_material_authority_report=bool(options.create_material_authority_report),
                    create_active_file_authority_audit=bool(options.create_active_file_authority_audit),
                    conflict_mode=str(options.conflict_mode or "").strip() if uses_manager_metadata else "",
                    target_language=str(options.target_language or "").strip() if uses_manager_metadata else "",
                    output_profile_suffix=profile,
                ),
            )
        )
    return tuple(expanded)


def effective_mod_package_export_options_for_kind(
    kind: str,
    options: ModPackageExportOptions,
) -> ModPackageExportOptions:
    normalized_kind = str(kind or "").strip().lower()
    manager_targets = tuple(normalize_mod_package_manager_targets(options.manager_targets))
    if "jmm" in set(manager_targets):
        return replace(
            options,
            manager_targets=manager_targets,
            structure="game_relative",
            create_manifest_json=False,
            create_mod_json=False,
            create_modinfo_json=False,
            create_info_json=False,
            create_no_encrypt_file=False,
        )
    if "dmm" in set(manager_targets) and normalized_kind == "dds_loose_mod":
        return replace(
            options,
            manager_targets=manager_targets,
            structure="dmm_texture",
            create_manifest_json=False,
            create_mod_json=False,
            create_modinfo_json=True,
            create_info_json=False,
            create_no_encrypt_file=False,
        )
    if "dmm" in set(manager_targets) and normalized_kind == "mesh_loose_mod":
        structure = "game_relative" if str(options.structure or "").strip().lower() == "dmm_texture" else options.structure
        return replace(
            options,
            manager_targets=manager_targets,
            structure=structure,
            create_manifest_json=True,
            create_mod_json=False,
            create_modinfo_json=True,
            create_info_json=False,
            create_no_encrypt_file=False,
        )
    if normalized_kind == "mesh_loose_mod" and str(options.structure or "").strip().lower() == "dmm_texture":
        return replace(options, manager_targets=manager_targets, structure="game_relative")
    return replace(options, manager_targets=manager_targets)


__all__ = [
    "MOD_PACKAGE_FILES_WRAPPER_STRUCTURES",
    "MOD_PACKAGE_MANAGER_PROFILE_LABELS",
    "MOD_PACKAGE_MANAGER_PROFILES",
    "MOD_PACKAGE_METADATA_ARTIFACTS",
    "MOD_PACKAGE_METADATA_ARTIFACTS_BY_FILENAME",
    "MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY",
    "MOD_PACKAGE_STRUCTURES",
    "ModPackageExportOptions",
    "ModPackageMetadataArtifactInfo",
    "effective_mod_package_export_options_for_kind",
    "mod_package_expanded_export_options",
    "mod_package_export_options_for_manager",
    "mod_package_export_options_for_profiles",
    "mod_package_profile_uses_manager_metadata",
    "normalize_mod_package_manager_profile",
    "normalize_mod_package_manager_targets",
]
