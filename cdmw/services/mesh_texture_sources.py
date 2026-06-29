"""Mesh Editor texture source resolution helpers."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cdmw.core.archive import ensure_archive_preview_source
from cdmw.models import ArchiveEntry


@dataclass(frozen=True, slots=True)
class MeshTextureSourceResolution:
    source_path: Path | None = None
    archive_entry: ArchiveEntry | None = None
    archive_path: str = ""
    status: str = "missing"
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.source_path is not None and Path(self.source_path).is_file()


def resolve_mesh_texture_source(
    texture: object,
    *,
    target_entry: object | None = None,
    entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]] | None = None,
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]] | None = None,
    ensure_source: Callable[..., tuple[Path, str]] = ensure_archive_preview_source,
    stop_event: threading.Event | None = None,
) -> MeshTextureSourceResolution:
    text = str(texture or "").strip()
    if not text:
        return MeshTextureSourceResolution(status="missing", message="No texture path was provided.")
    local = _local_file(text)
    if local is not None:
        return MeshTextureSourceResolution(source_path=local, status="local", message=f"Local texture source: {local.name}")
    entry = _best_archive_texture_entry(
        text,
        target_entry=target_entry,
        entries_by_normalized_path=entries_by_normalized_path,
        entries_by_basename=entries_by_basename,
    )
    if entry is None:
        return MeshTextureSourceResolution(status="missing", message=f"Texture source not found in loaded archives: {text}")
    try:
        source_path, note = ensure_source(entry, stop_event=stop_event)
    except TypeError:
        source_path, note = ensure_source(entry)
    resolved = Path(source_path).expanduser().resolve()
    return MeshTextureSourceResolution(
        source_path=resolved,
        archive_entry=entry,
        archive_path=str(entry.path or "").replace("\\", "/"),
        status="archive",
        message=f"Archive texture source ready: {entry.path}{' (' + note + ')' if note else ''}",
    )


def _local_file(value: str) -> Path | None:
    try:
        path = Path(value).expanduser()
    except OSError:
        return None
    try:
        return path.resolve() if path.is_file() else None
    except OSError:
        return None


def _best_archive_texture_entry(
    texture: str,
    *,
    target_entry: object | None,
    entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]] | None,
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]] | None,
) -> ArchiveEntry | None:
    candidates: dict[str, ArchiveEntry] = {}
    for key in _texture_lookup_keys(texture):
        for entry in tuple((entries_by_normalized_path or {}).get(key, ()) or ()):
            _remember_texture_candidate(candidates, entry)
    for basename in _texture_basename_keys(texture):
        for entry in tuple((entries_by_basename or {}).get(basename, ()) or ()):
            _remember_texture_candidate(candidates, entry)
    if not candidates:
        return None
    texture_keys = _texture_lookup_keys(texture)
    target_path = _normalize_virtual_path(getattr(target_entry, "path", ""))
    target_pamt = getattr(target_entry, "pamt_path", None)

    def score(entry: ArchiveEntry) -> tuple[int, str]:
        path = _normalize_virtual_path(entry.path)
        value = 0
        if path in texture_keys:
            value += 100
        if PurePosixPath(path).name in _texture_basename_keys(texture):
            value += 20
        if target_pamt is not None and getattr(entry, "pamt_path", None) == target_pamt:
            value += 18
        value += min(_shared_prefix_len(path, target_path) * 3, 24)
        return value, path

    return max(candidates.values(), key=score)


def _remember_texture_candidate(candidates: dict[str, ArchiveEntry], entry: object) -> None:
    if not isinstance(entry, ArchiveEntry) or entry.extension != ".dds":
        return
    path = _normalize_virtual_path(entry.path)
    if path:
        candidates.setdefault(path, entry)


def _texture_lookup_keys(texture: str) -> tuple[str, ...]:
    normalized = _normalize_virtual_path(texture)
    if not normalized:
        return ()
    keys = [normalized]
    path = PurePosixPath(normalized)
    if path.suffix.lower() != ".dds":
        keys.append(path.with_suffix(".dds").as_posix())
    return tuple(dict.fromkeys(keys))


def _texture_basename_keys(texture: str) -> tuple[str, ...]:
    names = [PurePosixPath(key).name.lower() for key in _texture_lookup_keys(texture)]
    return tuple(dict.fromkeys(name for name in names if name))


def _normalize_virtual_path(path: object) -> str:
    return PurePosixPath(str(path or "").replace("\\", "/").strip().strip("/")).as_posix().lower()


def _shared_prefix_len(left: str, right: str) -> int:
    if not left or not right:
        return 0
    count = 0
    for left_part, right_part in zip(PurePosixPath(left).parts, PurePosixPath(right).parts):
        if left_part != right_part:
            break
        count += 1
    return count


__all__ = ["MeshTextureSourceResolution", "resolve_mesh_texture_source"]
