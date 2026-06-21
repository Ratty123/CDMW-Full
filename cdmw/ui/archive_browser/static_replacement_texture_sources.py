"""Texture source registration helpers for static replacement."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableSequence, MutableSet, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cdmw.models import ArchiveEntry


@dataclass(frozen=True)
class ArchiveTextureLookupIndexes:
    path_index: dict[str, list[ArchiveEntry]]
    basename_index: dict[str, list[ArchiveEntry]]
    graph_reference_count: int
    dds_count: int
    sidecar_count: int


def register_texture_source_files(
    selected_files: Iterable[object],
    *,
    texture_files_for_mapping: MutableSequence[Path],
    seen_texture_file_keys: MutableSet[str],
    allowed_extensions: Sequence[str],
) -> bool:
    allowed = {str(extension or "").lower() for extension in tuple(allowed_extensions or ())}
    added = False
    for selected_file in tuple(selected_files or ()):
        texture_path = Path(str(selected_file)).expanduser()
        if not texture_path.is_file() or texture_path.suffix.lower() not in allowed:
            continue
        resolved = texture_path.resolve()
        key = str(resolved).lower()
        if key in seen_texture_file_keys:
            continue
        seen_texture_file_keys.add(key)
        texture_files_for_mapping.append(resolved)
        added = True
    return added


def register_texture_source_file(
    selected_file: object,
    *,
    texture_files_for_mapping: MutableSequence[Path],
    seen_texture_file_keys: MutableSet[str],
) -> bool:
    texture_path = Path(str(selected_file)).expanduser()
    if not texture_path.is_file():
        return False
    resolved = texture_path.resolve()
    key = str(resolved).lower()
    if key in seen_texture_file_keys:
        return False
    seen_texture_file_keys.add(key)
    texture_files_for_mapping.append(resolved)
    return True


def register_allowed_texture_source_file(
    selected_file: object,
    *,
    texture_files_for_mapping: MutableSequence[Path],
    seen_texture_file_keys: MutableSet[str],
    allowed_extensions: Sequence[str],
) -> Path | None:
    texture_path = Path(str(selected_file)).expanduser()
    allowed = {str(extension or "").lower() for extension in tuple(allowed_extensions or ())}
    if not texture_path.is_file() or texture_path.suffix.lower() not in allowed:
        return None
    resolved = texture_path.resolve()
    key = str(resolved).lower()
    if key not in seen_texture_file_keys:
        seen_texture_file_keys.add(key)
        texture_files_for_mapping.append(resolved)
    return resolved


def register_dialog_supplemental_file(
    path: object,
    *,
    dialog_added_supplemental_files: MutableSequence[Path],
    supplemental_files: Sequence[object],
    texture_files_for_mapping: MutableSequence[Path],
    allowed_texture_extensions: Sequence[str],
) -> Path | None:
    try:
        resolved = Path(str(path)).expanduser().resolve()
    except Exception:
        return None
    if not resolved.is_file():
        return None

    existing_keys = {
        str(existing.expanduser().resolve()).lower()
        for existing in tuple(dialog_added_supplemental_files)
        if isinstance(existing, Path)
    }
    original_keys: set[str] = set()
    for existing in tuple(supplemental_files or ()):
        if not isinstance(existing, Path):
            continue
        try:
            original_keys.add(str(existing.expanduser().resolve()).lower())
        except Exception:
            original_keys.add(str(existing).lower())

    key = str(resolved).lower()
    if key not in existing_keys and key not in original_keys:
        dialog_added_supplemental_files.append(resolved)

    allowed = {str(extension or "").lower() for extension in tuple(allowed_texture_extensions or ())}
    if resolved.suffix.lower() in allowed:
        texture_keys = {
            str(existing.expanduser().resolve()).lower()
            for existing in tuple(texture_files_for_mapping)
            if isinstance(existing, Path)
        }
        if key not in texture_keys:
            texture_files_for_mapping.append(resolved)
    return resolved


def texture_source_files_in_folder(
    selected_dir: object,
    *,
    allowed_extensions: Sequence[str],
) -> tuple[Path, ...]:
    root = Path(str(selected_dir or "")).expanduser()
    if not root.is_dir():
        return ()
    allowed = {str(extension or "").lower() for extension in tuple(allowed_extensions or ())}
    return tuple(
        candidate
        for candidate in sorted(root.rglob("*"))
        if candidate.is_file() and candidate.suffix.lower() in allowed
    )


def add_archive_texture_lookup_entry(
    path_index: dict[str, list[ArchiveEntry]],
    basename_index: dict[str, list[ArchiveEntry]],
    candidate: object,
) -> None:
    if not isinstance(candidate, ArchiveEntry):
        return
    normalized_path = str(getattr(candidate, "path", "") or "").replace("\\", "/").strip().lower()
    if not normalized_path:
        return
    path_bucket = path_index.setdefault(normalized_path, [])
    if candidate not in path_bucket:
        path_bucket.append(candidate)
    basename = PurePosixPath(normalized_path).name.lower()
    if basename:
        basename_bucket = basename_index.setdefault(basename, [])
        if candidate not in basename_bucket:
            basename_bucket.append(candidate)


def archive_texture_lookup_indexes_for_alignment(
    *,
    target_entry: object,
    graph_entries: Sequence[object] = (),
    graph_references: Sequence[object] = (),
    related_target_basenames: Sequence[str] = (),
    extension_index: Mapping[object, Sequence[object]] | None = None,
) -> ArchiveTextureLookupIndexes:
    path_index: dict[str, list[ArchiveEntry]] = {}
    basename_index: dict[str, list[ArchiveEntry]] = {}
    graph_reference_count = 0
    for related_entry in tuple(graph_entries or ()):
        add_archive_texture_lookup_entry(path_index, basename_index, related_entry)
        graph_reference_count += 1
    for reference in tuple(graph_references or ()):
        resolved_entry = getattr(reference, "resolved_entry", None)
        if isinstance(resolved_entry, ArchiveEntry):
            add_archive_texture_lookup_entry(path_index, basename_index, resolved_entry)
            graph_reference_count += 1

    related_basenames = {
        str(basename or "").strip().lower()
        for basename in tuple(related_target_basenames or ())
        if str(basename or "").strip()
    }
    source_basename = PurePosixPath(
        str(getattr(target_entry, "path", "") or "").replace("\\", "/")
    ).name.lower()
    if source_basename:
        related_basenames.add(source_basename)

    dds_count = 0
    sidecar_count = 0
    if isinstance(extension_index, Mapping):
        for candidate in extension_index.get(".dds", ()) or ():
            add_archive_texture_lookup_entry(path_index, basename_index, candidate)
            if isinstance(candidate, ArchiveEntry):
                dds_count += 1
        if related_basenames:
            for extension, candidates in extension_index.items():
                if str(extension or "").strip().lower() == ".dds":
                    continue
                for candidate in candidates or ():
                    if not isinstance(candidate, ArchiveEntry):
                        continue
                    candidate_basename = PurePosixPath(
                        str(getattr(candidate, "path", "") or "").replace("\\", "/")
                    ).name.lower()
                    if candidate_basename not in related_basenames:
                        continue
                    add_archive_texture_lookup_entry(path_index, basename_index, candidate)
                    sidecar_count += 1
    return ArchiveTextureLookupIndexes(
        path_index=path_index,
        basename_index=basename_index,
        graph_reference_count=graph_reference_count,
        dds_count=dds_count,
        sidecar_count=sidecar_count,
    )


__all__ = [
    "ArchiveTextureLookupIndexes",
    "add_archive_texture_lookup_entry",
    "archive_texture_lookup_indexes_for_alignment",
    "register_allowed_texture_source_file",
    "register_dialog_supplemental_file",
    "register_texture_source_file",
    "register_texture_source_files",
    "texture_source_files_in_folder",
]
