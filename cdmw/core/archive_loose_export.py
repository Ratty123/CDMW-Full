from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_modding_constants import (
    ARCHIVE_MESH_EXTENSIONS,
    MESH_IMPORT_COMPANION_EXTENSIONS,
    MESH_IMPORT_SIDECAR_EXTENSIONS,
    _JMM_DESCRIPTOR_ALIAS_PAIRS,
    _MESH_IMPORT_AUTOCOPY_COMPANION_EXTENSIONS,
)
from cdmw.core.archive_mesh_types import (
    ActiveFileAuthorityAuditResult,
    ActiveFileAuthorityAuditRow,
    ArchiveLooseExportResult,
    MeshImportPreviewResult,
    MeshImportSupplementalFileSpec,
)
from cdmw.core.archive_patching import (
    ArchivePatchRequest,
    _detect_archive_game_metadata,
    _normalize_virtual_path,
    _package_root_from_entry,
    _safe_log,
)
from cdmw.models import ArchiveEntry, ModPackageInfo

if TYPE_CHECKING:
    from cdmw.core.mod_package import MeshLooseModFile, ModPackageExportOptions

def _mesh_loose_export_payload_path(path_value: str | Path, export_options: Optional["ModPackageExportOptions"]) -> str:
    from cdmw.core.mod_package import normalize_mod_package_payload_path

    normalized_path = normalize_mod_package_payload_path(path_value).as_posix()
    structure = str(getattr(export_options, "structure", "") or "").strip().lower()
    if structure != "custom_compact_paths":
        return normalized_path
    pure_path = PurePosixPath(normalized_path)
    parts = tuple(part for part in pure_path.parts if part)
    if not parts or parts[0].lower() != "character" or len(parts) <= 2:
        return normalized_path
    suffix = pure_path.suffix.lower()
    if suffix in ARCHIVE_MESH_EXTENSIONS or suffix in MESH_IMPORT_SIDECAR_EXTENSIONS or suffix in MESH_IMPORT_COMPANION_EXTENSIONS:
        return PurePosixPath("character", pure_path.name).as_posix()
    return normalized_path
