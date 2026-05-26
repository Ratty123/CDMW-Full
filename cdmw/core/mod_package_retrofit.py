from __future__ import annotations

import dataclasses
import json
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

from cdmw.core.mod_package import (
    MOD_PACKAGE_MANAGER_PROFILES,
    MeshLooseModAsset,
    MeshLooseModFile,
    ModPackageExportOptions,
    mod_package_export_options_for_manager,
    normalize_mod_package_manager_profile,
    normalize_mod_package_payload_path,
    sanitize_mod_package_folder_name,
    write_jmm_mod_json,
    write_mesh_loose_mod_package_metadata,
    write_mod_package_manifest,
)
from cdmw.models import ModPackageInfo


KNOWN_RETROFIT_CONTENT_ROOTS = frozenset(
    {
        "character",
        "effect",
        "gamedata",
        "leveldata",
        "meta",
        "object",
        "tree",
        "ui",
        "vehicle",
        "world",
    }
)
RETROFIT_MANAGER_PROFILES = MOD_PACKAGE_MANAGER_PROFILES
_IGNORED_ROOT_FILENAMES = {
    ".no_encrypt",
    "info.json",
    "manifest.json",
    "mod.field.json",
    "mod.json",
    "modinfo.json",
    "readme.txt",
}
_IGNORED_SUFFIXES = {".zip", ".7z", ".rar", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_MESH_SUFFIXES = {".pac", ".pam", ".pamlod", ".pac_xml", ".pam_xml", ".pamlod_xml", ".pami"}


@dataclasses.dataclass(frozen=True, slots=True)
class RetrofittableModPackage:
    root: Path
    name: str
    kind: str
    package_info: ModPackageInfo
    payload_paths: tuple[str, ...]
    existing_metadata: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    manifest: Mapping[str, object] = dataclasses.field(default_factory=dict)
    modinfo: Mapping[str, object] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True, slots=True)
class ModPackageRetrofitResult:
    source_root: Path
    output_root: Path
    package_root: Path
    zip_path: Path
    manager_profile: str
    metadata_files: tuple[Path, ...]
    payload_paths: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    repaired_path_count: int = 0
    unresolved_path_count: int = 0
    ambiguous_path_count: int = 0


@dataclasses.dataclass(frozen=True, slots=True)
class RetrofitPayloadMapping:
    source_path: str
    target_path: str
    package_group: str = ""
    is_new: bool = False
    status: str = "unchanged"
    message: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class RetrofitPathRepairSummary:
    mappings: tuple[RetrofitPayloadMapping, ...]
    repaired_path_count: int = 0
    unresolved_path_count: int = 0
    ambiguous_path_count: int = 0
    warnings: tuple[str, ...] = ()


def scan_retrofittable_mod_packages(source: Path | str) -> list[RetrofittableModPackage]:
    source_path = Path(source).expanduser()
    if source_path.is_file() and source_path.suffix.lower() == ".zip":
        package = analyze_retrofittable_mod_package(source_path)
        return [package] if package is not None else []
    if not source_path.is_dir():
        return []
    own_package = analyze_retrofittable_mod_package(source_path)
    if own_package is not None:
        return [own_package]

    packages: list[RetrofittableModPackage] = []
    for child in sorted(source_path.iterdir(), key=lambda item: item.name.casefold()):
        if child.is_dir() and child.name.casefold() == "converted":
            continue
        if not child.is_dir() and child.suffix.lower() != ".zip":
            continue
        package = analyze_retrofittable_mod_package(child)
        if package is not None:
            packages.append(package)
    return packages


def analyze_retrofittable_mod_package(root: Path | str) -> RetrofittableModPackage | None:
    package_root = Path(root).expanduser()
    if package_root.is_file() and package_root.suffix.lower() == ".zip":
        return _analyze_retrofittable_zip_package(package_root)
    if not package_root.is_dir():
        return None

    manifest = _read_json_file(package_root / "manifest.json")
    modinfo = _read_json_file(package_root / "modinfo.json")
    payload_paths = _discover_retrofit_payload_paths(package_root)
    if not payload_paths and not manifest and not modinfo:
        return None

    existing_metadata = tuple(
        name
        for name in ("manifest.json", "modinfo.json", "mod.json", "info.json", "mod.field.json", ".no_encrypt")
        if (package_root / name).exists()
    )
    warnings: list[str] = []
    if not payload_paths:
        warnings.append("No game-content payload files were detected.")

    kind = _detect_package_kind(manifest, payload_paths)
    package_info = _package_info_from_metadata(package_root, manifest, modinfo)
    return RetrofittableModPackage(
        root=package_root,
        name=package_root.name,
        kind=kind,
        package_info=package_info,
        payload_paths=tuple(payload_paths),
        existing_metadata=existing_metadata,
        warnings=tuple(warnings),
        manifest=manifest,
        modinfo=modinfo,
    )


