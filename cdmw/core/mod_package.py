from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import textwrap
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

from cdmw.constants import (
    APP_REPOSITORY_URL,
    APP_TITLE,
)
from cdmw.core.common import raise_if_cancelled
from cdmw.domain.packages.export_policy import (
    MOD_PACKAGE_FILES_WRAPPER_STRUCTURES,
    MOD_PACKAGE_MANAGER_PROFILE_LABELS,
    MOD_PACKAGE_MANAGER_PROFILES,
    MOD_PACKAGE_METADATA_ARTIFACTS,
    MOD_PACKAGE_METADATA_ARTIFACTS_BY_FILENAME,
    MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY,
    MOD_PACKAGE_STRUCTURES,
    ModPackageExportOptions,
    ModPackageMetadataArtifactInfo,
    effective_mod_package_export_options_for_kind as _effective_export_options_for_kind,
    mod_package_expanded_export_options,
    mod_package_export_options_for_manager,
    mod_package_export_options_for_profiles,
    mod_package_profile_uses_manager_metadata,
    normalize_mod_package_manager_profile,
    normalize_mod_package_manager_targets as _normalize_manager_targets,
)
from cdmw.domain.packages.layout import (
    _payload_path_text,
    is_mod_package_payload_path,
    normalize_mod_package_new_path_prefixes,
    normalize_mod_package_payload_path,
    resolve_mod_package_profile_root,
    resolve_mod_package_root,
    safe_mod_package_files_dir as _safe_files_dir,
    sanitize_mod_package_folder_name,
)
from cdmw.models import ModPackageInfo


@dataclasses.dataclass(slots=True)
class MeshLooseModAsset:
    entry_path: str
    package_group: str
    format: str
    obj_path: str = ""
    vertices: int = 0
    faces: int = 0
    submeshes: int = 0
    generated_from: str = ""
    note: str = ""


@dataclasses.dataclass(slots=True)
class MeshLooseModFile:
    path: str
    package_group: str
    format: str
    is_new: bool = False
    generated_from: str = ""
    note: str = ""


@dataclasses.dataclass(slots=True)
class ModPackageFinalizeResult:
    metadata_files: list[Path]
    zip_path: Path | None = None
    payload_root: Path | None = None
    warnings: list[str] = dataclasses.field(default_factory=list)


_README_WIDTH = 57
_README_LABEL_WIDTH = 18
_README_DECOR_LINES = (
    "::::::::::::-------------::---::-----:---------::::::::::",
    ":::::::::::--------::::---:----:------:----------::::::::",
    "::::::::::---::-:::::::-:-::--::::---:----===-----:::::::",
    ":::::::::-----:::::::::::-::::::::::::---====-----:::::::",
    ":::::::::----::::--::::::::::::::::::::-----------:::::::",
    "::::::::----:::-:::--------=-====-========---:--:::::::::",
    ":::::::----::--:::-----====+==+++=++**++++=---:::::::::::",
    ":::::::-------:::-----===+++==+++++****++++=--::::-::-:::",
    ":::::--------:::-=-======+++++++++++***+++=+--:::-:------",
    "::::--------:::-========++++*+++++++****++++-:::::-------",
    "--::-----:-::::-==+=----===+++++*+******++++-::::::------",
    "----:---::::::-==+===-------====+===-----===-::::::------",
    "--------::::::-=====----=----=+**+=---=--=+=-::::::------",
    "-----------:::-+++=========-==+**++=====+*+=-:::::-------",
    "----:::----:::=++++=++========+***+**++**+*=--:::--------",
    "------------::=++==========+=++*****#**++**---::---------",
    "::::::::::--:-=++===========+++********++++---:----------",
    "-::::::::::::--===========---==+*++****+++==-:----:------",
    "-:::::::::::::--===========-=--=++*****+++-:::-----:-----",
    "--::::::::::::::----====------=-===+***==-::::-----------",
    "--:::-::::::::::::---=--------=======++=---:-::----:-----",
    "-::::-----::::::::::-----====++**++=-==----:--::--::--:--",
    "---:::::::-----::::::--------====++==---:::----:----::---",
    "--::::::::::--:---::::--------======----::::------=------",
)
_README_LOGO_LINES = (
    "========     ===       ===  =====  ==  ====  ====  ======",
    "=======  ===  ==  ====  ==   ===   ==  ====  ====  ======",
    "======  ========  ====  ==  =   =  ==  ====  ====  ======",
    "======  ========  ====  ==  == ==  ==  ====  ====  ======",
    "======  ========  ====  ==  =====  ==   ==    ==  =======",
    "======  ========  ====  ==  =====  ===  ==    ==  =======",
    "======  ========  ====  ==  =====  ===  ==    ==  =======",
    "=======  ===  ==  ====  ==  =====  ====    ==    ========",
    "========     ===       ===  =====  =====  ====  =========",
)


def _compact_mapping(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {})
    }


def _compact_nested_value(value: object) -> object:
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            compacted = _compact_nested_value(item)
            if compacted in ("", None, [], {}):
                continue
            result[str(key)] = compacted
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            compacted = _compact_nested_value(item)
            if compacted in ("", None, [], {}):
                continue
            result.append(compacted)
        return result
    return value


