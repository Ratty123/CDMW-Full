from __future__ import annotations

import dataclasses
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

from cdmw.core.mod_package import (
    MeshLooseModAsset,
    MeshLooseModFile,
    ModPackageExportOptions,
    mod_package_export_options_for_manager,
    normalize_mod_package_payload_path,
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
RETROFIT_MANAGER_PROFILES = ("universal", "dmm", "jmm", "cdumm", "crimson_sharp", "field_json")
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
) -> ModPackageRetrofitResult:
    normalized_profile = _normalize_retrofit_manager_profile(manager_profile)
    output_root = Path(output_parent).expanduser()
    package_root = output_root / f"{package.name}_{normalized_profile}"
    warnings: list[str] = list(package.warnings)
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True, exist_ok=True)

    copied_payload_paths = _copy_payloads(package.root, package_root, package.payload_paths, warnings)
    if normalized_profile == "jmm":
        mod_json_path = _write_jmm_mod_json(package_root, package, copied_payload_paths)
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
        )

    export_options = _retrofit_export_options(normalized_profile, package.kind, copied_payload_paths)

    if _should_preserve_mesh_manifest(package, copied_payload_paths):
        metadata_files = write_mesh_loose_mod_package_metadata(
            package_root,
            package.package_info,
            assets=_mesh_assets_from_manifest(package.manifest),
            files=_mesh_files_from_manifest(package.manifest, copied_payload_paths),
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


def _normalize_retrofit_manager_profile(profile: str) -> str:
    normalized = str(profile or "universal").strip().lower()
    aliases = {
        "field_json_v31": "field_json",
        "field-json": "field_json",
        "json": "jmm",
        "jmm_json": "jmm",
        "crimson_browser": "crimson_sharp",
        "sharp": "crimson_sharp",
        "definitive": "dmm",
        "definitive_mod_manager": "dmm",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in RETROFIT_MANAGER_PROFILES else "universal"


def _copy_payloads(
    source_root: Path,
    package_root: Path,
    payload_paths: Sequence[str],
    warnings: list[str],
) -> list[str]:
    if source_root.is_file() and source_root.suffix.lower() == ".zip":
        return _copy_payloads_from_zip(source_root, package_root, payload_paths, warnings)
    copied: list[str] = []
    seen: set[str] = set()
    for payload_path in payload_paths:
        normalized = normalize_mod_package_payload_path(payload_path).as_posix().strip("/")
        if not normalized:
            continue
        source_path = _source_path_for_payload(source_root, payload_path, normalized)
        if source_path is None:
            warnings.append(f"Missing payload skipped: {payload_path}")
            continue
        target_path = package_root.joinpath(*PurePosixPath(normalized).parts)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            copied.append(normalized)
    return copied


def _copy_payloads_from_zip(
    source_zip: Path,
    package_root: Path,
    payload_paths: Sequence[str],
    warnings: list[str],
) -> list[str]:
    requested = {normalize_mod_package_payload_path(path).as_posix().strip("/").casefold() for path in payload_paths}
    requested.discard("")
    copied: list[str] = []
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(source_zip) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                normalized = _payload_path_from_any_member(info.filename)
                if not normalized or normalized.casefold() not in requested or normalized.casefold() in seen:
                    continue
                target_path = package_root.joinpath(*PurePosixPath(normalized).parts)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source_handle, target_path.open("wb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle)
                seen.add(normalized.casefold())
                copied.append(normalized)
    except (OSError, zipfile.BadZipFile) as exc:
        warnings.append(f"Zip payload copy failed: {exc}")
    for payload_path in payload_paths:
        normalized = normalize_mod_package_payload_path(payload_path).as_posix().strip("/")
        if normalized and normalized.casefold() not in seen:
            warnings.append(f"Missing payload skipped: {payload_path}")
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
) -> ModPackageExportOptions:
    base = mod_package_export_options_for_manager(manager_profile)
    if manager_profile == "jmm":
        return ModPackageExportOptions(create_manifest_json=False, create_no_encrypt_file=False, create_zip=False)
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
) -> Path:
    source_metadata = package.manifest
    target = _metadata_text(source_metadata, "target") or _first_payload_with_suffix(payload_paths, (".pac", ".pam", ".pamlod"))
    payload = {
        "name": _metadata_text(source_metadata, "name") or package.package_info.title or package.root.stem,
        "title": package.package_info.title,
        "version": package.package_info.version or "1.0",
        "author": package.package_info.author,
        "game": _metadata_text(source_metadata, "game") or "Crimson Desert",
        "description": package.package_info.description,
        "kind": _metadata_text(source_metadata, "kind") or "file_replacement",
        "category": _metadata_text(source_metadata, "category") or _infer_jmm_category(target, payload_paths),
        "target": target,
        "files": list(payload_paths),
        "new_paths": _jmm_new_paths(source_metadata, payload_paths),
    }
    path = package_root / "mod.json"
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


def _mesh_assets_from_manifest(manifest: Mapping[str, object]) -> tuple[MeshLooseModAsset, ...]:
    assets = manifest.get("assets")
    if not isinstance(assets, Sequence) or isinstance(assets, (str, bytes, bytearray)):
        return ()
    result: list[MeshLooseModAsset] = []
    for item in assets:
        if not isinstance(item, Mapping):
            continue
        result.append(
            MeshLooseModAsset(
                entry_path=_metadata_text(item, "entry_path"),
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


def _mesh_files_from_manifest(manifest: Mapping[str, object], fallback_paths: Sequence[str]) -> tuple[MeshLooseModFile, ...]:
    files = manifest.get("files")
    result: list[MeshLooseModFile] = []
    if isinstance(files, Sequence) and not isinstance(files, (str, bytes, bytearray)):
        for item in files:
            if not isinstance(item, Mapping):
                continue
            path = normalize_mod_package_payload_path(_metadata_text(item, "path")).as_posix().strip("/")
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
    for key in ("game_build", "game_metadata", "include_paired_lod", "asset_count", "file_count", "new_paths"):
        value = manifest.get(key)
        if value not in ("", None, [], {}):
            fields[key] = value
    return fields


__all__ = [
    "RETROFIT_MANAGER_PROFILES",
    "RetrofittableModPackage",
    "ModPackageRetrofitResult",
    "analyze_retrofittable_mod_package",
    "retrofit_mod_package",
    "scan_retrofittable_mod_packages",
]