def _mesh_import_companion_stem(path: str) -> str:
    pure = PurePosixPath(str(path or "").replace("\\", "/").strip())
    name = pure.name.lower()
    for suffix in (".pac.xml", ".pam.xml", ".pamlod.xml"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    suffix = pure.suffix.lower()
    if suffix in {".pac_xml", ".pam_xml", ".pamlod_xml", ".pami", ".xml", ".hkx", ".hkt", ".meshinfo"}:
        return pure.stem.lower()
    return pure.stem.lower()


def _mesh_import_is_exact_runtime_companion(primary_entry: ArchiveEntry, related_entry: ArchiveEntry) -> bool:
    related_extension = str(getattr(related_entry, "extension", "") or "").strip().lower()
    if related_extension not in _MESH_IMPORT_AUTOCOPY_COMPANION_EXTENSIONS:
        return False
    primary_path = str(getattr(primary_entry, "path", "") or "").replace("\\", "/").strip()
    related_path = str(getattr(related_entry, "path", "") or "").replace("\\", "/").strip()
    if not primary_path or not related_path or primary_path.lower() == related_path.lower():
        return False
    primary_stem = PurePosixPath(primary_path).stem.lower()
    related_stem = _mesh_import_companion_stem(related_path)
    if not primary_stem or related_stem != primary_stem:
        return False
    lowered_related = related_path.lower()
    if related_extension in {".hkx", ".hkt"}:
        return "meshphysics" in lowered_related or "physics" in lowered_related
    if related_extension == ".meshinfo":
        return True
    return "modelproperty" in lowered_related or related_extension in {".pami", ".xml"}


def _mesh_import_auto_companion_entries(
    primary_entry: ArchiveEntry,
    preview_result: MeshImportPreviewResult,
) -> Tuple[ArchiveEntry, ...]:
    entries: List[ArchiveEntry] = []
    seen: set[str] = set()
    for reference in tuple(getattr(preview_result, "texture_references", ()) or ()):
        related_entry = getattr(reference, "resolved_entry", None)
        if not isinstance(related_entry, ArchiveEntry):
            continue
        related_extension = str(getattr(related_entry, "extension", "") or "").strip().lower()
        if related_extension in MESH_IMPORT_SIDECAR_EXTENSIONS:
            # Unchanged material XML is optional for mesh-only edits.  Generated
            # or user-selected sidecars still flow through supplemental/related
            # export paths with explicit manifest notes.
            continue
        if related_extension in {".hkx", ".hkt"}:
            # Physics/collision companions are often unchanged archive data.  Keep
            # them out of source-owned loose packages unless the user explicitly
            # selects them in the related-file picker.
            continue
        if not _mesh_import_is_exact_runtime_companion(primary_entry, related_entry):
            continue
        key = str(getattr(related_entry, "path", "") or "").replace("\\", "/").strip().lower()
        if not key or key in seen:
            continue
        entries.append(related_entry)
        seen.add(key)
    return tuple(entries)
def _merge_note_text(existing_note: str, new_note: str) -> str:
    existing_parts = [part.strip() for part in str(existing_note or "").split(";") if part.strip()]
    for part in [part.strip() for part in str(new_note or "").split(";") if part.strip()]:
        if part not in existing_parts:
            existing_parts.append(part)
    return "; ".join(existing_parts)


def _dedupe_mesh_loose_file_rows(file_rows: Sequence["MeshLooseModFile"]) -> List["MeshLooseModFile"]:
    deduped: List["MeshLooseModFile"] = []
    by_path: Dict[str, "MeshLooseModFile"] = {}
    for row in file_rows:
        path_key = str(getattr(row, "path", "") or "").replace("\\", "/").strip().lower()
        if not path_key:
            continue
        existing = by_path.get(path_key)
        if existing is None:
            by_path[path_key] = row
            deduped.append(row)
            continue
        if not getattr(existing, "package_group", "") and getattr(row, "package_group", ""):
            existing.package_group = row.package_group
        if not getattr(existing, "format", "") and getattr(row, "format", ""):
            existing.format = row.format
        if not getattr(existing, "generated_from", "") and getattr(row, "generated_from", ""):
            existing.generated_from = row.generated_from
        existing.note = _merge_note_text(getattr(existing, "note", ""), getattr(row, "note", ""))
    return deduped


def _export_related_archive_entries(
    entries: Sequence[ArchiveEntry],
    output_root: Path,
    *,
    on_log: Optional[Callable[[str], None]] = None,
) -> List[Path]:
    from cdmw.core.archive_extraction import extract_archive_entry

    written_paths: List[Path] = []
    seen_paths: set[str] = set()
    for entry in entries:
        normalized_path = _normalize_virtual_path(entry.path)
        if not normalized_path or normalized_path in seen_paths:
            continue
        seen_paths.add(normalized_path)
        relative_parts = PurePosixPath(entry.path.replace("\\", "/")).parts
        if not relative_parts:
            continue
        target_path = output_root.joinpath(*relative_parts)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _safe_log(on_log, f"Copying related file: {target_path.relative_to(output_root).as_posix()}")
            extract_archive_entry(entry, target_path)
            written_paths.append(target_path)
        except Exception as exc:
            _safe_log(
                on_log,
                f"Warning: could not export related file {entry.path}: {exc}",
            )
    return written_paths










def _add_jmm_descriptor_alias_payloads(
    package_root: Path,
    *,
    written_files: List[Path],
    written_virtual_paths: set[str],
    payload_paths: List[str],
    new_file_paths: List[str],
    on_log: Optional[Callable[[str], None]] = None,
) -> None:
    for left, right in _JMM_DESCRIPTOR_ALIAS_PAIRS:
        left_key = left.casefold()
        right_key = right.casefold()
        if left_key in written_virtual_paths and right_key not in written_virtual_paths:
            source_rel, target_rel = left, right
        elif right_key in written_virtual_paths and left_key not in written_virtual_paths:
            source_rel, target_rel = right, left
        else:
            continue
        source_path = package_root.joinpath(*PurePosixPath(source_rel).parts)
        if not source_path.is_file():
            continue
        target_path = package_root.joinpath(*PurePosixPath(target_rel).parts)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(source_path.read_bytes())
        written_files.append(target_path)
        written_virtual_paths.add(target_rel.casefold())
        payload_paths.append(target_rel)
        new_file_paths.append(target_rel)
        _safe_log(on_log, f"Writing JMM descriptor alias payload: {target_rel}")


def export_archive_payloads_to_mod_ready_loose(
    requests: Sequence[ArchivePatchRequest],
    *,
    parent_root: Path,
    package_info: ModPackageInfo,
    export_options: Optional["ModPackageExportOptions"] = None,
    create_no_encrypt_file: bool = True,
    extra_payloads_to_include: Sequence[MeshImportSupplementalFileSpec] = (),
    on_log: Optional[Callable[[str], None]] = None,
) -> ArchiveLooseExportResult:
    from cdmw.core.mod_package import (
        mod_package_expanded_export_options,
        normalize_mod_package_payload_path,
        resolve_mod_package_profile_root,
        write_mod_package_manifest,
    )
    from cdmw.core.mod_package import ModPackageExportOptions

    if not requests:
        raise ValueError("No archive payloads were provided for mod-ready loose export.")

    base_options = export_options if isinstance(export_options, ModPackageExportOptions) else ModPackageExportOptions()
    expanded_options = mod_package_expanded_export_options(base_options, kind="archive_loose_mod")
    if len(expanded_options) > 1:
        results: List[ArchiveLooseExportResult] = []
        for profile, profile_options in expanded_options:
            _safe_log(on_log, f"Writing {profile} mod-ready loose package...")
            results.append(
                export_archive_payloads_to_mod_ready_loose(
                    requests,
                    parent_root=parent_root,
                    package_info=package_info,
                    export_options=profile_options,
                    create_no_encrypt_file=create_no_encrypt_file,
                    extra_payloads_to_include=extra_payloads_to_include,
                    on_log=on_log,
                )
            )
        first_root = results[0].package_root
        return ArchiveLooseExportResult(
            package_root=first_root,
            written_files=[path for result in results for path in result.written_files],
            package_roots=tuple(result.package_root for result in results),
        )

    profile, active_export_options = expanded_options[0]
    resolved_parent_root = parent_root.expanduser().resolve()
    package_root = resolve_mod_package_profile_root(
        resolved_parent_root,
        package_info,
        str(getattr(active_export_options, "output_profile_suffix", "") or profile),
        multi_profile=bool(getattr(active_export_options, "output_profile_suffix", "")),
    )
    package_root.mkdir(parents=True, exist_ok=True)

    written_files: List[Path] = []
    written_virtual_paths: set[str] = set()
    payload_paths: List[str] = []
    new_file_paths: List[str] = []
    for request in requests:
        normalized_request_path = normalize_mod_package_payload_path(request.entry.path).as_posix()
        relative_parts = PurePosixPath(normalized_request_path).parts
        if not relative_parts:
            raise ValueError(f"Archive path is invalid: {request.entry.path}")
        normalized_key = normalized_request_path.lower()
        if normalized_key in written_virtual_paths:
            continue
        target_path = package_root.joinpath(*relative_parts)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        _safe_log(on_log, f"Writing loose mod payload: {target_path.relative_to(package_root)}")
        target_path.write_bytes(request.payload_data)
        written_files.append(target_path)
        written_virtual_paths.add(normalized_key)
        payload_paths.append(normalized_request_path)

    for spec in tuple(extra_payloads_to_include or ()):
        if not isinstance(spec, MeshImportSupplementalFileSpec):
            continue
        normalized_target_path = normalize_mod_package_payload_path(spec.target_path or "").as_posix()
        if not normalized_target_path:
            _safe_log(on_log, f"Skipping extra source payload without a mapped loose target: {spec.source_path.name}")
            continue
        normalized_key = normalized_target_path.lower()
        if normalized_key in written_virtual_paths:
            continue
        payload_data = bytes(spec.payload_data or b"")
        if not payload_data:
            source_path = spec.source_path.expanduser().resolve()
            if not source_path.is_file():
                _safe_log(on_log, f"Skipping missing extra source payload: {spec.source_path}")
                continue
            payload_data = source_path.read_bytes()
        relative_parts = PurePosixPath(normalized_target_path).parts
        if not relative_parts:
            continue
        target_path = package_root.joinpath(*relative_parts)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        _safe_log(on_log, f"Writing extra loose mod payload: {target_path.relative_to(package_root)}")
        target_path.write_bytes(payload_data)
        written_files.append(target_path)
        written_virtual_paths.add(normalized_key)
        payload_paths.append(normalized_target_path)
        if not isinstance(spec.target_entry, ArchiveEntry):
            new_file_paths.append(normalized_target_path)

    manager_targets = {
        str(target or "").strip().casefold()
        for target in tuple(getattr(active_export_options, "manager_targets", ()) or ())
        if str(target or "").strip()
    }
    if "jmm" in manager_targets:
        _add_jmm_descriptor_alias_payloads(
            package_root,
            written_files=written_files,
            written_virtual_paths=written_virtual_paths,
            payload_paths=payload_paths,
            new_file_paths=new_file_paths,
            on_log=on_log,
        )

    manifest_path = write_mod_package_manifest(
        package_root,
        package_info,
        kind="archive_loose_mod",
        extra_fields={"file_count": len(written_files)},
        new_file_paths=new_file_paths,
        all_payload_paths=payload_paths or [path.relative_to(package_root).as_posix() for path in written_files],
        export_options=active_export_options,
        create_no_encrypt_file=create_no_encrypt_file,
    )
    written_files.append(manifest_path)

    return ArchiveLooseExportResult(package_root=package_root, written_files=written_files, package_roots=(package_root,))


def export_archive_mesh_payloads_to_mod_ready_loose(
    requests: Sequence[ArchivePatchRequest],
    *,
    primary_entry: ArchiveEntry,
    preview_result: MeshImportPreviewResult,
    source_obj_path: Path,
    source_display_label: str = "",
    parent_root: Path,
    package_info: ModPackageInfo,
    export_options: Optional["ModPackageExportOptions"] = None,
    create_no_encrypt_file: bool = True,
    include_related_files: bool = False,
    related_entries_to_include: Optional[Sequence[ArchiveEntry]] = None,
    supplemental_files_to_include: Sequence[MeshImportSupplementalFileSpec] = (),
    on_log: Optional[Callable[[str], None]] = None,
) -> ArchiveLooseExportResult:
    from cdmw.core.mod_package import (
        MeshLooseModAsset,
        MeshLooseModFile,
        mod_package_expanded_export_options,
        normalize_mod_package_payload_path,
        resolve_mod_package_profile_root,
        write_mesh_loose_mod_package_metadata,
    )
    from cdmw.core.mod_package import ModPackageExportOptions
    from cdmw.core.archive_extraction import extract_archive_entry

    if not requests:
        raise ValueError("No archive payloads were provided for mesh mod-ready loose export.")

    base_options = export_options if isinstance(export_options, ModPackageExportOptions) else ModPackageExportOptions()
    expanded_options = mod_package_expanded_export_options(base_options, kind="mesh_loose_mod")
    if len(expanded_options) > 1:
        results: List[ArchiveLooseExportResult] = []
        for profile, profile_options in expanded_options:
            _safe_log(on_log, f"Writing {profile} mod-ready mesh package...")
            results.append(
                export_archive_mesh_payloads_to_mod_ready_loose(
                    requests,
                    primary_entry=primary_entry,
                    preview_result=preview_result,
                    source_obj_path=source_obj_path,
                    source_display_label=source_display_label,
                    parent_root=parent_root,
                    package_info=package_info,
                    export_options=profile_options,
                    create_no_encrypt_file=create_no_encrypt_file,
                    include_related_files=include_related_files,
                    related_entries_to_include=related_entries_to_include,
                    supplemental_files_to_include=supplemental_files_to_include,
                    on_log=on_log,
                )
            )
        first_root = results[0].package_root
        return ArchiveLooseExportResult(
            package_root=first_root,
            written_files=[path for result in results for path in result.written_files],
            authority_audit_path=results[0].authority_audit_path,
            authority_mismatch_count=sum(result.authority_mismatch_count for result in results),
            package_roots=tuple(result.package_root for result in results),
        )

    profile, active_export_options = expanded_options[0]
    resolved_parent_root = parent_root.expanduser().resolve()
    package_root = resolve_mod_package_profile_root(
        resolved_parent_root,
        package_info,
        str(getattr(active_export_options, "output_profile_suffix", "") or profile),
        multi_profile=bool(getattr(active_export_options, "output_profile_suffix", "")),
    )
    _safe_log(on_log, f"Mod-ready mesh package root: {package_root}")
    _clear_existing_mesh_loose_package_root(package_root, resolved_parent_root, on_log=on_log)
    package_root.mkdir(parents=True, exist_ok=True)

    written_files: List[Path] = []
    file_rows: List[MeshLooseModFile] = []
    source_obj_display = source_display_label.strip() or source_obj_path.expanduser().resolve().as_posix()
    paired_lod_path = (preview_result.paired_lod_path or "").strip().replace("\\", "/")
    primary_path = primary_entry.path.replace("\\", "/")
    primary_manifest_path = _mesh_loose_export_payload_path(primary_path, active_export_options)
    written_virtual_paths: set[str] = set()
    for request in requests:
        normalized_request_path = normalize_mod_package_payload_path(request.entry.path).as_posix()
        output_request_path = _mesh_loose_export_payload_path(normalized_request_path, active_export_options)
        relative_parts = PurePosixPath(normalized_request_path).parts
        if not relative_parts:
            raise ValueError(f"Archive path is invalid: {request.entry.path}")
        output_relative_parts = PurePosixPath(output_request_path).parts
        if not output_relative_parts:
            raise ValueError(f"Archive path is invalid: {request.entry.path}")
        target_path = package_root.joinpath(*output_relative_parts)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        _safe_log(on_log, f"Writing loose mesh payload: {target_path.relative_to(package_root).as_posix()}")
        target_path.write_bytes(request.payload_data)
        written_files.append(target_path)
        note = ""
        written_virtual_paths.add(output_request_path.lower())
        if paired_lod_path and normalized_request_path == paired_lod_path and normalized_request_path != primary_path:
            note = f"Auto-generated paired LOD for {primary_entry.path}"
        file_rows.append(
            MeshLooseModFile(
                path=output_request_path,
                package_group=request.entry.pamt_path.parent.name,
                format=request.entry.extension.lstrip(".").lower(),
                is_new=False,
                generated_from=source_obj_display,
                note=note,
            )
        )

    supplemental_specs = [
        spec
        for spec in supplemental_files_to_include
        if isinstance(spec, MeshImportSupplementalFileSpec)
        and (bool(spec.payload_data) or spec.source_path.expanduser().resolve().is_file())
    ]
    for spec in supplemental_specs:
        normalized_target_path = normalize_mod_package_payload_path(spec.target_path or "").as_posix()
        if not normalized_target_path:
            _safe_log(
                on_log,
                f"Skipping selected supplemental file without a mapped loose target: {spec.source_path.name}",
            )
            continue
        output_target_path = _mesh_loose_export_payload_path(normalized_target_path, active_export_options)
        output_relative_parts = PurePosixPath(output_target_path).parts
        if not output_relative_parts:
            _safe_log(
                on_log,
                f"Skipping selected supplemental file with an invalid target path: {spec.source_path.name}",
            )
            continue
        normalized_target_key = output_target_path.lower()
        if normalized_target_key in written_virtual_paths:
            _safe_log(
                on_log,
                f"Skipping selected supplemental file already written in this package: {output_target_path}",
            )
            continue
        target_path = package_root.joinpath(*output_relative_parts)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if spec.payload_data:
            _safe_log(
                on_log,
                f"Writing generated supplemental payload: {target_path.relative_to(package_root).as_posix()}",
            )
            target_path.write_bytes(spec.payload_data)
        else:
            _safe_log(
                on_log,
                f"Copying selected supplemental file: {target_path.relative_to(package_root).as_posix()}",
            )
            shutil.copy2(spec.source_path, target_path)
        if target_path not in written_files:
            written_files.append(target_path)
        written_virtual_paths.add(normalized_target_key)
        if spec.note:
            note = spec.note
        elif spec.kind == "sidecar":
            note = f"Selected local sidecar included for {primary_entry.path}"
        elif spec.kind == "sidecar_generated":
            note = f"Patched material sidecar generated for {primary_entry.path}"
        elif spec.kind == "texture_generated":
            note = f"Generated replacement texture for {primary_entry.path}"
        elif spec.kind == "texture":
            note = f"Selected local texture override included for {primary_entry.path}"
        elif spec.kind == "companion":
            note = f"Selected Crimson companion metadata included for {primary_entry.path}"
        else:
            note = f"Selected local file included for {primary_entry.path}"
        package_group = ""
        is_new_file = not isinstance(spec.target_entry, ArchiveEntry)
        if isinstance(spec.target_entry, ArchiveEntry):
            package_group = spec.target_entry.pamt_path.parent.name
        file_rows.append(
            MeshLooseModFile(
                path=output_target_path,
                package_group=package_group,
                format=PurePosixPath(normalized_target_path).suffix.lstrip(".").lower()
                or spec.source_path.suffix.lstrip(".").lower(),
                is_new=is_new_file,
                generated_from=spec.source_path.as_posix(),
                note=note,
            )
        )

    related_entries: List[ArchiveEntry] = []
    if related_entries_to_include is not None:
        related_entries.extend(entry for entry in related_entries_to_include if isinstance(entry, ArchiveEntry))
    elif include_related_files:
        for reference in preview_result.texture_references:
            related_entry = getattr(reference, "resolved_entry", None)
            if isinstance(related_entry, ArchiveEntry):
                related_entries.append(related_entry)
    auto_companion_entries = _mesh_import_auto_companion_entries(primary_entry, preview_result)
    if auto_companion_entries:
        existing_related_keys = {
            str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower()
            for entry in related_entries
            if isinstance(entry, ArchiveEntry)
        }
        added_auto_companions: List[ArchiveEntry] = []
        for companion_entry in auto_companion_entries:
            key = str(getattr(companion_entry, "path", "") or "").replace("\\", "/").strip().lower()
            output_key = _mesh_loose_export_payload_path(key, active_export_options).lower() if key else ""
            if not key or key in existing_related_keys or output_key in written_virtual_paths:
                continue
            related_entries.append(companion_entry)
            existing_related_keys.add(key)
            added_auto_companions.append(companion_entry)
        if added_auto_companions:
            _safe_log(
                on_log,
                "Auto-including exact mesh companion file(s): "
                + ", ".join(entry.basename for entry in added_auto_companions[:6])
                + (" ..." if len(added_auto_companions) > 6 else ""),
            )

    if related_entries:
        for related_entry in related_entries:
            normalized_related_path = normalize_mod_package_payload_path(related_entry.path).as_posix()
            output_related_path = _mesh_loose_export_payload_path(normalized_related_path, active_export_options)
            if output_related_path.lower() in written_virtual_paths:
                continue
            output_relative_parts = PurePosixPath(output_related_path).parts
            if not output_relative_parts:
                continue
            target_path = package_root.joinpath(*output_relative_parts)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                _safe_log(on_log, f"Copying related file: {target_path.relative_to(package_root).as_posix()}")
                extract_archive_entry(related_entry, target_path)
                written_files.append(target_path)
                written_virtual_paths.add(output_related_path.lower())
                if related_entry.extension == ".dds":
                    note = f"Referenced texture copied from archive for {primary_entry.path}"
                elif related_entry.extension.lower() in MESH_IMPORT_SIDECAR_EXTENSIONS:
                    note = f"Unchanged original sidecar copied for {primary_entry.path}"
                else:
                    note = f"Selected archive related file copied for {primary_entry.path}"
                file_rows.append(
                    MeshLooseModFile(
                        path=output_related_path,
                        package_group=related_entry.pamt_path.parent.name,
                        format=related_entry.extension.lstrip(".").lower(),
                        is_new=False,
                        generated_from=source_obj_display,
                        note=note,
                    )
                )
            except Exception as exc:
                _safe_log(
                    on_log,
                    f"Warning: could not include related file {related_entry.path}: {exc}",
                )

    asset_rows = [
        MeshLooseModAsset(
            entry_path=primary_manifest_path,
            package_group=primary_entry.pamt_path.parent.name,
            format=primary_entry.extension.lstrip(".").lower(),
            obj_path=source_obj_display,
            vertices=int(preview_result.parsed_mesh.total_vertices or 0),
            faces=int(preview_result.parsed_mesh.total_faces or 0),
            submeshes=len(preview_result.parsed_mesh.submeshes),
        )
    ]
    deduped_file_rows = _dedupe_mesh_loose_file_rows(file_rows)
    duplicate_row_count = len(file_rows) - len(deduped_file_rows)
    if duplicate_row_count > 0:
        _safe_log(on_log, f"Removed {duplicate_row_count:,} duplicate file metadata row(s) before writing manifest.json.")
    game_metadata = _detect_archive_game_metadata(primary_entry)

    metadata_files = write_mesh_loose_mod_package_metadata(
        package_root,
        package_info,
        assets=asset_rows,
        files=deduped_file_rows,
        include_paired_lod=bool(paired_lod_path),
        export_options=active_export_options,
        create_no_encrypt_file=create_no_encrypt_file,
        game_build=str(game_metadata.get("game_build", "") or ""),
        game_metadata=game_metadata,
    )
    primary_lower = primary_path.casefold()
    cloth_like = any(token in primary_lower for token in ("cloak", "cloth", "cape", "pbd"))
    wrote_physics_companion = any(
        str(path.suffix).casefold() in {".hkx", ".hkt", ".meshinfo"}
        for path in written_files
    )
    if cloth_like and not wrote_physics_companion:
        _safe_log(
            on_log,
            "Cloth/PBD note: mesh-only cloak/cloth export changed the PAC payload, but unchanged .pac_xml "
            "alone does not update cloth physics. If the game still shows the old shape, verify the equipped "
            "variant, paired LOD, and physics/PBD companion files.",
        )
    authority_audit: Optional[ActiveFileAuthorityAuditResult] = None
    authority_audit_output_path = package_root.with_name(f"{package_root.name}_cdmw_active_file_authority_audit.json")
    if bool(getattr(active_export_options, "create_active_file_authority_audit", False)):
        try:
            authority_audit = audit_loose_package_active_file_authority(
                package_root,
                game_root=_package_root_from_entry(primary_entry),
                payload_files=written_files,
                write_audit_file=True,
                audit_output_path=authority_audit_output_path,
                on_log=on_log,
            )
            if authority_audit.audit_path is not None:
                try:
                    audit_display = authority_audit.audit_path.relative_to(package_root.parent).as_posix()
                except ValueError:
                    audit_display = authority_audit.audit_path.as_posix()
                _safe_log(
                    on_log,
                    "Active file authority audit report written outside package: "
                    f"{audit_display}",
                )
            for row in authority_audit.rows[:8]:
                _safe_log(
                    on_log,
                    "Active file authority: "
                    f"{row.status} {row.virtual_path} "
                    f"(package {row.local_size:,} bytes {row.local_sha256[:16]}"
                    + (
                        f"; active {row.active_source} {row.active_size:,} bytes {row.active_sha256[:16]}"
                        if row.active_source
                        else "; no active archive/loose match"
                    )
                    + ").",
                )
            for warning in authority_audit.warnings[:12]:
                _safe_log(on_log, warning)
            if authority_audit.mismatch_count:
                _safe_log(
                    on_log,
                    f"Active file authority audit found {authority_audit.mismatch_count:,} mismatch(es); "
                    "clean/disable stale active archives before judging in-game materials.",
                )
        except Exception as exc:
            _safe_log(on_log, f"Warning: active file authority audit failed: {exc}")
    elif _is_active_file_authority_audit_path(authority_audit_output_path):
        try:
            if authority_audit_output_path.is_file():
                authority_audit_output_path.unlink()
                _safe_log(on_log, f"Removed stale active file authority audit: {authority_audit_output_path}")
        except OSError as exc:
            _safe_log(on_log, f"Warning: could not remove stale active file authority audit: {exc}")
    _safe_log(
        on_log,
        f"Finished mod-ready mesh package with {len(written_files):,} payload file(s) and {len(metadata_files):,} metadata file(s).",
    )

    return ArchiveLooseExportResult(
        package_root=package_root,
        written_files=[*written_files, *metadata_files],
        authority_audit_path=authority_audit.audit_path if authority_audit is not None else None,
        authority_mismatch_count=authority_audit.mismatch_count if authority_audit is not None else 0,
        package_roots=(package_root,),
    )


def _clear_existing_mesh_loose_package_root(
    package_root: Path,
    resolved_parent_root: Path,
    *,
    on_log: Optional[Callable[[str], None]] = None,
) -> None:
    resolved_package_root = package_root.expanduser().resolve()
    if not resolved_package_root.exists():
        return
    if resolved_package_root == resolved_parent_root:
        raise ValueError(f"Refusing to clear loose export parent directory: {resolved_package_root}")
    try:
        resolved_package_root.relative_to(resolved_parent_root)
    except ValueError as exc:
        raise ValueError(
            f"Refusing to clear loose export folder outside the selected export root: {resolved_package_root}"
        ) from exc
    _safe_log(on_log, f"Clearing existing loose mesh package folder: {resolved_package_root}")
    for child in resolved_package_root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _loose_authority_virtual_path(package_root: Path, local_path: Path) -> str:
    try:
        relative = local_path.resolve().relative_to(package_root.resolve()).as_posix()
    except ValueError:
        relative = local_path.as_posix()
    parts = tuple(part for part in PurePosixPath(relative).parts if part)
    if not parts:
        return ""
    if parts[0].casefold() == "files" and len(parts) > 1:
        parts = parts[1:]
    if parts[0].casefold() in {"assets", "metadata"}:
        return ""
    if PurePosixPath(*parts).name.casefold() in {
        "manifest.json",
        "mod.json",
        "modinfo.json",
        "info.json",
        "readme.txt",
        ".no_encrypt",
        "cdmw_active_file_authority_audit.json",
    }:
        return ""
    return PurePosixPath(*parts).as_posix()


def _is_active_file_authority_audit_path(path: Path) -> bool:
    name = path.name.casefold()
    return name == "cdmw_active_file_authority_audit.json" or name.endswith(
        "_cdmw_active_file_authority_audit.json"
    )


def audit_loose_package_active_file_authority(
    package_root: Path,
    *,
    game_root: Path,
    payload_files: Sequence[Path],
    write_audit_file: bool = True,
    audit_output_path: Optional[Path] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> ActiveFileAuthorityAuditResult:
    """Compare loose package payload hashes with active archive entries.

    This catches stale DMM/archive installs where preview validates the newly
    exported loose folder but the game loads an older active package instead.
    """

    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_filtering import (
        archive_entry_is_mod_package,
        active_archive_entry_for_virtual_path,
    )
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.core.archive_scan_cache import discover_pamt_files

    root = Path(package_root).expanduser().resolve()
    resolved_game_root = Path(game_root).expanduser().resolve()
    result = ActiveFileAuthorityAuditResult(package_root=root, game_root=resolved_game_root)
    manifest_summary: Dict[str, object] = {}
    manifest_path = root / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest_payload, Mapping):
                manifest_summary = {
                    "structure": str(manifest_payload.get("structure", "") or ""),
                    "files_root": str(manifest_payload.get("files_root", "") or ""),
                    "manager_targets": list(manifest_payload.get("manager_targets", ()) or ()),
                    "file_count": int(manifest_payload.get("file_count", 0) or 0),
                    "assets": list(manifest_payload.get("assets", ()) or ())[:8],
                    "files": list(manifest_payload.get("files", ()) or ())[:32],
                }
        except Exception as exc:
            result_hint = f"Active file authority audit could not read manifest.json: {exc}"
            _safe_log(on_log, result_hint)
    structure = str(manifest_summary.get("structure", "") or "").strip().lower()
    files_root = str(manifest_summary.get("files_root", "") or "").strip()
    expects_files_wrapper = structure in {"files_wrapper", "custom_compact_paths"} or (files_root and files_root != ".")
    wanted: dict[str, tuple[str, Path, int, str]] = {}
    for raw_path in tuple(payload_files or ()):
        local_path = Path(raw_path)
        if not local_path.is_file():
            continue
        try:
            relative_parts_for_layout = tuple(part for part in local_path.resolve().relative_to(root).parts if part)
        except ValueError:
            relative_parts_for_layout = ()
        if expects_files_wrapper and relative_parts_for_layout and relative_parts_for_layout[0].casefold() != (files_root or "files").casefold():
            result_warning = (
                f"VERIFY LOOSE MOD TARGET: package metadata expects payloads under {files_root or 'files'}/, "
                f"but found {PurePosixPath(*relative_parts_for_layout).as_posix()}."
            )
            if result_warning not in result.warnings:
                result.warnings.append(result_warning)
            result.requires_report = True
        if not expects_files_wrapper and relative_parts_for_layout and relative_parts_for_layout[0].casefold() == "files":
            result_warning = (
                "VERIFY LOOSE MOD TARGET: package metadata is game-relative but payloads are under files/. "
                "Pick the CDUMM/files-wrapper profile if the manager expects files/."
            )
            if result_warning not in result.warnings:
                result.warnings.append(result_warning)
            result.requires_report = True
        virtual_path = _loose_authority_virtual_path(root, local_path)
        if not virtual_path:
            continue
        try:
            size = local_path.stat().st_size
            digest = _sha256_file(local_path)
        except OSError:
            continue
        wanted[virtual_path.casefold()] = (virtual_path, local_path, size, digest)

    if not wanted:
        return result
    entries_by_path: dict[str, list[ArchiveEntry]] = defaultdict(list)
    if not resolved_game_root.is_dir():
        result.warnings.append(f"Active file authority audit skipped; game root not found: {resolved_game_root}")
    else:
        for pamt_path in discover_pamt_files(resolved_game_root):
            try:
                entries = parse_archive_pamt(pamt_path)
            except Exception as exc:
                _safe_log(on_log, f"Authority audit skipped unreadable PAMT {pamt_path}: {exc}")
                continue
            for entry in entries:
                key = str(entry.path or "").replace("\\", "/").strip().casefold()
                if key in wanted:
                    entries_by_path[key].append(entry)

    for key, (virtual_path, local_path, local_size, local_sha) in sorted(wanted.items()):
        row = ActiveFileAuthorityAuditRow(
            virtual_path=virtual_path,
            local_path=local_path.as_posix(),
            local_size=int(local_size),
            local_sha256=local_sha,
        )
        candidates = entries_by_path.get(key, [])
        direct_loose_path = resolved_game_root.joinpath(*PurePosixPath(virtual_path).parts)
        direct_loose_exists = direct_loose_path.is_file()
        row.duplicate_count = len(candidates) + (1 if direct_loose_exists else 0)
        if direct_loose_exists:
            try:
                row.active_source = f"loose/{virtual_path}"
                row.active_size = direct_loose_path.stat().st_size
                row.active_sha256 = _sha256_file(direct_loose_path)
            except OSError as exc:
                row.status = "active_read_failed"
                row.note = str(exc)
                result.warnings.append(f"Authority audit could not read active loose payload for {virtual_path}: {exc}")
                result.requires_report = True
                result.rows.append(row)
                continue
            if row.active_sha256 == local_sha and row.active_size == local_size:
                row.status = "match"
            else:
                row.status = "mismatch"
                row.note = "Active loose payload differs from final package; in-game test may be using stale data."
                result.mismatch_count += 1
                result.requires_report = True
                result.warnings.append(
                    f"IN-GAME TEST BLOCKED: active loose file differs from package {virtual_path} "
                    f"(active {row.active_sha256[:16]}, loose {local_sha[:16]})."
                )
            result.rows.append(row)
            continue
        active_entry = active_archive_entry_for_virtual_path(candidates) if candidates else None
        if active_entry is None:
            row.status = "loose_only"
            row.note = "No active archive entry with this virtual path was found."
            result.rows.append(row)
            continue
        row.active_source = f"{active_entry.pamt_path.parent.name}/{active_entry.pamt_path.name}"
        row.active_size = int(getattr(active_entry, "orig_size", 0) or 0)
        try:
            active_data, _decompressed, _note = read_archive_entry_data(active_entry)
            row.active_sha256 = hashlib.sha256(active_data).hexdigest()
            row.active_size = len(active_data)
        except Exception as exc:
            row.status = "active_read_failed"
            row.note = str(exc)
            result.warnings.append(f"Authority audit could not read active archive payload for {virtual_path}: {exc}")
            result.requires_report = True
            result.rows.append(row)
            continue
        if row.active_sha256 == local_sha and row.active_size == local_size:
            row.status = "match"
        elif archive_entry_is_mod_package(active_entry):
            row.status = "mismatch"
            row.note = "Active mod archive payload differs from final loose package; in-game test may be using stale data."
            result.mismatch_count += 1
            result.requires_report = True
            result.warnings.append(
                f"IN-GAME TEST BLOCKED: active {row.active_source} differs from loose {virtual_path} "
                f"(active {row.active_sha256[:16]}, loose {local_sha[:16]})."
            )
        else:
            row.status = "replaces_archive"
            row.note = "Final loose package differs from base archive; expected for replacement mods."
        result.rows.append(row)

    audit_path = (
        Path(audit_output_path).expanduser().resolve()
        if audit_output_path is not None
        else root / "cdmw_active_file_authority_audit.json"
    )
    if write_audit_file and result.requires_report:
        audit_doc = {
            "schema": "cdmw_active_file_authority_audit_v1",
            "package_root": root.as_posix(),
            "game_root": resolved_game_root.as_posix(),
            "manager_layout": manifest_summary,
            "mismatch_count": result.mismatch_count,
            "warnings": list(result.warnings),
            "in_game_visibility_notes": [
                "If this report shows the edited PAC differs but the game still shows the original, check the equipped asset variant, enabled mod-manager profile, loose path structure, game cache, paired LOD, and cloth/physics companion files.",
                "Mesh-only cloth/cloak edits may still need matching physics/PBD companion work; unchanged .pac_xml alone does not update cloth simulation.",
            ],
            "rows": [dataclasses.asdict(row) for row in result.rows],
        }
        try:
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text(json.dumps(audit_doc, indent=2, sort_keys=True), encoding="utf-8")
            result.audit_path = audit_path
        except OSError as exc:
            result.warnings.append(f"Could not write active file authority audit: {exc}")
    elif write_audit_file and audit_output_path is not None and _is_active_file_authority_audit_path(audit_path):
        try:
            if audit_path.is_file():
                audit_path.unlink()
        except OSError as exc:
            result.warnings.append(f"Could not remove stale active file authority audit: {exc}")
    return result
