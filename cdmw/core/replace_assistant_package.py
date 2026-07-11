from __future__ import annotations

from pathlib import Path
from typing import Callable

from cdmw.core.archive_extraction import clear_directory_contents
from cdmw.core.mod_package import write_mod_package_manifest
from cdmw.core.upscale_profiles import copy_mod_ready_loose_tree
from cdmw.domain.packages.export_policy import (
    MOD_PACKAGE_FILES_WRAPPER_STRUCTURES,
    ModPackageExportOptions,
    effective_mod_package_export_options_for_kind,
    mod_package_expanded_export_options,
)
from cdmw.domain.packages.layout import resolve_mod_package_profile_root, safe_mod_package_files_dir
from cdmw.models import ModPackageInfo


def publish_replace_assistant_packages(
    stage_root: Path,
    *,
    output_parent: Path,
    package_info: ModPackageInfo,
    export_options: ModPackageExportOptions | None,
    create_no_encrypt_file: bool,
    overwrite: bool,
    file_count: int,
    on_log: Callable[[str], None] | None = None,
) -> tuple[tuple[Path, Path], ...]:
    base_options = export_options or ModPackageExportOptions(create_no_encrypt_file=create_no_encrypt_file)
    published: list[tuple[Path, Path]] = []
    for profile, profile_options in mod_package_expanded_export_options(base_options, kind="dds_loose_mod"):
        active_options = effective_mod_package_export_options_for_kind("dds_loose_mod", profile_options)
        profile_suffix = active_options.output_profile_suffix or profile
        package_root = resolve_mod_package_profile_root(
            output_parent,
            package_info,
            profile_suffix,
            multi_profile=bool(active_options.output_profile_suffix),
        )
        if overwrite and package_root.exists():
            clear_directory_contents(package_root)
        package_root.mkdir(parents=True, exist_ok=True)
        copy_mod_ready_loose_tree(stage_root, package_root, overwrite=overwrite, dry_run=False, on_log=None)
        write_mod_package_manifest(
            package_root,
            package_info,
            kind="dds_loose_mod",
            extra_fields={"file_count": file_count},
            create_no_encrypt_file=create_no_encrypt_file,
            export_options=active_options,
        )
        structure = active_options.structure.strip().lower()
        if structure in MOD_PACKAGE_FILES_WRAPPER_STRUCTURES:
            payload_root = package_root / safe_mod_package_files_dir(active_options.files_dir)
        elif structure == "field_json_v31":
            payload_root = package_root / "assets"
        else:
            payload_root = package_root
        published.append((package_root, payload_root))
        if on_log is not None:
            on_log(f"Replace package written to: {package_root}")
    return tuple(published)
