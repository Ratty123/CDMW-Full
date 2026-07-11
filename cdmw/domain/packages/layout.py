"""Pure package folder and payload-path layout rules."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Sequence

from cdmw.domain.packages.export_policy import normalize_mod_package_manager_profile
from cdmw.models import ModPackageInfo


_KNOWN_MOD_CONTENT_ROOTS = {
    "actionchart",
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


def sanitize_mod_package_folder_name(name: str) -> str:
    sanitized = re.sub(r'[<>:"/\\\\|?*]+', "_", name).strip(" .")
    return sanitized or "Crimson Desert Mod Workbench Mod"


def resolve_mod_package_root(parent_root: Path, package_info: ModPackageInfo) -> Path:
    package_title = (package_info.title or "").strip() or "Crimson Desert Mod Workbench Mod"
    return parent_root / sanitize_mod_package_folder_name(package_title)


def resolve_mod_package_profile_root(
    parent_root: Path,
    package_info: ModPackageInfo,
    profile: str,
    *,
    multi_profile: bool,
) -> Path:
    root = resolve_mod_package_root(parent_root, package_info)
    normalized = normalize_mod_package_manager_profile(profile)
    return root.with_name(f"{root.name}_{normalized}") if multi_profile else root


def normalize_mod_package_payload_path(path_value: str | Path) -> PurePosixPath:
    normalized = str(path_value or "").replace("\\", "/").strip().strip("/")
    if not normalized:
        return PurePosixPath()
    parts = [part for part in PurePosixPath(normalized).parts if part not in ("", ".")]
    if not parts:
        return PurePosixPath()

    lowered_parts = [part.lower() for part in parts]
    if "files" in lowered_parts:
        files_index = lowered_parts.index("files")
        parts = parts[files_index + 1 :]
        lowered_parts = lowered_parts[files_index + 1 :]
    if parts and re.fullmatch(r"\d{4}", parts[0]):
        parts = parts[1:]
        lowered_parts = lowered_parts[1:]
    if len(parts) >= 2 and lowered_parts[0] == "gamedata" and lowered_parts[1] in _KNOWN_MOD_CONTENT_ROOTS:
        parts = parts[1:]
        lowered_parts = lowered_parts[1:]
    while len(parts) > 1 and lowered_parts and lowered_parts[0] not in _KNOWN_MOD_CONTENT_ROOTS:
        parts = parts[1:]
        lowered_parts = lowered_parts[1:]
    return PurePosixPath(*parts)


def is_mod_package_payload_path(path_value: str | Path) -> bool:
    normalized = normalize_mod_package_payload_path(path_value)
    if not normalized.parts or any(part.startswith(".") for part in normalized.parts):
        return False
    return not (
        len(normalized.parts) == 1
        and normalized.name.lower() in {"manifest.json", "mod.json", "modinfo.json", "info.json", "readme.txt"}
    )


def _payload_path_text(path_value: str | Path) -> str:
    normalized = normalize_mod_package_payload_path(path_value)
    if not normalized.parts or any(part.startswith(".") for part in normalized.parts):
        return ""
    return normalized.as_posix().strip("/")


def normalize_mod_package_new_path_prefixes(
    new_file_paths: Sequence[str | Path],
    *,
    all_payload_paths: Sequence[str | Path] | None = None,
) -> list[str]:
    # Exact files avoid false conflicts between mods sharing a parent folder.
    del all_payload_paths
    new_paths: list[str] = []
    seen: set[str] = set()
    for path_value in new_file_paths:
        path_text = _payload_path_text(path_value)
        if not path_text or path_text in seen:
            continue
        seen.add(path_text)
        new_paths.append(path_text)
    return new_paths


def safe_mod_package_files_dir(value: str) -> str:
    normalized = str(value or "files").replace("\\", "/").strip().strip("/")
    if not normalized or normalized.startswith(".") or "/" in normalized:
        return "files"
    return normalized


__all__ = [
    "is_mod_package_payload_path",
    "normalize_mod_package_new_path_prefixes",
    "normalize_mod_package_payload_path",
    "resolve_mod_package_profile_root",
    "resolve_mod_package_root",
    "safe_mod_package_files_dir",
    "sanitize_mod_package_folder_name",
]
