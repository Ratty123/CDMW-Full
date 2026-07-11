from __future__ import annotations

from cdmw.models import ArchiveEntry
from collections.abc import Mapping
from cdmw.modding.mesh_parser import ParsedMesh
from pathlib import Path
from collections.abc import Sequence
from cdmw.services.mesh_texture_sources import resolve_mesh_texture_source
from hashlib import sha256

def _archive_source_file_snapshot(entries: Sequence[ArchiveEntry]) -> dict[str, dict[str, int | bool]]:
    path_texts: set[str] = set()
    for entry in entries:
        for path in (getattr(entry, "pamt_path", None), getattr(entry, "paz_file", None)):
            if path:
                path_texts.add(str(path))
    snapshot: dict[str, dict[str, int | bool]] = {}
    for path_text in sorted(path_texts, key=str.lower):
        path = Path(path_text)
        try:
            stat = path.stat()
        except OSError:
            snapshot[str(path)] = {"exists": False, "size": 0, "mtime_ns": 0}
        else:
            snapshot[str(path)] = {
                "exists": True,
                "size": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            }
    return snapshot

def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _archive_entry_provenance(entry: ArchiveEntry) -> dict[str, object]:
    return {
        "virtual_path": str(entry.path or "").replace("\\", "/"),
        "pamt_path": str(entry.pamt_path),
        "paz_path": str(entry.paz_file),
        "paz_index": int(entry.paz_index),
        "entry_offset": int(entry.offset),
        "compressed_bytes": int(entry.comp_size),
        "original_bytes": int(entry.orig_size),
    }

def _archive_content_fingerprints(paths: Sequence[Path]) -> dict[str, dict[str, object]]:
    fingerprints: dict[str, dict[str, object]] = {}
    for path in sorted({Path(value).resolve() for value in paths}, key=lambda value: str(value).casefold()):
        try:
            stat = path.stat()
            fingerprints[str(path)] = {
                "exists": True,
                "size": int(stat.st_size),
                "sha256": _sha256_file(path),
            }
        except OSError:
            fingerprints[str(path)] = {"exists": False, "size": 0, "sha256": ""}
    return fingerprints

def _resolve_real_archive_mesh_textures(
    mesh: ParsedMesh,
    model_entry: ArchiveEntry,
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
) -> tuple[dict[str, object], ...]:
    resolved_rows: list[dict[str, object]] = []
    for submesh_index, submesh in enumerate(mesh.submeshes):
        queries = tuple(
            dict.fromkeys(
                str(value or "").strip()
                for value in (submesh.texture, submesh.material, submesh.name)
                if str(value or "").strip()
            )
        )
        for query in queries:
            resolution = resolve_mesh_texture_source(
                query,
                target_entry=model_entry,
                entries_by_normalized_path=entries_by_path,
                entries_by_basename=entries_by_basename,
            )
            if not resolution.ok:
                continue
            source_path = Path(resolution.source_path).resolve()
            source_entry = resolution.archive_entry
            if source_entry is None:
                continue
            submesh.texture = str(source_path)
            resolved_rows.append(
                {
                    "submesh_index": submesh_index,
                    "submesh_name": str(submesh.name or ""),
                    "material": str(submesh.material or ""),
                    "query": query,
                    "archive_path": str(resolution.archive_path or ""),
                    "source_path": str(source_path),
                    "source_bytes": source_path.stat().st_size,
                    "source_sha256": _sha256_file(source_path),
                    "source_kind": str(resolution.status or ""),
                    "archive_provenance": _archive_entry_provenance(source_entry),
                }
            )
            break
    return tuple(resolved_rows)