def retrofit_mod_package(
    package: RetrofittableModPackage,
    output_parent: Path | str,
    *,
    manager_profile: str,
    export_options: ModPackageExportOptions | None = None,
    archive_entries_by_basename: Mapping[str, Sequence[object]] | None = None,
) -> ModPackageRetrofitResult:
    normalized_profile = _normalize_retrofit_manager_profile(manager_profile)
    output_root = Path(output_parent).expanduser()
    package_root = output_root / f"{package.name}_{normalized_profile}"
    warnings: list[str] = list(package.warnings)
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True, exist_ok=True)

    repair_summary = build_retrofit_path_repair_summary(
        package,
        archive_entries_by_basename=archive_entries_by_basename,
    )
    warnings.extend(repair_summary.warnings)
    copied_payload_paths = _copy_payloads(package.root, package_root, repair_summary.mappings, warnings)
    new_file_paths = [mapping.target_path for mapping in repair_summary.mappings if mapping.is_new]
    source_to_target = {mapping.source_path.casefold(): mapping.target_path for mapping in repair_summary.mappings}
    if normalized_profile == "jmm":
        mod_json_path = _write_jmm_mod_json(package_root, package, copied_payload_paths, new_file_paths)
        zip_path = _write_retrofit_package_zip(package_root)
        return ModPackageRetrofitResult(
            source_root=package.root,
            output_root=output_root,
            package_root=package_root,
            zip_path=zip_path,
            manager_profile=normalized_profile,
            metadata_files=(mod_json_path,),
            payload_paths=tuple(copied_payload_paths),
            warnings=tuple(warnings),
            repaired_path_count=repair_summary.repaired_path_count,
            unresolved_path_count=repair_summary.unresolved_path_count,
            ambiguous_path_count=repair_summary.ambiguous_path_count,
        )

    export_options = _retrofit_export_options(normalized_profile, package.kind, copied_payload_paths, export_options)

    if _should_preserve_mesh_manifest(package, copied_payload_paths):
        metadata_files = write_mesh_loose_mod_package_metadata(
            package_root,
            package.package_info,
            assets=_mesh_assets_from_manifest(package.manifest, source_to_target),
            files=_mesh_files_from_manifest(package.manifest, copied_payload_paths, source_to_target),
            include_paired_lod=bool(package.manifest.get("include_paired_lod", False)),
            export_options=export_options,
            create_no_encrypt_file=export_options.create_no_encrypt_file,
            game_build=str(package.manifest.get("game_build", "") or ""),
            game_metadata=package.manifest.get("game_metadata") if isinstance(package.manifest.get("game_metadata"), Mapping) else None,
        )
    else:
        returned_path = write_mod_package_manifest(
            package_root,
            package.package_info,
            kind=package.kind,
            extra_fields=_retrofit_extra_fields(package.manifest),
            new_file_paths=new_file_paths,
            all_payload_paths=copied_payload_paths,
            export_options=export_options,
            create_no_encrypt_file=export_options.create_no_encrypt_file,
        )
        metadata_files = [returned_path]
        for metadata_name in ("README.txt", ".no_encrypt", "manifest.json", "mod.json", "modinfo.json", "info.json", "mod.field.json"):
            metadata_path = package_root / metadata_name
            if metadata_path.exists() and metadata_path not in metadata_files:
                metadata_files.append(metadata_path)

    zip_path = package_root.with_suffix(".zip")
    if not zip_path.is_file():
        warnings.append("Converted zip was not created.")

    return ModPackageRetrofitResult(
        source_root=package.root,
        output_root=output_root,
        package_root=package_root,
        zip_path=zip_path,
        manager_profile=normalized_profile,
        metadata_files=tuple(metadata_files),
        payload_paths=tuple(copied_payload_paths),
        warnings=tuple(warnings),
        repaired_path_count=repair_summary.repaired_path_count,
        unresolved_path_count=repair_summary.unresolved_path_count,
        ambiguous_path_count=repair_summary.ambiguous_path_count,
    )