def _common_mod_package_fields(
    package_info: ModPackageInfo,
    *,
    files_dir_value: str,
    manager_targets: Sequence[str],
    new_path_prefixes: Sequence[str],
) -> dict[str, object]:
    title = (package_info.title or "").strip() or "Crimson Desert Mod Workbench Mod"
    return _compact_nested_value(
        {
            "name": title,
            "title": title,
            "game": "Crimson Desert",
            "version": (package_info.version or "").strip() or "1.0",
            "author": (package_info.author or "").strip(),
            "description": (package_info.description or "").strip(),
            "nexus_url": (package_info.nexus_url or "").strip(),
            "generator": APP_TITLE,
            "files_dir": files_dir_value,
            "files_root": files_dir_value if files_dir_value != "." else "",
            "manager_targets": list(manager_targets),
            "manager_target_labels": [MOD_PACKAGE_MANAGER_PROFILE_LABELS.get(target, target) for target in manager_targets],
            "new_paths": list(new_path_prefixes),
        }
    )  # type: ignore[return-value]


def _modinfo_payload(
    package_info: ModPackageInfo,
    options: ModPackageExportOptions,
    *,
    files_dir_value: str,
    manager_targets: Sequence[str],
    new_path_prefixes: Sequence[str],
) -> dict[str, object]:
    title = (package_info.title or "").strip() or "Crimson Desert Mod Workbench Mod"
    target_set = set(manager_targets)
    if target_set & {"cdumm", "dmm"}:
        payload: dict[str, object] = {
            "name": title,
            "version": (package_info.version or "").strip() or "1.0",
            "author": (package_info.author or "").strip(),
            "description": (package_info.description or "").strip(),
        }
    else:
        payload = {
            "name": title,
            "version": (package_info.version or "").strip() or "1.0",
            "author": (package_info.author or "").strip(),
            "description": (package_info.description or "").strip(),
            "generator": APP_TITLE,
        }
    if "cdumm" in target_set:
        payload["conflict_mode"] = (options.conflict_mode or "").strip()
        payload["target_language"] = (options.target_language or "").strip()
    return _compact_nested_value(payload)  # type: ignore[return-value]


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _first_payload_with_suffix(payload_paths: Sequence[str | Path], suffixes: Sequence[str]) -> str:
    normalized_suffixes = tuple(suffix.lower() for suffix in suffixes)
    for path_value in payload_paths:
        path_text = _payload_path_text(path_value)
        if path_text and PurePosixPath(path_text).suffix.lower() in normalized_suffixes:
            return path_text
    for path_value in payload_paths:
        path_text = _payload_path_text(path_value)
        if path_text:
            return path_text
    return ""


def _infer_jmm_category(target: str, payload_paths: Sequence[str | Path]) -> str:
    text = " ".join((target, *(_payload_path_text(path) for path in payload_paths))).lower()
    if "weapon" in text:
        return "weapon"
    if "armor" in text:
        return "armor"
    if "/ui/" in f"/{text}":
        return "ui"
    if "/character/" in f"/{text}":
        return "character"
    if "/object/" in f"/{text}":
        return "object"
    return "file_replacement"


def _jmm_mod_json_payload(
    package_info: ModPackageInfo,
    *,
    payload_paths: Sequence[str | Path],
    new_file_paths: Sequence[str | Path] = (),
    kind: str = "loose_mod",
) -> dict[str, object]:
    normalized_payloads = [
        path_text
        for path_text in (_payload_path_text(path) for path in payload_paths)
        if path_text
    ]
    target = _first_payload_with_suffix(normalized_payloads, (".pac", ".pam", ".pamlod")) or (normalized_payloads[0] if normalized_payloads else "")
    new_paths = normalize_mod_package_new_path_prefixes(new_file_paths, all_payload_paths=normalized_payloads)
    title = (package_info.title or "").strip() or "Crimson Desert Mod Workbench Mod"
    return _compact_nested_value(
        {
            "name": title,
            "title": title,
            "version": (package_info.version or "").strip() or "1.0",
            "author": (package_info.author or "").strip(),
            "game": "Crimson Desert",
            "description": (package_info.description or "").strip(),
            "kind": str(kind or "file_replacement").strip() or "file_replacement",
            "category": _infer_jmm_category(target, normalized_payloads),
            "target": target,
            "files": list(dict.fromkeys(normalized_payloads)),
            "new_paths": new_paths,
        }
    )  # type: ignore[return-value]


