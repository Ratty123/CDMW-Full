from __future__ import annotations

from cdmw.models import ArchiveEntry
from collections.abc import Mapping
from cdmw.core.archive_preview_result_builder import build_archive_preview_result
from cdmw.modding.mesh_parser import ParsedMesh
from pathlib import Path
from collections.abc import Sequence
from cdmw.services.archive_query_service import (
    extract_archive_model_sidecar_texture_references,
)
from cdmw.services.mesh_dotnet_material_state import (
    copy_dotnet_preview_material_bindings,
)
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


def _hydrate_real_archive_mesh_materials(
    mesh: ParsedMesh,
    model_entry: ArchiveEntry,
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
    *,
    preview_model: object | None = None,
) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
    """Apply production sidecar authority and resolve its DDS inputs locally.

    The real-asset harness must exercise the same PAC XML material graph as the
    Archive Browser and Mesh Editor.  Parser-slot fallback is retained only as
    extra provenance for materials whose sidecar does not expose a usable base.
    Game archives remain read-only; extracted DDS files live in the normal
    preview cache outside the install.
    """

    _, sidecar_paths, _, _ = (
        extract_archive_model_sidecar_texture_references(
            model_entry,
            archive_entries_by_basename=dict(entries_by_basename),
        )
    )
    diagnostics: list[str] = []
    if preview_model is None:
        preview_result = build_archive_preview_result(
            model_entry,
            (),
            texture_entries_by_normalized_path=dict(entries_by_path),
            texture_entries_by_basename=dict(entries_by_basename),
            include_loose_preview_assets=False,
            visible_texture_mode="mesh_base_first",
            support_texture_slots=("normal", "material", "height", "emissive"),
            quality_tier="full",
        )
        if preview_result.status != "ok" or preview_result.preview_model is None:
            raise RuntimeError(
                f"Production Archive Browser material hydration failed for {model_entry.path}: "
                f"{preview_result.warning_text or preview_result.detail_text}"
            )
        preview_model = preview_result.preview_model
    diagnostics.append(
        "Reused production Archive Browser base, sidecar, and support-map bindings for Mesh Editor material hydration."
    )

    rows: list[dict[str, object]] = []
    seen_rows: set[tuple[int, str, str, str]] = set()
    resolution_cache: dict[str, object] = {}
    fingerprint_cache: dict[Path, str] = {}
    for preview_index, preview_mesh in enumerate(preview_model.meshes):
        submesh_index = int(getattr(preview_mesh, "source_submesh_index", preview_index) or 0)
        resolved_direct_slots: set[str] = set()
        for material_input in tuple(getattr(preview_mesh, "preview_material_texture_inputs", ()) or ()):
            virtual_source = str(
                getattr(material_input, "source_dds_path", "")
                or getattr(material_input, "source_texture_path", "")
                or ""
            ).strip()
            if not virtual_source:
                continue
            cache_key = virtual_source.replace("\\", "/").casefold()
            resolution = resolution_cache.get(cache_key)
            if resolution is None:
                resolution = resolve_mesh_texture_source(
                    virtual_source,
                    target_entry=model_entry,
                    entries_by_normalized_path=entries_by_path,
                    entries_by_basename=entries_by_basename,
                )
                resolution_cache[cache_key] = resolution
            if not resolution.ok or resolution.archive_entry is None:
                continue
            source_path = Path(resolution.source_path).resolve()
            material_input.source_texture_path = str(source_path)
            material_input.source_dds_path = str(source_path)
            semantic = str(
                getattr(material_input, "semantic_type", "")
                or getattr(material_input, "slot_kind", "")
                or "material"
            ).strip().casefold()
            binding_disposition = str(
                getattr(material_input, "binding_disposition", "") or ""
            ).strip().casefold()
            source_bound = (
                getattr(material_input, "owner_slot_index", None) not in (None, -1)
                or bool(str(getattr(material_input, "owner_wrapper_item_id", "") or "").strip())
                or str(getattr(material_input, "sidecar_kind", "") or "").strip().casefold()
                in {"pac_xml", "pami"}
            )
            legacy_direct = (
                not source_bound
                and not binding_disposition
                and not str(getattr(material_input, "layer_role", "") or "").strip()
                and not str(getattr(material_input, "layer_channel", "") or "").strip()
            )
            direct_slot = {
                "albedo": "base",
                "base": "base",
                "base_color": "base",
                "color": "base",
                "diffuse": "base",
                "normal": "normal",
                "height": "height",
                "emissive": "emissive",
            }.get(semantic, "material")
            if (
                (binding_disposition == "promoted" or legacy_direct)
                and direct_slot in {"base", "normal", "height", "emissive"}
                and direct_slot not in resolved_direct_slots
            ):
                direct_attr = (
                    f"preview_{direct_slot}_texture_dds_path"
                    if direct_slot != "base"
                    else "preview_texture_dds_path"
                )
                setattr(preview_mesh, direct_attr, str(source_path))
                resolved_direct_slots.add(direct_slot)
            parameter_name = str(getattr(material_input, "parameter_name", "") or "")
            row_key = (submesh_index, str(source_path).casefold(), parameter_name.casefold(), semantic)
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            if source_path not in fingerprint_cache:
                fingerprint_cache[source_path] = _sha256_file(source_path)
            rows.append(
                {
                    "submesh_index": submesh_index,
                    "submesh_name": str(getattr(preview_mesh, "material_name", "") or ""),
                    "material": str(getattr(preview_mesh, "material_name", "") or ""),
                    "query": virtual_source,
                    "parameter_name": parameter_name,
                    "semantic": semantic,
                    "owner_slot_index": getattr(material_input, "owner_slot_index", None),
                    "owner_wrapper_item_id": str(
                        getattr(material_input, "owner_wrapper_item_id", "") or ""
                    ),
                    "binding_authority": str(
                        getattr(material_input, "binding_authority", "") or ""
                    ),
                    "binding_disposition": binding_disposition,
                    "material_authority": "sidecar",
                    "sidecar_paths": list(sidecar_paths),
                    "archive_path": str(resolution.archive_path or ""),
                    "source_path": str(source_path),
                    "source_bytes": source_path.stat().st_size,
                    "source_sha256": fingerprint_cache[source_path],
                    "source_kind": str(
                        getattr(material_input, "source_kind", "") or resolution.status or ""
                    ),
                    "archive_provenance": _archive_entry_provenance(resolution.archive_entry),
                }
            )

    copy_dotnet_preview_material_bindings(mesh, preview_model)
    fallback_rows = _resolve_real_archive_mesh_textures(
        mesh,
        model_entry,
        entries_by_path,
        entries_by_basename,
    )
    for row in fallback_rows:
        row_key = (
            int(row.get("submesh_index", -1)),
            str(row.get("source_path", "")).casefold(),
            str(row.get("query", "")).casefold(),
            "fallback",
        )
        if row_key not in seen_rows:
            seen_rows.add(row_key)
            rows.append({**row, "material_authority": "parser_slot_fallback"})
    return tuple(rows), tuple(diagnostics)