def merge_retrofittable_mod_packages(
    packages: Sequence[RetrofittableModPackage],
    output_parent: Path | str,
    *,
    package_info: ModPackageInfo,
    export_options: ModPackageExportOptions | None = None,
    archive_entries_by_basename: Mapping[str, Sequence[object]] | None = None,
) -> ModPackageRetrofitResult:
    selected_packages = tuple(packages)
    if len(selected_packages) < 2:
        raise ValueError("Select at least two packages to merge.")

    base_options = export_options or mod_package_export_options_for_manager("cdumm")
    target_set = {
        normalize_mod_package_manager_profile(target)
        for target in tuple(base_options.manager_targets or ())
        if str(target or "").strip()
    }
    if target_set != {"cdumm"}:
        raise ValueError("CDUMM merge only supports the CDUMM manager target.")

    output_root = Path(output_parent).expanduser()
    package_title = (package_info.title or "").strip() or "Merged CDUMM Mod"
    package_root = output_root / f"{sanitize_mod_package_folder_name(package_title)}_cdumm_merged"
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True, exist_ok=True)

    resolved_options = dataclasses.replace(
        base_options,
        manager_targets=("cdumm",),
        export_profiles=(),
        output_profile_suffix="",
        structure="files_wrapper",
        create_manifest_json=True,
        create_mod_json=False,
        create_modinfo_json=True,
        create_info_json=False,
    )

    warnings: list[str] = []
    repair_summaries: dict[Path, RetrofitPathRepairSummary] = {}
    source_to_target_by_package: dict[Path, dict[str, str]] = {}
    target_owner: dict[str, tuple[str, str]] = {}
    duplicate_messages: list[str] = []
    repaired_count = 0
    unresolved_count = 0
    ambiguous_count = 0

    for package in selected_packages:
        warnings.extend(package.warnings)
        repair_summary = build_retrofit_path_repair_summary(
            package,
            archive_entries_by_basename=archive_entries_by_basename,
        )
        repair_summaries[package.root] = repair_summary
        warnings.extend(repair_summary.warnings)
        repaired_count += repair_summary.repaired_path_count
        unresolved_count += repair_summary.unresolved_path_count
        ambiguous_count += repair_summary.ambiguous_path_count
        source_to_target: dict[str, str] = {}
        for mapping in repair_summary.mappings:
            target_path = normalize_mod_package_payload_path(mapping.target_path).as_posix().strip("/")
            source_path = normalize_mod_package_payload_path(mapping.source_path).as_posix().strip("/")
            if not source_path or not target_path:
                continue
            source_to_target[source_path.casefold()] = target_path
            key = target_path.casefold()
            owner = target_owner.get(key)
            if owner is not None:
                owner_name, owner_path = owner
                duplicate_messages.append(
                    f"{target_path} from {package.name} conflicts with {owner_path} from {owner_name}"
                )
                continue
            target_owner[key] = (package.name, target_path)
        source_to_target_by_package[package.root] = source_to_target

    if duplicate_messages:
        shutil.rmtree(package_root, ignore_errors=True)
        preview = "; ".join(duplicate_messages[:6])
        if len(duplicate_messages) > 6:
            preview += f"; +{len(duplicate_messages) - 6} more"
        raise ValueError(f"Cannot merge packages with duplicate payload paths: {preview}")

    copied_payload_paths: list[str] = []
    assets: list[MeshLooseModAsset] = []
    files: list[MeshLooseModFile] = []
    seen_copied: set[str] = set()
    seen_files: set[str] = set()
    seen_assets: set[str] = set()

    for package in selected_packages:
        repair_summary = repair_summaries[package.root]
        copied_for_package = _copy_payloads(package.root, package_root, repair_summary.mappings, warnings)
        for path in copied_for_package:
            key = path.casefold()
            if key not in seen_copied:
                seen_copied.add(key)
                copied_payload_paths.append(path)

        source_to_target = source_to_target_by_package[package.root]
        for asset in _mesh_assets_from_manifest(package.manifest, source_to_target):
            key = asset.entry_path.casefold()
            if not key or key in seen_assets:
                continue
            seen_assets.add(key)
            assets.append(asset)

        manifest_files = list(_mesh_files_from_manifest(package.manifest, copied_for_package, source_to_target))
        mapping_by_target = {
            normalize_mod_package_payload_path(mapping.target_path).as_posix().strip("/").casefold(): mapping
            for mapping in repair_summary.mappings
            if normalize_mod_package_payload_path(mapping.target_path).as_posix().strip("/")
        }
        for file_info in manifest_files:
            key = file_info.path.casefold()
            if not key or key in seen_files:
                continue
            seen_files.add(key)
            files.append(file_info)
        for copied_path in copied_for_package:
            key = copied_path.casefold()
            if key in seen_files:
                continue
            mapping = mapping_by_target.get(key)
            seen_files.add(key)
            files.append(
                MeshLooseModFile(
                    path=copied_path,
                    package_group=mapping.package_group if mapping is not None else "",
                    format=PurePosixPath(copied_path).suffix.lstrip("."),
                    is_new=bool(mapping.is_new) if mapping is not None else False,
                )
            )

    for copied_path in copied_payload_paths:
        suffix = PurePosixPath(copied_path).suffix.casefold()
        if suffix not in {".pac", ".pam", ".pamlod", ".pami"}:
            continue
        key = copied_path.casefold()
        if key in seen_assets:
            continue
        seen_assets.add(key)
        files_by_path = {file_info.path.casefold(): file_info for file_info in files}
        file_info = files_by_path.get(key)
        assets.append(
            MeshLooseModAsset(
                entry_path=copied_path,
                package_group=file_info.package_group if file_info is not None else "",
                format=PurePosixPath(copied_path).suffix.lstrip("."),
            )
        )

    game_build = _first_manifest_text(selected_packages, "game_build")
    game_metadata = _first_manifest_mapping(selected_packages, "game_metadata")
    include_paired_lod = any(bool(package.manifest.get("include_paired_lod", False)) for package in selected_packages)

    metadata_files = write_mesh_loose_mod_package_metadata(
        package_root,
        package_info,
        assets=tuple(assets),
        files=tuple(files),
        include_paired_lod=include_paired_lod,
        export_options=resolved_options,
        create_no_encrypt_file=resolved_options.create_no_encrypt_file,
        game_build=game_build,
        game_metadata=game_metadata,
    )
    _append_cdumm_merge_readme_note(package_root / "README.txt", selected_packages)
    zip_path = package_root.with_suffix(".zip")
    if resolved_options.create_zip:
        zip_path = _write_retrofit_package_zip(package_root)

    return ModPackageRetrofitResult(
        source_root=_merged_source_root(selected_packages),
        output_root=output_root,
        package_root=package_root,
        zip_path=zip_path,
        manager_profile="cdumm",
        metadata_files=tuple(metadata_files),
        payload_paths=tuple(copied_payload_paths),
        warnings=tuple(dict.fromkeys(warnings)),
        repaired_path_count=repaired_count,
        unresolved_path_count=unresolved_count,
        ambiguous_path_count=ambiguous_count,
    )