def write_jmm_mod_json(
    root: Path,
    package_info: ModPackageInfo,
    *,
    payload_paths: Sequence[str | Path],
    new_file_paths: Sequence[str | Path] = (),
    kind: str = "loose_mod",
) -> Path:
    return _write_json(
        root / "mod.json",
        _jmm_mod_json_payload(
            package_info,
            payload_paths=payload_paths,
            new_file_paths=new_file_paths,
            kind=kind,
        ),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _field_json_modinfo(package_info: ModPackageInfo) -> dict[str, object]:
    title = (package_info.title or "").strip() or "Crimson Desert Mod Workbench Mod"
    return _compact_nested_value(
        {
            "name": title,
            "title": title,
            "version": (package_info.version or "").strip() or "1.0",
            "author": (package_info.author or "").strip(),
            "description": (package_info.description or "").strip(),
            "nexus_url": (package_info.nexus_url or "").strip(),
        }
    )  # type: ignore[return-value]


def _write_field_json_v31_manifest(
    root: Path,
    package_info: ModPackageInfo,
    *,
    payload_paths: Sequence[str | Path],
) -> tuple[Path, list[str]]:
    warnings: list[str] = []
    targets: list[dict[str, object]] = []
    seen_vpaths: set[str] = set()
    for value in payload_paths:
        payload_text = normalize_mod_package_payload_path(value).as_posix()
        if not payload_text or not payload_text.lower().endswith(".dds"):
            continue
        source_rel = payload_text
        if payload_text.lower().startswith("assets/"):
            vpath_text = payload_text[len("assets/") :].strip("/")
            file_rel = payload_text
        else:
            vpath_text = payload_text.strip("/")
            file_rel = f"assets/{vpath_text}"
        if not vpath_text:
            continue
        source_path = root.joinpath(*PurePosixPath(source_rel).parts)
        asset_path = root.joinpath(*PurePosixPath(file_rel).parts)
        if not source_path.is_file() and asset_path.is_file():
            source_path = asset_path
        if not source_path.is_file():
            warnings.append(f"Field-JSON skipped missing DDS payload: {payload_text}")
            continue
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            same_file = source_path.resolve() == asset_path.resolve()
        except OSError:
            same_file = False
        if not same_file:
            shutil.copy2(source_path, asset_path)
        normalized_vpath = "/" + PurePosixPath(vpath_text).as_posix().lstrip("/")
        vpath_key = normalized_vpath.lower()
        if vpath_key in seen_vpaths:
            warnings.append(f"Field-JSON skipped duplicate DDS vpath: {normalized_vpath}")
            continue
        seen_vpaths.add(vpath_key)
        targets.append(
            {
                "kind": "asset",
                "asset_type": "dds",
                "file": PurePosixPath(file_rel).as_posix(),
                "vpath": normalized_vpath,
                "sha256": _sha256_file(asset_path),
                "size": asset_path.stat().st_size,
            }
        )

    payload = {
        "format": 3,
        "format_minor": 1,
        "modinfo": _field_json_modinfo(package_info),
        "targets": targets,
    }
    manifest_path = root / "mod.field.json"
    _write_json(manifest_path, payload)
    if not targets:
        warnings.append("Field-JSON manifest contains no DDS asset targets.")
    return manifest_path, warnings


def _payload_paths_under_root(root: Path, payload_paths: Sequence[str | Path]) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    resolved_root = root.expanduser().resolve()
    for value in payload_paths:
        path_text = _payload_path_text(value)
        if not path_text:
            continue
        path = root.joinpath(*PurePosixPath(path_text).parts)
        try:
            resolved_path = path.expanduser().resolve()
            resolved_path.relative_to(resolved_root)
        except (OSError, ValueError):
            continue
        key = str(resolved_path).lower()
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def _discover_payload_paths_under_root(root: Path) -> list[str]:
    ignored_names = {
        ".no_encrypt",
        "README.txt",
        "info.json",
        "manifest.json",
        "mod.field.json",
        "mod.json",
        "modinfo.json",
    }
    paths: list[str] = []
    if not root.exists():
        return paths
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in ignored_names:
            continue
        try:
            relative_path = path.relative_to(root)
        except ValueError:
            continue
        paths.append(relative_path.as_posix())
    return paths


def _move_payloads_to_files_dir(root: Path, payload_paths: Sequence[str | Path], files_dir_name: str) -> list[str]:
    moved: list[str] = []
    files_root = root / files_dir_name
    for source_path in _payload_paths_under_root(root, payload_paths):
        if not source_path.is_file():
            continue
        rel_text = _payload_path_text(source_path.relative_to(root))
        if not rel_text or rel_text.startswith(f"{files_dir_name}/"):
            continue
        target_path = files_root.joinpath(*PurePosixPath(rel_text).parts)
        if source_path.resolve() == target_path.resolve():
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            target_path.unlink()
        shutil.move(str(source_path), str(target_path))
        moved.append(rel_text)
    _remove_empty_moved_payload_dirs(root, moved, files_dir_name)
    return moved


def _remove_empty_moved_payload_dirs(root: Path, moved_paths: Sequence[str], files_dir_name: str) -> None:
    if not moved_paths:
        return
    try:
        resolved_root = root.expanduser().resolve()
        resolved_files_root = (root / files_dir_name).expanduser().resolve()
    except OSError:
        return

    candidates: dict[str, Path] = {}
    for moved_path in moved_paths:
        relative_parts = PurePosixPath(_payload_path_text(moved_path)).parts
        if not relative_parts:
            continue
        parent = root.joinpath(*relative_parts).parent
        while True:
            try:
                resolved_parent = parent.expanduser().resolve()
                resolved_parent.relative_to(resolved_root)
            except (OSError, ValueError):
                break
            if resolved_parent in {resolved_root, resolved_files_root}:
                break
            candidates[str(resolved_parent).lower()] = parent
            parent = parent.parent

    for directory in sorted(candidates.values(), key=lambda item: len(item.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            continue


_OPTIONAL_AUTHORITY_REPORT_FILENAMES = {
    "cdmw_material_authority_report.json",
    "cdmw_material_authority_report_check.json",
}


def _write_package_zip(
    root: Path,
    *,
    include_material_authority_reports: bool = False,
    stop_event: threading.Event | None = None,
) -> Path:
    raise_if_cancelled(stop_event, "Mod package ZIP creation cancelled.")
    zip_path = root.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    paths: list[Path] = []
    for path in root.rglob("*"):
        raise_if_cancelled(stop_event, "Mod package ZIP creation cancelled.")
        paths.append(path)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            raise_if_cancelled(stop_event, "Mod package ZIP creation cancelled.")
            if not path.is_file():
                continue
            if not include_material_authority_reports and path.name.lower() in _OPTIONAL_AUTHORITY_REPORT_FILENAMES:
                continue
            archive_name = path.relative_to(root).as_posix()
            if stop_event is None:
                archive.write(path, archive_name)
                continue
            archive_info = zipfile.ZipInfo.from_file(path, archive_name)
            archive_info.compress_type = archive.compression
            with path.open("rb") as source, archive.open(archive_info, "w", force_zip64=True) as target:
                while True:
                    raise_if_cancelled(stop_event, "Mod package ZIP creation cancelled.")
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
    raise_if_cancelled(stop_event, "Mod package ZIP creation cancelled.")
    return zip_path


def _readme_box_line(text: str = "") -> str:
    content_width = _README_WIDTH - 4
    normalized = str(text or "").rstrip()
    if len(normalized) > content_width:
        normalized = normalized[: content_width - 3].rstrip() + "..."
    return f"| {normalized:^{content_width}} |"


def _readme_banner_lines(title: str) -> list[str]:
    rule = "=" * _README_WIDTH
    border = "+" + "=" * (_README_WIDTH - 2) + "+"
    lines = [rule]
    lines.extend(line[:_README_WIDTH] for line in _README_DECOR_LINES)
    lines.append(rule)
    lines.extend(line[:_README_WIDTH] for line in _README_LOGO_LINES)
    lines.append(border)
    lines.append(_readme_box_line("Crimson Desert Mod Workbench"))
    lines.append(_readme_box_line("Generated Loose Mod Package"))
    if title:
        lines.append(_readme_box_line(title))
    lines.append(border)
    return lines


def _readme_add_blank_line(lines: list[str]) -> None:
    if lines and lines[-1] != "":
        lines.append("")


def _readme_add_section(lines: list[str], title: str) -> None:
    _readme_add_blank_line(lines)
    normalized = str(title or "").strip().upper()
    lines.append(normalized)
    lines.append("=" * _README_WIDTH)


def _readme_append_wrapped(
    lines: list[str],
    text: str,
    *,
    indent: str = "",
    subsequent_indent: str | None = None,
) -> None:
    paragraphs = str(text or "").splitlines() or [""]
    continuation_indent = indent if subsequent_indent is None else subsequent_indent
    for index, paragraph in enumerate(paragraphs):
        stripped = paragraph.strip()
        if not stripped:
            lines.append("")
            continue
        if index:
            _readme_add_blank_line(lines)
        lines.extend(
            textwrap.wrap(
                stripped,
                width=_README_WIDTH,
                initial_indent=indent,
                subsequent_indent=continuation_indent,
                break_long_words=False,
            )
        )


def _readme_append_field(lines: list[str], label: str, value: str) -> None:
    prefix = f"  {str(label or '').strip():<{_README_LABEL_WIDTH}} "
    wrapped = textwrap.wrap(
        str(value or "").strip() or "-",
        width=_README_WIDTH,
        initial_indent=prefix,
        subsequent_indent=" " * len(prefix),
        break_long_words=False,
    )
    lines.extend(wrapped or [prefix.rstrip()])


def _readme_append_labeled_description(lines: list[str], label: str, description: str) -> None:
    clean_label = str(label or "").strip()
    if len(clean_label) > _README_LABEL_WIDTH:
        lines.append(f"  {clean_label}")
        _readme_append_wrapped(lines, description, indent="      ")
        return
    _readme_append_field(lines, clean_label, description)


def _readme_append_step(lines: list[str], number: int, text: str) -> None:
    prefix = f"{number}. "
    _readme_append_wrapped(lines, text, indent=prefix, subsequent_indent=" " * len(prefix))


def _metadata_package_file_lines(paths: Sequence[Path]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for path in paths:
        name = path.name
        if name in seen:
            continue
        seen.add(name)
        artifact = MOD_PACKAGE_METADATA_ARTIFACTS_BY_FILENAME.get(name)
        if artifact is None:
            continue
        _readme_append_labeled_description(lines, name, artifact.description)
    return lines


def finalize_mod_package_export(
    root: Path,
    package_info: ModPackageInfo,
    *,
    kind: str = "loose_mod",
    payload_paths: Sequence[str | Path] = (),
    new_file_paths: Sequence[str | Path] = (),
    extra_fields: dict[str, object] | None = None,
    options: ModPackageExportOptions | None = None,
    created_utc: str | None = None,
) -> ModPackageFinalizeResult:
    root.mkdir(parents=True, exist_ok=True)
    resolved_options = _effective_export_options_for_kind(kind, options or ModPackageExportOptions())
    files_dir_name = _safe_files_dir(resolved_options.files_dir)
    normalized_structure = str(resolved_options.structure or "game_relative").strip().lower()
    if normalized_structure not in MOD_PACKAGE_STRUCTURES:
        normalized_structure = "game_relative"
    uses_files_wrapper = normalized_structure in MOD_PACKAGE_FILES_WRAPPER_STRUCTURES
    files_dir_value = files_dir_name if uses_files_wrapper else "."
    payload_root = root / files_dir_name if uses_files_wrapper else root
    effective_payload_paths: Sequence[str | Path] = payload_paths or _discover_payload_paths_under_root(root)
    field_json_warnings: list[str] = []

    if uses_files_wrapper and effective_payload_paths:
        _move_payloads_to_files_dir(root, effective_payload_paths, files_dir_name)

    new_path_prefixes = normalize_mod_package_new_path_prefixes(
        new_file_paths,
        all_payload_paths=effective_payload_paths,
    )
    manager_targets = _normalize_manager_targets(resolved_options.manager_targets)
    created = created_utc or datetime.now(timezone.utc).isoformat(timespec="seconds")
    modinfo = _modinfo_payload(
        package_info,
        resolved_options,
        files_dir_value=files_dir_value,
        manager_targets=manager_targets,
        new_path_prefixes=new_path_prefixes,
    )
    metadata_files: list[Path] = []
    common_fields = _common_mod_package_fields(
        package_info,
        files_dir_value=files_dir_value,
        manager_targets=manager_targets,
        new_path_prefixes=new_path_prefixes,
    )

    manifest_payload = _compact_nested_value(
        {
            "format": "v1",
            "schema_version": 1,
            "kind": kind,
            "id": sanitize_mod_package_folder_name(str(modinfo.get("name") or root.name)),
            **common_fields,
            "created_utc": created,
            "structure": normalized_structure,
            **dict(extra_fields or {}),
        }
    )

    if resolved_options.create_no_encrypt_file:
        no_encrypt_path = root / ".no_encrypt"
        no_encrypt_path.touch()
        metadata_files.append(no_encrypt_path)
    else:
        no_encrypt_path = root / ".no_encrypt"
        if no_encrypt_path.exists():
            no_encrypt_path.unlink()

    if resolved_options.create_manifest_json:
        metadata_files.append(_write_json(root / "manifest.json", manifest_payload))

    mod_json_payload = _compact_nested_value(
        {
            "format": "crimson_desert_mod",
            "schema_version": 1,
            **common_fields,
            "modinfo": modinfo,
        }
    )
    if resolved_options.create_mod_json:
        metadata_files.append(_write_json(root / "mod.json", mod_json_payload))
    if "jmm" in set(manager_targets):
        metadata_files.append(
            write_jmm_mod_json(
                root,
                package_info,
                payload_paths=effective_payload_paths,
                new_file_paths=new_file_paths,
                kind=kind,
            )
        )
    if resolved_options.create_modinfo_json:
        metadata_files.append(_write_json(root / "modinfo.json", modinfo))
    if resolved_options.create_info_json:
        metadata_files.append(_write_json(root / "info.json", manifest_payload))
    if normalized_structure == "field_json_v31":
        field_manifest_path, field_json_warnings = _write_field_json_v31_manifest(
            root,
            package_info,
            payload_paths=effective_payload_paths,
        )
        metadata_files.append(field_manifest_path)

    zip_path = (
        _write_package_zip(
            root,
            include_material_authority_reports=bool(resolved_options.create_material_authority_report),
        )
        if resolved_options.create_zip
        else None
    )
    return ModPackageFinalizeResult(
        metadata_files=metadata_files,
        zip_path=zip_path,
        payload_root=payload_root,
        warnings=field_json_warnings,
    )


def write_mod_package_readme(
    root: Path,
    package_info: ModPackageInfo,
    *,
    created_utc: str,
    overview: str,
    loose_file_count: int,
    asset_count: int | None = None,
    include_paired_lod: bool | None = None,
    create_no_encrypt_file: bool = True,
    manifest_label: str = "Structured package metadata",
    metadata_files: Sequence[Path] = (),
    ready_zip_path: Path | None = None,
    manager_targets: Sequence[str] = (),
    structure: str = "game_relative",
    kind: str = "loose_mod",
) -> Path:
    title = (package_info.title or "").strip() or "Crimson Desert Mod Workbench Mod"
    version = (package_info.version or "").strip() or "1.0"
    author = (package_info.author or "").strip() or "-"
    description = (package_info.description or "").strip()
    metadata_names = {path.name for path in metadata_files}

    lines = _readme_banner_lines(title)

    _readme_add_section(lines, "Package")
    _readme_append_field(lines, "Title", title)
    _readme_append_field(lines, "Author", author)
    _readme_append_field(lines, "Version", version)
    _readme_append_field(lines, "Generated UTC", created_utc)
    _readme_append_field(lines, "Generator", APP_TITLE)
    _readme_append_field(lines, "Repository", APP_REPOSITORY_URL)

    if description:
        _readme_add_section(lines, "Description")
        _readme_append_wrapped(lines, description, indent="  ")

    _readme_add_section(lines, "Overview")
    _readme_append_wrapped(lines, overview, indent="  ")

    _readme_add_section(lines, "Package Summary")
    _readme_append_field(lines, "Loose files", str(loose_file_count))
    if asset_count is not None:
        _readme_append_field(lines, "Assets", str(asset_count))
    if include_paired_lod is not None:
        _readme_append_field(lines, "Paired LOD", "Yes" if include_paired_lod else "No")

    _readme_add_section(lines, "Included Package Files")
    metadata_lines = _metadata_package_file_lines(metadata_files)
    if metadata_lines:
        lines.extend(metadata_lines)
    else:
        _readme_append_labeled_description(lines, "manifest.json", manifest_label)
        if create_no_encrypt_file:
            artifact = MOD_PACKAGE_METADATA_ARTIFACTS_BY_FILENAME.get(".no_encrypt")
            description_text = (
                artifact.description if artifact is not None else "Marks the package for non-encrypted handling."
            )
            _readme_append_labeled_description(lines, ".no_encrypt", description_text)
    if ready_zip_path is not None:
        _readme_append_labeled_description(
            lines,
            ready_zip_path.name,
            "Ready-to-import zip written beside this folder with the same generated package contents.",
        )

    target_set = {str(target or "").strip().lower() for target in manager_targets if str(target or "").strip()}
    normalized_structure = str(structure or "").strip().lower()
    normalized_kind = str(kind or "").strip().lower()
    _readme_add_section(lines, "Installation")
    if "field_json" in target_set or normalized_structure == "field_json_v31":
        _readme_append_step(lines, 1, "Import this folder with a tool that supports Field-JSON v3.1 manifests.")
        _readme_append_step(lines, 2, "Verify mod.field.json and the assets/ folder stay together.")
        _readme_append_step(lines, 3, "Deploy or mount the package, then verify the replaced DDS assets in game.")
    elif "dmm" in target_set and normalized_kind == "dds_loose_mod":
        _readme_append_step(lines, 1, "Place this folder inside DMM's mods/_textures/ folder.")
        _readme_append_step(lines, 2, "Refresh DMM, enable the texture mod, then mount it.")
        _readme_append_step(lines, 3, "Verify the replaced DDS files in game.")
    elif "dmm" in target_set:
        _readme_append_step(lines, 1, "Place this folder inside DMM's mods/ folder.")
        _readme_append_step(lines, 2, "Refresh DMM, enable the mod, then mount it.")
        _readme_append_step(lines, 3, "Verify that the replaced assets load correctly in game.")
    elif "cdumm" in target_set:
        _readme_append_step(lines, 1, "Place this folder inside your CDUMM mods folder.")
        _readme_append_step(lines, 2, "Enable the mod in CDUMM. CDUMM reads modinfo.json for name, version, author, description, conflict_mode, and target_language.")
        _readme_append_step(lines, 3, "Verify that the replaced assets load correctly in game.")
    elif "jmm" in target_set:
        _readme_append_step(lines, 1, "Place this folder inside your JMM mods folder.")
        _readme_append_step(lines, 2, "Enable the mod in JMM. JMM reads mod.json for file replacement paths.")
        _readme_append_step(lines, 3, "Verify that the replaced assets load correctly in game.")
    else:
        _readme_append_step(lines, 1, "Copy or import the contents of the folder into your Crimson Desert mod manager.")
        _readme_append_step(lines, 2, "Deploy or enable the mod through your chosen mod manager.")
        _readme_append_step(lines, 3, "Verify that the replaced assets load correctly in game.")
    lines.append("")

    # Every package told people how to install it and nothing told them how to
    # get back. That is the step someone needs precisely when the game has
    # stopped working and they are least able to go looking.
    _readme_add_section(lines, "Removing This Mod")
    _readme_append_step(lines, 1, "Disable or unmount the mod in the manager you installed it with.")
    _readme_append_step(lines, 2, "Delete this folder from the manager's mods folder.")
    _readme_append_step(
        lines,
        3,
        "Your original game files were never modified, so removing the mod is enough to "
        "put everything back. Nothing needs verifying or repairing.",
    )
    lines.append("")

    if "dmm" in target_set and normalized_structure == "dmm_texture":
        _readme_add_section(lines, "Layout")
        _readme_append_wrapped(
            lines,
            "This DMM texture layout intentionally does not use a files/ wrapper.",
        )
    if normalized_structure == "field_json_v31":
        _readme_add_section(lines, "Layout")
        _readme_append_wrapped(
            lines,
            "This Field-JSON package writes DDS assets under assets/ and records their game vpaths in mod.field.json.",
        )

    readme_path = root / "README.txt"
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return readme_path


def write_mod_package_manifest(
    root: Path,
    package_info: ModPackageInfo,
    *,
    kind: str = "loose_mod",
    extra_fields: dict[str, object] | None = None,
    new_file_paths: Sequence[str | Path] = (),
    all_payload_paths: Sequence[str | Path] = (),
    export_options: ModPackageExportOptions | None = None,
    create_no_encrypt_file: bool = True,
    stop_event: threading.Event | None = None,
) -> Path:
    raise_if_cancelled(stop_event, "Mod package metadata creation cancelled.")
    root.mkdir(parents=True, exist_ok=True)
    resolved_export_options = _effective_export_options_for_kind(
        kind,
        export_options
        or ModPackageExportOptions(
            create_no_encrypt_file=create_no_encrypt_file,
        ),
    )
    effective_create_no_encrypt_file = bool(create_no_encrypt_file and resolved_export_options.create_no_encrypt_file)
    effective_payload_paths: Sequence[str | Path] = all_payload_paths or _discover_payload_paths_under_root(root)
    normalized_structure = str(resolved_export_options.structure or "game_relative").strip().lower()
    if normalized_structure not in MOD_PACKAGE_STRUCTURES:
        normalized_structure = "game_relative"
    files_dir_name = _safe_files_dir(resolved_export_options.files_dir)
    files_dir_value = files_dir_name if normalized_structure in MOD_PACKAGE_FILES_WRAPPER_STRUCTURES else "."
    manager_targets = _normalize_manager_targets(resolved_export_options.manager_targets)
    new_path_prefixes = normalize_mod_package_new_path_prefixes(
        new_file_paths,
        all_payload_paths=effective_payload_paths,
    )
    common_fields = _common_mod_package_fields(
        package_info,
        files_dir_value=files_dir_value,
        manager_targets=manager_targets,
        new_path_prefixes=new_path_prefixes,
    )

    created_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = _compact_mapping(
        {
            "format": "v1",
            "schema_version": 1,
            "kind": kind,
            **common_fields,
            "created_utc": created_utc,
            "structure": normalized_structure,
        }
    )
    if extra_fields:
        payload.update(_compact_mapping(dict(extra_fields)))
    manifest_path = root / "manifest.json"
    if resolved_export_options.create_manifest_json:
        manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    elif manifest_path.exists():
        manifest_path.unlink()
    metadata_options = dataclasses.replace(
        resolved_export_options,
        create_manifest_json=False,
        create_no_encrypt_file=effective_create_no_encrypt_file,
        create_zip=False,
    )
    finalized = finalize_mod_package_export(
        root,
        package_info,
        kind=kind,
        payload_paths=effective_payload_paths,
        new_file_paths=new_file_paths,
        extra_fields=extra_fields,
        options=metadata_options,
        created_utc=created_utc,
    )
    ready_zip_path = root.with_suffix(".zip") if resolved_export_options.create_zip else None
    metadata_files = [
        *([manifest_path] if manifest_path.exists() else []),
        *[path for path in finalized.metadata_files if path.name != "manifest.json"],
    ]
    payload_file_count = payload.get("file_count")
    loose_file_count = len(effective_payload_paths) if payload_file_count is None else int(payload_file_count or 0)
    readme_path = write_mod_package_readme(
        root,
        package_info,
        created_utc=created_utc,
        overview="This package contains loose file replacements generated by Crimson Desert Mod Workbench.",
        loose_file_count=loose_file_count,
        create_no_encrypt_file=effective_create_no_encrypt_file,
        manifest_label="Structured package metadata",
        metadata_files=metadata_files,
        ready_zip_path=ready_zip_path,
        manager_targets=manager_targets,
        structure=normalized_structure,
        kind=kind,
    )
    if ready_zip_path is not None:
        _write_package_zip(
            root,
            include_material_authority_reports=bool(resolved_export_options.create_material_authority_report),
            stop_event=stop_event,
        )
    raise_if_cancelled(stop_event, "Mod package metadata creation cancelled.")
    return manifest_path if manifest_path.exists() else (metadata_files[0] if metadata_files else readme_path)


def write_mesh_loose_mod_package_metadata(
    root: Path,
    package_info: ModPackageInfo,
    *,
    assets: Sequence[MeshLooseModAsset],
    files: Sequence[MeshLooseModFile],
    include_paired_lod: bool,
    export_options: ModPackageExportOptions | None = None,
    create_no_encrypt_file: bool = True,
    game_build: str = "",
    game_metadata: Mapping[str, object] | None = None,
    stop_event: threading.Event | None = None,
) -> list[Path]:
    raise_if_cancelled(stop_event, "Mod package metadata creation cancelled.")
    created_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    resolved_export_options = _effective_export_options_for_kind(
        "mesh_loose_mod",
        export_options
        or ModPackageExportOptions(
            create_no_encrypt_file=create_no_encrypt_file,
        ),
    )
    normalized_game_build = (game_build or "").strip()
    normalized_structure = str(resolved_export_options.structure or "game_relative").strip().lower()
    if normalized_structure not in MOD_PACKAGE_STRUCTURES:
        normalized_structure = "game_relative"
    files_dir_name = _safe_files_dir(resolved_export_options.files_dir)
    files_dir_value = files_dir_name if normalized_structure in MOD_PACKAGE_FILES_WRAPPER_STRUCTURES else "."
    manager_targets = _normalize_manager_targets(resolved_export_options.manager_targets)
    effective_create_no_encrypt_file = bool(create_no_encrypt_file and resolved_export_options.create_no_encrypt_file)
    file_paths = [file_info.path for file_info in files]
    new_path_prefixes = normalize_mod_package_new_path_prefixes(
        [file_info.path for file_info in files if bool(getattr(file_info, "is_new", False))],
        all_payload_paths=file_paths,
    )
    common_fields = _common_mod_package_fields(
        package_info,
        files_dir_value=files_dir_value,
        manager_targets=manager_targets,
        new_path_prefixes=new_path_prefixes,
    )
    root.mkdir(parents=True, exist_ok=True)
    no_encrypt_path = root / ".no_encrypt"
    if effective_create_no_encrypt_file:
        no_encrypt_path.touch()
    elif no_encrypt_path.exists():
        no_encrypt_path.unlink()

    def _compact_value(value: object) -> object:
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                compacted = _compact_value(item)
                if compacted in ("", None, [], {}):
                    continue
                result[key] = compacted
            return result
        if isinstance(value, list):
            result = []
            for item in value:
                compacted = _compact_value(item)
                if compacted in ("", None, [], {}):
                    continue
                result.append(compacted)
            return result
        return value

    normalized_game_metadata = _compact_value(dict(game_metadata or {})) if game_metadata else {}

    manifest_payload = _compact_value(
        {
            "format": "v1",
            "schema_version": 1,
            "kind": "mesh_loose_mod",
            **common_fields,
            "created_utc": created_utc,
            "structure": normalized_structure,
            "game_build": normalized_game_build,
            "game_metadata": normalized_game_metadata,
            "include_paired_lod": bool(include_paired_lod),
            "asset_count": len(assets),
            "file_count": len(files),
            "new_paths": new_path_prefixes,
            "assets": [
                _compact_value(
                    {
                        "entry_path": asset.entry_path,
                        "package_group": asset.package_group,
                        "format": asset.format,
                        "obj_path": asset.obj_path,
                        "vertices": asset.vertices,
                        "faces": asset.faces,
                        "submeshes": asset.submeshes,
                        "note": asset.note,
                    }
                )
                for asset in assets
            ],
            "files": [
                _compact_value(
                    {
                        "path": file_info.path,
                        "package_group": file_info.package_group,
                        "format": file_info.format,
                        "is_new": True if file_info.is_new else None,
                        "note": file_info.note,
                    }
                )
                for file_info in files
            ],
        }
    )
    manifest_path = root / "manifest.json"
    if resolved_export_options.create_manifest_json:
        manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
    elif manifest_path.exists():
        manifest_path.unlink()
    finalized = finalize_mod_package_export(
        root,
        package_info,
        kind="mesh_loose_mod",
        payload_paths=file_paths,
        new_file_paths=[file_info.path for file_info in files if bool(getattr(file_info, "is_new", False))],
        extra_fields={
            "game_build": normalized_game_build,
            "include_paired_lod": bool(include_paired_lod),
            "asset_count": len(assets),
            "file_count": len(files),
        },
        options=dataclasses.replace(
            resolved_export_options,
            create_manifest_json=False,
            create_no_encrypt_file=effective_create_no_encrypt_file,
            create_zip=False,
        ),
        created_utc=created_utc,
    )
    raise_if_cancelled(stop_event, "Mod package metadata creation cancelled.")
    if resolved_export_options.create_manifest_json:
        manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
    ready_zip_path = root.with_suffix(".zip") if resolved_export_options.create_zip else None
    metadata_files = [
        *([manifest_path] if manifest_path.exists() else []),
        *[path for path in finalized.metadata_files if path.name != "manifest.json"],
    ]
    if "jmm" in set(manager_targets):
        jmm_path = write_jmm_mod_json(
            root,
            package_info,
            payload_paths=file_paths,
            new_file_paths=[file_info.path for file_info in files if bool(getattr(file_info, "is_new", False))],
            kind="mesh_loose_mod",
        )
        if jmm_path not in metadata_files:
            metadata_files.append(jmm_path)
    readme_path = write_mod_package_readme(
        root,
        package_info,
        created_utc=created_utc,
        overview="This package contains loose mesh replacement files generated from an OBJ import workflow.",
        loose_file_count=len(files),
        asset_count=len(assets),
        include_paired_lod=bool(include_paired_lod),
        create_no_encrypt_file=effective_create_no_encrypt_file,
        manifest_label="Structured mesh package metadata",
        metadata_files=metadata_files,
        ready_zip_path=ready_zip_path,
        manager_targets=manager_targets,
        structure=normalized_structure,
        kind="mesh_loose_mod",
    )
    if ready_zip_path is not None:
        ready_zip_path = _write_package_zip(
            root,
            include_material_authority_reports=bool(resolved_export_options.create_material_authority_report),
            stop_event=stop_event,
        )
    return [
        *([manifest_path] if manifest_path.exists() else []),
        readme_path,
        *[path for path in finalized.metadata_files if path.name != "manifest.json"],
    ]
