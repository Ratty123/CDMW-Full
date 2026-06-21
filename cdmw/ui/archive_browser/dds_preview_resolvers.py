"""Archive DDS preview source lookup helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath


PreviewSourceResolver = Callable[[object], tuple[object, object]]


def archive_dds_preview_source_for_path(
    texture_path: str,
    entries_by_normalized_path: Mapping[str, Sequence[object]],
    *,
    ensure_preview_source: PreviewSourceResolver,
) -> Path | None:
    normalized_path = str(texture_path or "").replace("\\", "/").strip().strip("/").lower()
    if not normalized_path:
        return None
    for candidate in tuple(entries_by_normalized_path.get(normalized_path, ()) or ()):
        if str(getattr(candidate, "extension", "") or "").lower() != ".dds":
            continue
        try:
            source_path, _note = ensure_preview_source(candidate)
        except Exception:
            continue
        if isinstance(source_path, Path) and source_path.is_file():
            return source_path
    return None


def archive_dds_preview_sources_for_basename(
    basename: str,
    entries_by_basename: Mapping[str, Sequence[object]],
    *,
    ensure_preview_source: PreviewSourceResolver,
) -> tuple[Path, ...]:
    normalized_basename = PurePosixPath(str(basename or "").replace("\\", "/")).name.lower()
    if not normalized_basename:
        return ()
    paths: list[Path] = []
    for candidate in tuple(entries_by_basename.get(normalized_basename, ()) or ()):
        if str(getattr(candidate, "extension", "") or "").lower() != ".dds":
            continue
        try:
            source_path, _note = ensure_preview_source(candidate)
        except Exception:
            continue
        if isinstance(source_path, Path) and source_path.is_file():
            paths.append(source_path)
    return tuple(paths)


def archive_dds_preview_resolver_pair(
    entries_by_normalized_path: Mapping[str, Sequence[object]],
    entries_by_basename: Mapping[str, Sequence[object]],
    *,
    ensure_preview_source: PreviewSourceResolver,
) -> tuple[Callable[[str], Path | None], Callable[[str], tuple[Path, ...]]]:
    def resolve_path(texture_path: str) -> Path | None:
        return archive_dds_preview_source_for_path(
            texture_path,
            entries_by_normalized_path,
            ensure_preview_source=ensure_preview_source,
        )

    def resolve_basename(basename: str) -> tuple[Path, ...]:
        return archive_dds_preview_sources_for_basename(
            basename,
            entries_by_basename,
            ensure_preview_source=ensure_preview_source,
        )

    return resolve_path, resolve_basename


__all__ = [
    "archive_dds_preview_resolver_pair",
    "archive_dds_preview_source_for_path",
    "archive_dds_preview_sources_for_basename",
]