def _read_json_file(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _analyze_retrofittable_zip_package(package_path: Path) -> RetrofittableModPackage | None:
    try:
        with zipfile.ZipFile(package_path) as archive:
            member_names = [info.filename.replace("\\", "/") for info in archive.infolist() if not info.is_dir()]
            json_members = {
                PurePosixPath(name).name.lower(): name
                for name in member_names
                if PurePosixPath(name).name.lower() in {"manifest.json", "modinfo.json", "mod.json", "info.json", "mod.field.json"}
            }
            manifest = _read_zip_json_member(archive, json_members.get("manifest.json", ""))
            modinfo = _read_zip_json_member(archive, json_members.get("modinfo.json", ""))
            mod_json = _read_zip_json_member(archive, json_members.get("mod.json", ""))
            payload_paths = _discover_retrofit_zip_payload_paths(member_names, mod_json)
    except (OSError, zipfile.BadZipFile):
        return None

    metadata_source = manifest or mod_json
    if not payload_paths and not metadata_source and not modinfo:
        return None
    existing_metadata = tuple(
        name for name in ("manifest.json", "modinfo.json", "mod.json", "info.json", "mod.field.json") if name in json_members
    )
    warnings: list[str] = []
    if not payload_paths:
        warnings.append("No game-content payload files were detected.")
    kind = _detect_package_kind(metadata_source, payload_paths)
    package_info = _package_info_from_metadata(package_path, metadata_source, modinfo)
    return RetrofittableModPackage(
        root=package_path,
        name=package_path.stem,
        kind=kind,
        package_info=package_info,
        payload_paths=tuple(payload_paths),
        existing_metadata=existing_metadata,
        warnings=tuple(warnings),
        manifest=metadata_source,
        modinfo=modinfo,
    )


def _read_zip_json_member(archive: zipfile.ZipFile, member_name: str) -> dict[str, object]:
    if not member_name:
        return {}
    try:
        payload = json.loads(archive.read(member_name).decode("utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _discover_retrofit_zip_payload_paths(member_names: Sequence[str], mod_json: Mapping[str, object]) -> list[str]:
    manifest_files = mod_json.get("files")
    if isinstance(manifest_files, Sequence) and not isinstance(manifest_files, (str, bytes, bytearray)):
        paths = [_payload_path_from_any_member(str(value or "")) for value in manifest_files]
    else:
        paths = [_payload_path_from_any_member(name) for name in member_names if not _is_ignored_retrofit_file(Path(name))]
    result: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path:
            continue
        key = path.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _discover_retrofit_payload_paths(root: Path) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _is_ignored_retrofit_file(relative):
            continue
        relative_parts = relative.parts
        if not relative_parts:
            continue
        first_part = relative_parts[0].casefold()
        if first_part == "files":
            if len(relative_parts) < 3 or relative_parts[1].casefold() not in KNOWN_RETROFIT_CONTENT_ROOTS:
                continue
        elif first_part not in KNOWN_RETROFIT_CONTENT_ROOTS:
            continue
        normalized = normalize_mod_package_payload_path(relative).as_posix().strip("/")
        if not normalized:
            continue
        parts = PurePosixPath(normalized).parts
        if not parts or parts[0].lower() not in KNOWN_RETROFIT_CONTENT_ROOTS:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        paths.append(normalized)
    return paths


def _payload_path_from_any_member(path_value: str | Path) -> str:
    normalized = normalize_mod_package_payload_path(path_value).as_posix().strip("/")
    parts = PurePosixPath(normalized).parts if normalized else ()
    if not parts or parts[0].lower() not in KNOWN_RETROFIT_CONTENT_ROOTS:
        return ""
    return normalized


def _is_ignored_retrofit_file(relative: Path) -> bool:
    parts = relative.parts
    if not parts:
        return True
    name = relative.name
    lowered_name = name.casefold()
    if len(parts) == 1 and lowered_name in _IGNORED_ROOT_FILENAMES:
        return True
    if Path(name).suffix.casefold() in _IGNORED_SUFFIXES:
        return True
    if any(part.startswith(".") for part in parts):
        return True
    return False


def _detect_package_kind(manifest: Mapping[str, object], payload_paths: Sequence[str]) -> str:
    manifest_kind = str(manifest.get("kind", "") or "").strip()
    if manifest_kind and manifest_kind != "file_replacement":
        return manifest_kind
    suffixes = {PurePosixPath(path).suffix.lower() for path in payload_paths}
    if suffixes and suffixes <= {".dds"}:
        return "dds_loose_mod"
    if suffixes & _MESH_SUFFIXES:
        return "mesh_loose_mod"
    return "loose_mod"


def _package_info_from_metadata(
    root: Path,
    manifest: Mapping[str, object],
    modinfo: Mapping[str, object],
) -> ModPackageInfo:
    title = _metadata_text(manifest, "title") or _metadata_text(manifest, "name") or _metadata_text(modinfo, "name") or root.name
    return ModPackageInfo(
        title=title,
        version=_metadata_text(manifest, "version") or _metadata_text(modinfo, "version") or "1.0",
        author=_metadata_text(manifest, "author") or _metadata_text(modinfo, "author"),
        description=_metadata_text(manifest, "description") or _metadata_text(modinfo, "description"),
        nexus_url=_metadata_text(manifest, "nexus_url"),
    )


def _metadata_text(metadata: Mapping[str, object], key: str) -> str:
    value = metadata.get(key)
    return str(value or "").strip() if value is not None else ""


def _first_manifest_text(packages: Sequence[RetrofittableModPackage], key: str) -> str:
    for package in packages:
        value = _metadata_text(package.manifest, key)
        if value:
            return value
    return ""


def _first_manifest_mapping(packages: Sequence[RetrofittableModPackage], key: str) -> Mapping[str, object] | None:
    for package in packages:
        value = package.manifest.get(key)
        if isinstance(value, Mapping) and value:
            return value
    return None


def _merged_source_root(packages: Sequence[RetrofittableModPackage]) -> Path:
    roots = [package.root for package in packages]
    if not roots:
        return Path()
    parents = [root.parent for root in roots]
    try:
        return Path(os.path.commonpath([str(parent) for parent in parents]))
    except Exception:
        return parents[0]


def _append_cdumm_merge_readme_note(readme_path: Path, packages: Sequence[RetrofittableModPackage]) -> None:
    if not readme_path.is_file():
        return
    package_names = ", ".join(package.package_info.title or package.name for package in packages)
    note = (
        "\nMERGED CDUMM PACKAGE\n"
        "=========================================================\n"
        "  This package combines the selected source mods into one CDUMM import.\n"
        "  Import this merged package instead of enabling the source mods separately;\n"
        "  separate imports can conflict when CDUMM builds meta/0.pathc.\n"
        f"  Source mods: {package_names}\n"
    )
    existing = readme_path.read_text(encoding="utf-8")
    readme_path.write_text(existing.rstrip() + "\n" + note, encoding="utf-8")


def _normalize_retrofit_manager_profile(profile: str) -> str:
    normalized = normalize_mod_package_manager_profile(profile)
    return normalized if normalized in RETROFIT_MANAGER_PROFILES else "universal"


def build_retrofit_path_repair_summary(
    package: RetrofittableModPackage,
    *,
    archive_entries_by_basename: Mapping[str, Sequence[object]] | None = None,
) -> RetrofitPathRepairSummary:
    warnings: list[str] = []
    manifest_rows = _manifest_file_rows_by_path(package.manifest)
    manifest_new_paths = _manifest_new_paths(package.manifest)
    mappings: list[RetrofitPayloadMapping] = []
    repaired = 0
    unresolved = 0
    ambiguous = 0
    for payload_path in package.payload_paths:
        source_path = normalize_mod_package_payload_path(payload_path).as_posix().strip("/")
        if not source_path:
            continue
        row = manifest_rows.get(source_path.casefold(), {})
        package_group = _metadata_text(row, "package_group") if isinstance(row, Mapping) else ""
        is_new = bool(row.get("is_new", False)) if isinstance(row, Mapping) else False
        if source_path.casefold() in manifest_new_paths:
            is_new = True
        target_path, status, message = _repair_retrofit_payload_path(
            source_path,
            package_group=package_group,
            archive_entries_by_basename=archive_entries_by_basename,
        )
        if status == "repaired":
            repaired += 1
        elif status == "unresolved":
            unresolved += 1
            warnings.append(message)
        elif status == "ambiguous":
            ambiguous += 1
            warnings.append(message)
        mappings.append(
            RetrofitPayloadMapping(
                source_path=source_path,
                target_path=target_path,
                package_group=package_group,
                is_new=is_new,
                status=status,
                message=message,
            )
        )
    return RetrofitPathRepairSummary(
        mappings=tuple(mappings),
        repaired_path_count=repaired,
        unresolved_path_count=unresolved,
        ambiguous_path_count=ambiguous,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _manifest_file_rows_by_path(manifest: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for rows_name, path_key in (("assets", "entry_path"), ("files", "path")):
        rows = manifest.get(rows_name)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
            continue
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            path = normalize_mod_package_payload_path(_metadata_text(item, path_key)).as_posix().strip("/")
            if path:
                result.setdefault(path.casefold(), item)
    return result


def _manifest_new_paths(manifest: Mapping[str, object]) -> set[str]:
    value = manifest.get("new_paths")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return set()
    return {
        normalized.casefold()
        for normalized in (normalize_mod_package_payload_path(str(item or "")).as_posix().strip("/") for item in value)
        if normalized
    }


def _compact_mesh_path_needs_repair(path: str) -> bool:
    pure = PurePosixPath(path)
    parts = tuple(part for part in pure.parts if part)
    if len(parts) != 2 or parts[0].casefold() != "character":
        return False
    return pure.suffix.casefold() in _MESH_SUFFIXES


def _repair_retrofit_payload_path(
    path: str,
    *,
    package_group: str,
    archive_entries_by_basename: Mapping[str, Sequence[object]] | None,
) -> tuple[str, str, str]:
    normalized = normalize_mod_package_payload_path(path).as_posix().strip("/")
    if not normalized or not _compact_mesh_path_needs_repair(normalized):
        return normalized, "unchanged", ""
    if not archive_entries_by_basename:
        return (
            normalized,
            "unresolved",
            f"Could not repair compact path without loaded archive index: {normalized}",
        )
    basename = PurePosixPath(normalized).name.casefold()
    candidates = list(archive_entries_by_basename.get(basename, ()) or ())
    if not candidates:
        for key, values in archive_entries_by_basename.items():
            if str(key or "").casefold() == basename:
                candidates.extend(values or ())
        deduped_candidates: list[object] = []
        seen_candidate_keys: set[str] = set()
        for candidate in candidates:
            candidate_key = str(getattr(candidate, "path", "") or "").replace("\\", "/").casefold()
            if candidate_key in seen_candidate_keys:
                continue
            seen_candidate_keys.add(candidate_key)
            deduped_candidates.append(candidate)
        candidates = deduped_candidates
    suffix = PurePosixPath(normalized).suffix.casefold()
    candidates = [
        candidate
        for candidate in candidates
        if str(getattr(candidate, "path", "") or "").replace("\\", "/").casefold().endswith(suffix)
    ]
    normalized_group = str(package_group or "").strip().casefold()
    if normalized_group:
        group_matches = [
            candidate
            for candidate in candidates
            if str(getattr(getattr(candidate, "pamt_path", Path()), "parent", Path()).name or "").strip().casefold()
            == normalized_group
        ]
        if group_matches:
            candidates = group_matches
    unique_paths = sorted(
        {
            str(getattr(candidate, "path", "") or "").replace("\\", "/").strip()
            for candidate in candidates
            if str(getattr(candidate, "path", "") or "").strip()
        },
        key=str.casefold,
    )
    if len(unique_paths) == 1:
        repaired = normalize_mod_package_payload_path(unique_paths[0]).as_posix().strip("/")
        if repaired and repaired.casefold() != normalized.casefold():
            return repaired, "repaired", f"Repaired compact path {normalized} -> {repaired}"
        return normalized, "unchanged", ""
    if not unique_paths:
        group_note = f" in package group {package_group}" if package_group else ""
        return normalized, "unresolved", f"Could not repair compact path{group_note}: {normalized}"
    return (
        normalized,
        "ambiguous",
        f"Compact path {normalized} matched multiple archive paths: {', '.join(unique_paths[:4])}"
        + (" ..." if len(unique_paths) > 4 else ""),
    )


def _copy_payloads(
    source_root: Path,
    package_root: Path,
    mappings: Sequence[RetrofitPayloadMapping],
    warnings: list[str],
) -> list[str]:
    if source_root.is_file() and source_root.suffix.lower() == ".zip":
        return _copy_payloads_from_zip(source_root, package_root, mappings, warnings)
    copied: list[str] = []
    seen: set[str] = set()
    for mapping in mappings:
        source_normalized = normalize_mod_package_payload_path(mapping.source_path).as_posix().strip("/")
        target_normalized = normalize_mod_package_payload_path(mapping.target_path).as_posix().strip("/")
        if not source_normalized or not target_normalized:
            continue
        source_path = _source_path_for_payload(source_root, mapping.source_path, source_normalized)
        if source_path is None:
            warnings.append(f"Missing payload skipped: {mapping.source_path}")
            continue
        target_path = package_root.joinpath(*PurePosixPath(target_normalized).parts)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        key = target_normalized.casefold()
        if key not in seen:
            seen.add(key)
            copied.append(target_normalized)
    return copied


def _copy_payloads_from_zip(
    source_zip: Path,
    package_root: Path,
    mappings: Sequence[RetrofitPayloadMapping],
    warnings: list[str],
) -> list[str]:
    requested = {
        normalize_mod_package_payload_path(mapping.source_path).as_posix().strip("/").casefold(): mapping
        for mapping in mappings
        if normalize_mod_package_payload_path(mapping.source_path).as_posix().strip("/")
    }
    copied: list[str] = []
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(source_zip) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                normalized = _payload_path_from_any_member(info.filename)
                key = normalized.casefold()
                mapping = requested.get(key)
                if not normalized or mapping is None or key in seen:
                    continue
                target_normalized = normalize_mod_package_payload_path(mapping.target_path).as_posix().strip("/")
                if not target_normalized:
                    continue
                target_path = package_root.joinpath(*PurePosixPath(target_normalized).parts)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source_handle, target_path.open("wb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle)
                seen.add(key)
                copied.append(target_normalized)
    except (OSError, zipfile.BadZipFile) as exc:
        warnings.append(f"Zip payload copy failed: {exc}")
    for mapping in mappings:
        normalized = normalize_mod_package_payload_path(mapping.source_path).as_posix().strip("/")
        if normalized and normalized.casefold() not in seen:
            warnings.append(f"Missing payload skipped: {mapping.source_path}")
    return copied


def _source_path_for_payload(source_root: Path, payload_path: str, normalized: str) -> Path | None:
    candidates = (
        source_root.joinpath(*PurePosixPath(payload_path).parts),
        source_root / "files" / Path(*PurePosixPath(normalized).parts),
        source_root.joinpath(*PurePosixPath(normalized).parts),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _retrofit_export_options(
    manager_profile: str,
    kind: str,
    payload_paths: Sequence[str],
    override_options: ModPackageExportOptions | None = None,
) -> ModPackageExportOptions:
    defaults = mod_package_export_options_for_manager(manager_profile)
    base = override_options if isinstance(override_options, ModPackageExportOptions) else defaults
    base = dataclasses.replace(base, manager_targets=defaults.manager_targets, export_profiles=(), output_profile_suffix="")
    if manager_profile == "jmm":
        return dataclasses.replace(
            base,
            manager_targets=("jmm",),
            structure="game_relative",
            create_manifest_json=False,
            create_mod_json=False,
            create_modinfo_json=False,
            create_info_json=False,
            create_no_encrypt_file=False,
            create_zip=True,
        )
    kind_normalized = str(kind or "").strip().lower()
    texture_only = bool(payload_paths) and all(PurePosixPath(path).suffix.lower() == ".dds" for path in payload_paths)
    if manager_profile == "dmm" and not (kind_normalized == "dds_loose_mod" and texture_only):
        return dataclasses.replace(
            base,
            structure="game_relative",
            create_manifest_json=True,
            create_mod_json=False,
            create_modinfo_json=True,
            create_info_json=False,
            create_no_encrypt_file=False,
            create_zip=True,
        )
    return dataclasses.replace(base, create_zip=True)


def _write_jmm_mod_json(
    package_root: Path,
    package: RetrofittableModPackage,
    payload_paths: Sequence[str],
    new_file_paths: Sequence[str] = (),
) -> Path:
    source_metadata = package.manifest
    source_target = normalize_mod_package_payload_path(_metadata_text(source_metadata, "target")).as_posix().strip("/")
    repaired_targets = {path.casefold() for path in payload_paths}
    target = source_target if source_target.casefold() in repaired_targets else _first_payload_with_suffix(payload_paths, (".pac", ".pam", ".pamlod"))
    path = write_jmm_mod_json(
        package_root,
        ModPackageInfo(
            title=package.package_info.title or _metadata_text(source_metadata, "name") or package.root.stem,
            version=package.package_info.version or "1.0",
            author=package.package_info.author,
            description=package.package_info.description,
            nexus_url=package.package_info.nexus_url,
        ),
        payload_paths=payload_paths,
        new_file_paths=tuple(dict.fromkeys([*(_jmm_new_paths(source_metadata, payload_paths)), *new_file_paths])),
        kind=_metadata_text(source_metadata, "kind") or package.kind or "file_replacement",
    )
    if target:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["target"] = target
        if _metadata_text(source_metadata, "category"):
            payload["category"] = _metadata_text(source_metadata, "category")
        path.write_text(json.dumps(_compact_retrofit_value(payload), indent=2), encoding="utf-8")
    return path


def _first_payload_with_suffix(payload_paths: Sequence[str], suffixes: Sequence[str]) -> str:
    normalized_suffixes = tuple(suffix.lower() for suffix in suffixes)
    for path in payload_paths:
        if PurePosixPath(path).suffix.lower() in normalized_suffixes:
            return path
    return payload_paths[0] if payload_paths else ""


def _infer_jmm_category(target: str, payload_paths: Sequence[str]) -> str:
    text = " ".join((target, *payload_paths)).lower()
    if "weapon" in text:
        return "weapon"
    if "/ui/" in f"/{text}":
        return "ui"
    if "/character/" in f"/{text}":
        return "character"
    if "/object/" in f"/{text}":
        return "object"
    return "file_replacement"


def _jmm_new_paths(source_metadata: Mapping[str, object], payload_paths: Sequence[str]) -> list[str]:
    source_new_paths = source_metadata.get("new_paths")
    if isinstance(source_new_paths, Sequence) and not isinstance(source_new_paths, (str, bytes, bytearray)):
        result = [_payload_path_from_any_member(str(path or "")) for path in source_new_paths]
        return [path for path in result if path]
    return [path for path in payload_paths if PurePosixPath(path).suffix.lower() == ".dds"]


def _compact_retrofit_value(value: object) -> object:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            compacted = _compact_retrofit_value(item)
            if compacted in ("", None, [], {}):
                continue
            result[str(key)] = compacted
        return result
    if isinstance(value, list):
        return [_compact_retrofit_value(item) for item in value if _compact_retrofit_value(item) not in ("", None, [], {})]
    return value


def _write_retrofit_package_zip(root: Path) -> Path:
    zip_path = root.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())
    return zip_path


def _should_preserve_mesh_manifest(package: RetrofittableModPackage, payload_paths: Sequence[str]) -> bool:
    if str(package.kind or "").strip().lower() != "mesh_loose_mod":
        return False
    return bool(package.manifest.get("assets") or package.manifest.get("files") or payload_paths)


def _mesh_assets_from_manifest(
    manifest: Mapping[str, object],
    source_to_target: Mapping[str, str] | None = None,
) -> tuple[MeshLooseModAsset, ...]:
    assets = manifest.get("assets")
    if not isinstance(assets, Sequence) or isinstance(assets, (str, bytes, bytearray)):
        return ()
    path_map = source_to_target or {}
    result: list[MeshLooseModAsset] = []
    for item in assets:
        if not isinstance(item, Mapping):
            continue
        source_entry_path = normalize_mod_package_payload_path(_metadata_text(item, "entry_path")).as_posix().strip("/")
        entry_path = path_map.get(source_entry_path.casefold(), source_entry_path)
        result.append(
            MeshLooseModAsset(
                entry_path=entry_path,
                package_group=_metadata_text(item, "package_group"),
                format=_metadata_text(item, "format"),
                obj_path=_metadata_text(item, "obj_path"),
                vertices=_metadata_int(item.get("vertices")),
                faces=_metadata_int(item.get("faces")),
                submeshes=_metadata_int(item.get("submeshes")),
                generated_from=_metadata_text(item, "generated_from"),
                note=_metadata_text(item, "note"),
            )
        )
    return tuple(result)


def _mesh_files_from_manifest(
    manifest: Mapping[str, object],
    fallback_paths: Sequence[str],
    source_to_target: Mapping[str, str] | None = None,
) -> tuple[MeshLooseModFile, ...]:
    files = manifest.get("files")
    result: list[MeshLooseModFile] = []
    path_map = source_to_target or {}
    if isinstance(files, Sequence) and not isinstance(files, (str, bytes, bytearray)):
        for item in files:
            if not isinstance(item, Mapping):
                continue
            source_path = normalize_mod_package_payload_path(_metadata_text(item, "path")).as_posix().strip("/")
            path = path_map.get(source_path.casefold(), source_path)
            if not path:
                continue
            result.append(
                MeshLooseModFile(
                    path=path,
                    package_group=_metadata_text(item, "package_group"),
                    format=_metadata_text(item, "format") or PurePosixPath(path).suffix.lstrip("."),
                    is_new=bool(item.get("is_new", False)),
                    generated_from=_metadata_text(item, "generated_from"),
                    note=_metadata_text(item, "note"),
                )
            )
    if result:
        return tuple(result)
    return tuple(
        MeshLooseModFile(path=path, package_group="", format=PurePosixPath(path).suffix.lstrip("."))
        for path in fallback_paths
    )


def _metadata_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _retrofit_extra_fields(manifest: Mapping[str, object]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for key in ("game_build", "game_metadata", "include_paired_lod", "asset_count", "file_count"):
        value = manifest.get(key)
        if value not in ("", None, [], {}):
            fields[key] = value
    return fields


__all__ = [
    "RETROFIT_MANAGER_PROFILES",
    "RetrofitPathRepairSummary",
    "RetrofitPayloadMapping",
    "RetrofittableModPackage",
    "ModPackageRetrofitResult",
    "analyze_retrofittable_mod_package",
    "build_retrofit_path_repair_summary",
    "merge_retrofittable_mod_packages",
    "retrofit_mod_package",
    "scan_retrofittable_mod_packages",
]
