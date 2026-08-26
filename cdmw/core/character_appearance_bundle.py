"""Atomic manifest persistence for extracted character appearance bundles."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path, PurePosixPath
from typing import Mapping, Optional, Sequence

from cdmw.core.atomic_file import atomic_write_text
from cdmw.core.common import raise_if_cancelled
from cdmw.models import ArchiveEntry


CHARACTER_APPEARANCE_BUNDLE_FILENAME = "cdmw_character_appearance_bundle.json"
CHARACTER_APPEARANCE_BUNDLE_FORMAT = "cdmw_character_appearance_bundle_v1"
_BUNDLE_EXTENSIONS = {".app_xml", ".pab", ".pabc", ".pac", ".pamt", ".prefabdata_xml"}
_BUNDLE_FILE_LIMIT = 20_000
_BUNDLE_PAYLOAD_LIMIT = 256 * 1024 * 1024


def _normalized_path(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/").casefold()


def _sha256_file(path: Path, stop_event: Optional[threading.Event]) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                raise_if_cancelled(stop_event)
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"Could not hash character appearance file {path}: {exc}") from exc
    return digest.hexdigest()


def _bundle_output_path(package_root: Path, relative_path: str) -> Path:
    normalized = _normalized_path(relative_path)
    if not normalized or normalized.startswith("../"):
        raise ValueError(f"Character appearance bundle path is invalid: {relative_path}")
    root = package_root.expanduser().resolve()
    target = root.joinpath(*PurePosixPath(normalized).parts).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Character appearance bundle path escapes its root: {relative_path}") from exc
    return target


def _read_bundle_file(path: Path, stop_event: Optional[threading.Event]) -> bytes:
    try:
        if path.stat().st_size > _BUNDLE_PAYLOAD_LIMIT:
            raise ValueError(f"Character appearance bundle manifest is larger than {_BUNDLE_PAYLOAD_LIMIT:,} bytes")
        chunks: list[bytes] = []
        with path.open("rb") as handle:
            while True:
                raise_if_cancelled(stop_event)
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
    except OSError as exc:
        raise ValueError(f"Could not read character appearance bundle manifest {path}: {exc}") from exc
    return b"".join(chunks)


def write_character_appearance_bundle_manifest(
    output_root: Path | str,
    *,
    primary_model_path: str,
    selected_appearance_path: str,
    entries: Sequence[ArchiveEntry],
    fbx_paths: Sequence[Path | str] = (),
    stop_event: Optional[threading.Event] = None,
) -> Path:
    """Atomically publish identity and hashes for an extracted appearance tree."""

    package_root = Path(output_root).expanduser().resolve()
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    primary_key = _normalized_path(primary_model_path)
    selected_key = _normalized_path(selected_appearance_path)
    for entry in entries:
        raise_if_cancelled(stop_event)
        virtual_path = _normalized_path(getattr(entry, "path", ""))
        extension = str(getattr(entry, "extension", "") or PurePosixPath(virtual_path).suffix).casefold()
        if not virtual_path or virtual_path in seen or extension not in _BUNDLE_EXTENSIONS:
            continue
        seen.add(virtual_path)
        local_path = _bundle_output_path(package_root, virtual_path)
        if not local_path.is_file():
            raise ValueError(f"Extracted character appearance file is missing: {virtual_path}")
        role = "appearance_dependency"
        if virtual_path == primary_key:
            role = "primary_model"
        elif virtual_path == selected_key:
            role = "selected_appearance"
        elif extension == ".pab":
            role = "skeleton"
        elif extension == ".pabc":
            role = "skeleton_variation"
        elif extension == ".pamt":
            role = "morph_targets"
        elif extension == ".prefabdata_xml":
            role = "prefab_data"
        rows.append({
            "virtual_path": virtual_path,
            "relative_path": virtual_path,
            "role": role,
            "size": local_path.stat().st_size,
            "sha256": _sha256_file(local_path, stop_event),
        })
    fbx_rows: list[dict[str, object]] = []
    for raw_path in fbx_paths:
        candidate = Path(raw_path).expanduser().resolve()
        if not candidate.is_file() or candidate.suffix.casefold() != ".fbx":
            continue
        try:
            relative_path = candidate.relative_to(package_root).as_posix()
        except ValueError:
            continue
        fbx_rows.append({
            "relative_path": relative_path,
            "size": candidate.stat().st_size,
            "sha256": _sha256_file(candidate, stop_event),
        })
    if primary_key not in {str(row["virtual_path"]) for row in rows}:
        raise ValueError(f"Primary character model was not included in the bundle: {primary_model_path}")
    payload = {
        "format": CHARACTER_APPEARANCE_BUNDLE_FORMAT,
        "schema_version": 1,
        "primary_model_path": primary_key,
        "selected_appearance_path": selected_key,
        "files": rows,
        "blender_fbx": fbx_rows,
    }
    manifest_path = package_root / CHARACTER_APPEARANCE_BUNDLE_FILENAME
    atomic_write_text(manifest_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return manifest_path


def load_character_appearance_bundle_index(
    package_root: Path,
    *,
    stop_event: Optional[threading.Event],
) -> tuple[dict[str, Path], dict[str, tuple[Path, ...]], dict[str, str], Path] | None:
    manifest_path = package_root / CHARACTER_APPEARANCE_BUNDLE_FILENAME
    if not manifest_path.is_file():
        return None
    try:
        document = json.loads(_read_bundle_file(manifest_path, stop_event).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Character appearance bundle manifest is invalid: {exc}") from exc
    if not isinstance(document, Mapping) or document.get("format") != CHARACTER_APPEARANCE_BUNDLE_FORMAT:
        raise ValueError("Character appearance bundle manifest has an unsupported format")
    raw_rows = document.get("files")
    if not isinstance(raw_rows, list) or len(raw_rows) > _BUNDLE_FILE_LIMIT:
        raise ValueError("Character appearance bundle manifest file inventory is invalid")
    by_virtual: dict[str, Path] = {}
    by_basename_lists: dict[str, list[Path]] = {}
    hashes: dict[str, str] = {}
    for row in raw_rows:
        raise_if_cancelled(stop_event)
        if not isinstance(row, Mapping):
            raise ValueError("Character appearance bundle contains a non-object file row")
        virtual_path = _normalized_path(row.get("virtual_path", ""))
        relative_path = str(row.get("relative_path", "") or "")
        expected_hash = str(row.get("sha256", "") or "").casefold()
        if not virtual_path or len(expected_hash) != 64:
            raise ValueError("Character appearance bundle contains an incomplete file identity row")
        local_path = _bundle_output_path(package_root, relative_path)
        if not local_path.is_file():
            raise ValueError(f"Character appearance bundle file is missing: {relative_path}")
        by_virtual[virtual_path] = local_path
        by_basename_lists.setdefault(PurePosixPath(virtual_path).name, []).append(local_path)
        hashes[virtual_path] = expected_hash
    return by_virtual, {key: tuple(value) for key, value in by_basename_lists.items()}, hashes, manifest_path


__all__ = [
    "CHARACTER_APPEARANCE_BUNDLE_FILENAME",
    "CHARACTER_APPEARANCE_BUNDLE_FORMAT",
    "load_character_appearance_bundle_index",
    "write_character_appearance_bundle_manifest",
]
