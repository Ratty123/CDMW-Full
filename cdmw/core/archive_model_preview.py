from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import threading
from dataclasses import fields
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    HkxPhysicsOverlayData,
    ModelPreviewData,
    ModelPreviewMesh,
    RelationConfidence,
)
from cdmw.core.common import RunCancelled, raise_if_cancelled
from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import _ARCHIVE_XML_LIKE_EXTENSIONS
from cdmw.core.archive_scan_cache import (
    _HKX_CONTEXT_MODEL_PREVIEW_CACHE,
    _HKX_CONTEXT_MODEL_PREVIEW_CACHE_LIMIT,
)
from cdmw.modding.skeleton_parser import parse_pab

if TYPE_CHECKING:
    from cdmw.modding.mesh_parser import ParsedMesh

_FAST_ARCHIVE_PREVIEW_MAX_FACES = 35_000


def build_hkx_descriptor_hint_from_xml_text(*args, **kwargs):
    from cdmw.core.archive_hkx_descriptor import build_hkx_descriptor_hint_from_xml_text as owner

    return owner(*args, **kwargs)


def build_hkx_editable_geometry_document(*args, **kwargs):
    from cdmw.core.archive_hkx_editable_geometry import build_hkx_editable_geometry_document as owner

    return owner(*args, **kwargs)


def build_hkx_physics_overlay_from_document(*args, **kwargs):
    from cdmw.core.archive_hkx_overlay import build_hkx_physics_overlay_from_document as owner

    return owner(*args, **kwargs)


def build_mesh_preview_from_bytes(*args, **kwargs):
    from cdmw.core.archive_mesh_import_preview import build_mesh_preview_from_bytes as owner

    return owner(*args, **kwargs)


def merge_hkx_physics_overlays(*args, **kwargs):
    from cdmw.core.archive_hkx_overlay import merge_hkx_physics_overlays as owner

    return owner(*args, **kwargs)


def build_pam_model_preview(*args, **kwargs):
    from cdmw.core.model_preview import build_pam_model_preview as owner

    return owner(*args, **kwargs)


def build_pamlod_model_preview(*args, **kwargs):
    from cdmw.core.model_preview import build_pamlod_model_preview as owner

    return owner(*args, **kwargs)


def ensure_model_preview_is_reasonable(*args, **kwargs):
    from cdmw.core.model_preview import ensure_model_preview_is_reasonable as owner

    return owner(*args, **kwargs)


def parse_archive_note_flags(note: str) -> set[str]:
    return {part.strip() for part in note.split(",") if part.strip()}


def summarize_obj_text(content: str) -> str:
    vertices = 0
    texcoords = 0
    normals = 0
    faces = 0
    for raw_line in content.splitlines():
        line = raw_line.lstrip()
        if line.startswith("v "):
            vertices += 1
        elif line.startswith("vt "):
            texcoords += 1
        elif line.startswith("vn "):
            normals += 1
        elif line.startswith("f "):
            faces += 1
    return f"OBJ summary: {vertices:,} vertices, {texcoords:,} UVs, {normals:,} normals, {faces:,} faces."


def _build_model_preview_summary_text(path: str, model_preview: ModelPreviewData) -> str:
    if getattr(model_preview, "format", "").lower() == "pamlod":
        lod_index = getattr(model_preview, "lod_index", -1)
        lod_count = getattr(model_preview, "lod_count", 0)
        lod_label = f"LOD {lod_index + 1}" if lod_index >= 0 else "LOD"
        if lod_count > 0 and lod_index >= 0:
            lod_label = f"{lod_label} of {lod_count}"
        return (
            f"{path}\n"
            f"{lod_label}\n"
            f"{model_preview.vertex_count:,} vertices\n"
            f"{model_preview.face_count:,} faces"
        )
    return (
        f"{path}\n"
        f"{model_preview.mesh_count:,} submesh(es)\n"
        f"{model_preview.vertex_count:,} vertices\n"
        f"{model_preview.face_count:,} faces"
    )


def _build_hkx_preview_context_from_related_references(
    references: Sequence[ArchiveModelTextureReference],
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[List[Mapping[str, object]], Dict[str, Mapping[str, object]], List[str]]:
    descriptor_hints: List[Mapping[str, object]] = []
    skeleton_bone_positions: Dict[str, Mapping[str, object]] = {}
    notes: List[str] = []
    seen_descriptor_paths: set[str] = set()
    seen_skeleton_paths: set[str] = set()

    def _finite_tuple3(value: object) -> Tuple[float, float, float]:
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return ()
        try:
            point = (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError, OverflowError):
            return ()
        return point if all(math.isfinite(component) for component in point) else ()

    def _bone_preview_position(bone: object) -> Tuple[Tuple[float, float, float], str]:
        matrix = tuple(getattr(bone, "bind_matrix", ()) or ())
        candidates: List[Tuple[float, Tuple[float, float, float], str]] = []
        if len(matrix) >= 16:
            for indexes, source in (((12, 13, 14), "bind_matrix_row_translation"), ((3, 7, 11), "bind_matrix_column_translation")):
                point = _finite_tuple3(tuple(matrix[index] for index in indexes))
                if point:
                    magnitude = math.sqrt((point[0] * point[0]) + (point[1] * point[1]) + (point[2] * point[2]))
                    if magnitude > 1e-6:
                        candidates.append((magnitude, point, source))
        if candidates:
            _magnitude, point, source = max(candidates, key=lambda item: item[0])
            return point, source
        point = _finite_tuple3(tuple(getattr(bone, "position", ()) or ()))
        return (point, "local_position") if point else ((), "")

    for reference in references:
        raise_if_cancelled(stop_event)
        resolved_entry = getattr(reference, "resolved_entry", None)
        resolved_extension = str(getattr(resolved_entry, "extension", "") or "").lower()
        if resolved_entry is None or resolved_extension not in _ARCHIVE_XML_LIKE_EXTENSIONS | {".xml"}:
            continue
        normalized_path = str(getattr(resolved_entry, "path", "") or "").replace("\\", "/").strip().lower()
        if not normalized_path or normalized_path in seen_descriptor_paths:
            continue
        if not any(token in normalized_path for token in ("physics", "attachment", "havok", "modelproperty", "material")):
            continue
        seen_descriptor_paths.add(normalized_path)
        try:
            descriptor_data, _decompressed, _note = read_archive_entry_data(resolved_entry, stop_event=stop_event)
            descriptor_text = descriptor_data.decode("utf-8", errors="ignore")
            descriptor_hint = build_hkx_descriptor_hint_from_xml_text(descriptor_text, resolved_entry.path)
            if descriptor_hint is not None:
                descriptor_hints.append(descriptor_hint)
        except RunCancelled:
            raise
        except Exception as exc:
            notes.append(f"HKX descriptor context skipped for {getattr(resolved_entry, 'path', 'unknown')}: {exc}")

    for reference in references:
        raise_if_cancelled(stop_event)
        resolved_entry = getattr(reference, "resolved_entry", None)
        if resolved_entry is None or str(getattr(resolved_entry, "extension", "") or "").lower() != ".pab":
            continue
        normalized_path = str(getattr(resolved_entry, "path", "") or "").replace("\\", "/").strip().lower()
        if not normalized_path or normalized_path in seen_skeleton_paths:
            continue
        seen_skeleton_paths.add(normalized_path)
        try:
            skeleton_data, _decompressed, _note = read_archive_entry_data(resolved_entry, stop_event=stop_event)
            skeleton = parse_pab(skeleton_data, resolved_entry.path)
            bones_by_index = {
                int(getattr(bone, "index", -1)): bone
                for bone in getattr(skeleton, "bones", []) or []
                if int(getattr(bone, "index", -1)) >= 0
            }
            loaded_count = 0
            for bone in getattr(skeleton, "bones", []) or []:
                bone_name = str(getattr(bone, "name", "") or "").strip()
                position, position_source = _bone_preview_position(bone)
                if not bone_name or len(position) < 3:
                    continue
                try:
                    parent_index = int(getattr(bone, "parent_index", -1))
                except (TypeError, ValueError, OverflowError):
                    parent_index = -1
                try:
                    bone_index = int(getattr(bone, "index", -1))
                except (TypeError, ValueError, OverflowError):
                    bone_index = -1
                parent_bone = bones_by_index.get(parent_index)
                skeleton_bone_positions[bone_name] = {
                    "name": bone_name,
                    "index": bone_index,
                    "parent_index": parent_index,
                    "parent_name": str(getattr(parent_bone, "name", "") or "") if parent_bone is not None else "",
                    "position": position,
                    "position_source": position_source,
                    "source_path": resolved_entry.path,
                }
                loaded_count += 1
            if loaded_count > 0:
                notes.append(f"HKX skeleton context loaded from {resolved_entry.path}: {loaded_count:,} bone(s).")
        except RunCancelled:
            raise
        except Exception as exc:
            notes.append(f"HKX skeleton context skipped for {getattr(resolved_entry, 'path', 'unknown')}: {exc}")
    return descriptor_hints, skeleton_bone_positions, notes


def _attach_hkx_physics_overlay_to_model_preview(
    model_preview: Optional[ModelPreviewData],
    references: Sequence[ArchiveModelTextureReference],
    *,
    stop_event: Optional[threading.Event] = None,
    max_hkx_files: int = 3,
) -> List[str]:
    if model_preview is None:
        return []
    overlays: List[Optional[HkxPhysicsOverlayData]] = []
    notes: List[str] = []
    seen_paths: set[str] = set()
    descriptor_hints: List[Mapping[str, object]] = []
    seen_descriptor_paths: set[str] = set()
    skeleton_bone_positions: Dict[str, Mapping[str, object]] = {}
    seen_skeleton_paths: set[str] = set()

    def _finite_tuple3(value: object) -> Tuple[float, float, float]:
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return ()
        try:
            point = (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError, OverflowError):
            return ()
        return point if all(math.isfinite(component) for component in point) else ()

    def _bone_preview_position(bone: object) -> Tuple[Tuple[float, float, float], str]:
        matrix = tuple(getattr(bone, "bind_matrix", ()) or ())
        candidates: List[Tuple[float, Tuple[float, float, float], str]] = []
        if len(matrix) >= 16:
            for indexes, source in (((12, 13, 14), "bind_matrix_row_translation"), ((3, 7, 11), "bind_matrix_column_translation")):
                point = _finite_tuple3(tuple(matrix[index] for index in indexes))
                if point:
                    magnitude = math.sqrt((point[0] * point[0]) + (point[1] * point[1]) + (point[2] * point[2]))
                    if magnitude > 1e-6:
                        candidates.append((magnitude, point, source))
        if candidates:
            _magnitude, point, source = max(candidates, key=lambda item: item[0])
            return point, source
        point = _finite_tuple3(tuple(getattr(bone, "position", ()) or ()))
        return (point, "local_position") if point else ((), "")

    def _overlay_match_tokens(path_text: object) -> set[str]:
        normalized = str(path_text or "").replace("\\", "/").casefold()
        stop_tokens = {
            "animation",
            "archive",
            "bin",
            "character",
            "cloth",
            "havok",
            "havokphysics",
            "hkx",
            "leveldata",
            "meshphysics",
            "model",
            "object",
            "pac",
            "pam",
            "pamlod",
            "pc",
            "physics",
            "phm",
            "phw",
        }
        return {
            token
            for token in re.findall(r"[a-z0-9]+", normalized)
            if len(token) >= 2 and token not in stop_tokens and token != "cd"
        }

    def _score_overlay_hkx_reference(reference: ArchiveModelTextureReference, order: int) -> Tuple[int, int, ArchiveModelTextureReference]:
        resolved_entry = getattr(reference, "resolved_entry", None)
        candidate_path = str(getattr(resolved_entry, "path", "") or getattr(reference, "resolved_archive_path", "") or "")
        source_path = str(getattr(model_preview, "path", "") or "")
        source_path_folded = source_path.replace("\\", "/").casefold()
        candidate_path_folded = candidate_path.replace("\\", "/").casefold()
        source_stem = PurePosixPath(source_path_folded).stem
        candidate_stem = PurePosixPath(candidate_path_folded).stem
        score = 0
        if source_stem and candidate_stem and source_stem == candidate_stem:
            score += 220
        elif source_stem and source_stem in candidate_path_folded:
            score += 150
        elif candidate_stem and candidate_stem in source_path_folded:
            score += 80
        shared_tokens = _overlay_match_tokens(source_path_folded) & _overlay_match_tokens(candidate_path_folded)
        important_tokens = {
            "shield",
            "sword",
            "weapon",
            "bow",
            "dagger",
            "axe",
            "mace",
            "staff",
            "cloak",
            "cape",
            "hair",
            "helmet",
        }
        for token in shared_tokens:
            score += 70 if token in important_tokens else 22
        return score, order, reference

    for reference in references:
        resolved_entry = getattr(reference, "resolved_entry", None)
        if resolved_entry is None or str(getattr(resolved_entry, "extension", "") or "").lower() not in {".xml", ".app_xml", ".pac_xml", ".prefabdata_xml"}:
            continue
        normalized_path = str(getattr(resolved_entry, "path", "") or "").replace("\\", "/").strip().lower()
        if not normalized_path or normalized_path in seen_descriptor_paths:
            continue
        if not any(
            token in normalized_path
            for token in ("physics", "attachment", "havok", "modelproperty", "material")
        ):
            continue
        seen_descriptor_paths.add(normalized_path)
        try:
            descriptor_data, _decompressed, _note = read_archive_entry_data(resolved_entry, stop_event=stop_event)
            descriptor_text = descriptor_data.decode("utf-8", errors="ignore")
            descriptor_hint = build_hkx_descriptor_hint_from_xml_text(descriptor_text, resolved_entry.path)
            if descriptor_hint is not None:
                descriptor_hints.append(descriptor_hint)
        except RunCancelled:
            raise
        except Exception as exc:
            notes.append(f"HKX descriptor context skipped for {getattr(resolved_entry, 'path', 'unknown')}: {exc}")
    for reference in references:
        resolved_entry = getattr(reference, "resolved_entry", None)
        if resolved_entry is None or str(getattr(resolved_entry, "extension", "") or "").lower() != ".pab":
            continue
        normalized_path = str(getattr(resolved_entry, "path", "") or "").replace("\\", "/").strip().lower()
        if not normalized_path or normalized_path in seen_skeleton_paths:
            continue
        seen_skeleton_paths.add(normalized_path)
        try:
            skeleton_data, _decompressed, _note = read_archive_entry_data(resolved_entry, stop_event=stop_event)
            skeleton = parse_pab(skeleton_data, resolved_entry.path)
            bones_by_index = {
                int(getattr(bone, "index", -1)): bone
                for bone in getattr(skeleton, "bones", []) or []
                if int(getattr(bone, "index", -1)) >= 0
            }
            for bone in getattr(skeleton, "bones", []) or []:
                bone_name = str(getattr(bone, "name", "") or "").strip()
                position, position_source = _bone_preview_position(bone)
                if not bone_name or len(position) < 3:
                    continue
                parent_index = int(getattr(bone, "parent_index", -1) or -1)
                parent_bone = bones_by_index.get(parent_index)
                skeleton_bone_positions[bone_name] = {
                    "name": bone_name,
                    "index": int(getattr(bone, "index", -1) or 0),
                    "parent_index": parent_index,
                    "parent_name": str(getattr(parent_bone, "name", "") or "") if parent_bone is not None else "",
                    "position": position,
                    "position_source": position_source,
                    "source_path": resolved_entry.path,
                }
        except RunCancelled:
            raise
        except Exception as exc:
            notes.append(f"HKX skeleton context skipped for {getattr(resolved_entry, 'path', 'unknown')}: {exc}")
    hkx_candidates: List[Tuple[int, int, ArchiveModelTextureReference]] = []
    for order, reference in enumerate(references):
        if stop_event is not None and stop_event.is_set():
            raise RunCancelled("HKX physics overlay preparation cancelled.")
        resolved_entry = getattr(reference, "resolved_entry", None)
        if resolved_entry is None or str(getattr(resolved_entry, "extension", "") or "").lower() not in {".hkx", ".hkt"}:
            continue
        normalized_path = str(getattr(resolved_entry, "path", "") or "").replace("\\", "/").strip().lower()
        if not normalized_path or normalized_path in seen_paths:
            continue
        hkx_candidates.append(_score_overlay_hkx_reference(reference, order))
    hkx_candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    if hkx_candidates:
        best_score = hkx_candidates[0][0]
        if best_score >= 50:
            threshold = max(45, best_score - 45)
            skipped = [
                candidate
                for candidate in hkx_candidates
                if candidate[0] < threshold
            ]
            hkx_candidates = [
                candidate
                for candidate in hkx_candidates
                if candidate[0] >= threshold
            ]
            if skipped:
                notes.append(
                    "Skipped lower-confidence HKX overlays that looked like broader character/rig context rather than the selected model."
                )
    for _score, _order, reference in hkx_candidates:
        if stop_event is not None and stop_event.is_set():
            raise RunCancelled("HKX physics overlay preparation cancelled.")
        resolved_entry = getattr(reference, "resolved_entry", None)
        if resolved_entry is None:
            continue
        normalized_path = str(getattr(resolved_entry, "path", "") or "").replace("\\", "/").strip().lower()
        if not normalized_path or normalized_path in seen_paths:
            continue
        seen_paths.add(normalized_path)
        try:
            hkx_data, _decompressed, _note = read_archive_entry_data(resolved_entry, stop_event=stop_event)
            hkx_document = build_hkx_editable_geometry_document(hkx_data, resolved_entry.path, descriptor_hints)
            overlay = build_hkx_physics_overlay_from_document(
                hkx_document,
                source_path=resolved_entry.path,
                normalization_center=tuple(getattr(model_preview, "normalization_center", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
                normalization_scale=float(getattr(model_preview, "normalization_scale", 1.0) or 1.0),
                skeleton_bone_positions=skeleton_bone_positions,
            )
            if overlay is not None:
                overlays.append(overlay)
                notes.append(f"HKX physics overlay loaded from {resolved_entry.path}: {len(overlay.shapes):,} decoded shape(s).")
        except RunCancelled:
            raise
        except Exception as exc:
            notes.append(f"HKX physics overlay skipped for {getattr(resolved_entry, 'path', 'unknown')}: {exc}")
        if len(overlays) >= max_hkx_files:
            break
    merged = merge_hkx_physics_overlays(overlays)
    if merged is not None:
        model_preview.physics_overlay = merged
        if len(seen_paths) > len(overlays):
            notes.append("Only the first compatible HKX physics overlays are drawn to keep preview rendering responsive.")
    return notes


def resolve_hkx_preview_context_model_entry(
    entry: ArchiveEntry,
    related_references: Sequence[ArchiveModelTextureReference],
) -> Optional[ArchiveEntry]:
    """Return the best read-only model context for an HKX/HKT preview."""

    if str(getattr(entry, "extension", "") or "").strip().lower() not in {".hkx", ".hkt"}:
        return None
    source_path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip()
    source_stem = PurePosixPath(source_path).stem.strip().casefold()
    source_parent = PurePosixPath(source_path).parent.as_posix().casefold()
    model_extensions = {".pac", ".pam", ".pamlod"}
    candidates: List[Tuple[int, int, ArchiveEntry]] = []
    seen: set[Tuple[str, str]] = set()

    for order, reference in enumerate(tuple(related_references or ())):
        resolved_entry = getattr(reference, "resolved_entry", None)
        if not isinstance(resolved_entry, ArchiveEntry):
            continue
        extension = str(getattr(resolved_entry, "extension", "") or "").strip().lower()
        if extension not in model_extensions:
            continue
        candidate_path = str(getattr(resolved_entry, "path", "") or "").replace("\\", "/").strip()
        candidate_stem = PurePosixPath(candidate_path).stem.strip().casefold()
        candidate_parent = PurePosixPath(candidate_path).parent.as_posix().casefold()
        key = (candidate_path.casefold(), str(getattr(resolved_entry, "pamt_path", "") or "").casefold())
        if not candidate_path or key in seen:
            continue
        seen.add(key)
        score = 0
        if source_stem and candidate_stem == source_stem:
            score += 1000
        elif source_stem and (source_stem in candidate_stem or source_stem in candidate_path.casefold()):
            score += 360
        if source_parent and candidate_parent and source_parent == candidate_parent:
            score += 120
        if getattr(resolved_entry, "pamt_path", None) == getattr(entry, "pamt_path", None):
            score += 80
        if getattr(resolved_entry, "pamt_path", None) is not None and getattr(entry, "pamt_path", None) is not None:
            try:
                if resolved_entry.pamt_path.parent == entry.pamt_path.parent:
                    score += 50
            except Exception:
                pass
        if str(getattr(reference, "semantic_hint", "") or "").strip().lower() == "same_stem_companion":
            score += 70
        if str(getattr(reference, "relation_confidence", "") or "").strip().lower() in {
            RelationConfidence.AUTHORITATIVE.value,
            RelationConfidence.EXACT_PATH.value,
            RelationConfidence.PATH_NORMALIZED.value,
            RelationConfidence.DERIVED_SAME_STEM.value,
        }:
            score += 40
        score += {".pac": 30, ".pam": 20, ".pamlod": 10}.get(extension, 0)
        candidates.append((score, -order, resolved_entry))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _path_mtime_fingerprint(path: object) -> Tuple[str, int, int]:
    try:
        resolved = Path(path)
    except (TypeError, ValueError, OSError):
        return (str(path or ""), 0, 0)
    try:
        stat = resolved.stat()
    except OSError:
        return (str(resolved), 0, 0)
    return (str(resolved), int(getattr(stat, "st_mtime_ns", 0) or 0), int(getattr(stat, "st_size", 0) or 0))


def _hkx_context_model_preview_cache_key(
    entry: ArchiveEntry,
    *,
    visible_texture_mode: object,
    support_texture_slots: Sequence[str],
    quality_tier: str,
) -> str:
    payload = {
        "path": str(getattr(entry, "path", "") or "").replace("\\", "/").casefold(),
        "pamt": _path_mtime_fingerprint(getattr(entry, "pamt_path", "")),
        "paz": _path_mtime_fingerprint(getattr(entry, "paz_file", "")),
        "offset": int(getattr(entry, "offset", 0) or 0),
        "comp_size": int(getattr(entry, "comp_size", 0) or 0),
        "orig_size": int(getattr(entry, "orig_size", 0) or 0),
        "flags": int(getattr(entry, "flags", 0) or 0),
        "paz_index": int(getattr(entry, "paz_index", 0) or 0),
        "visible_texture_mode": str(visible_texture_mode or ""),
        "support_texture_slots": tuple(sorted(str(slot or "").strip().lower() for slot in tuple(support_texture_slots or ()) if str(slot or "").strip())),
        "quality_tier": _normalize_archive_preview_quality_tier(quality_tier),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def _clone_hkx_context_model_preview(model_preview: ModelPreviewData) -> ModelPreviewData:
    meshes: List[ModelPreviewMesh] = []
    for mesh in tuple(getattr(model_preview, "meshes", ()) or ()):
        if not isinstance(mesh, ModelPreviewMesh):
            continue
        mesh_values = {field_info.name: getattr(mesh, field_info.name) for field_info in fields(ModelPreviewMesh)}
        mesh_values["positions"] = list(getattr(mesh, "positions", ()) or ())
        mesh_values["texture_coordinates"] = list(getattr(mesh, "texture_coordinates", ()) or ())
        mesh_values["normals"] = list(getattr(mesh, "normals", ()) or ())
        mesh_values["indices"] = list(getattr(mesh, "indices", ()) or ())
        mesh_values["source_vertex_indices"] = list(getattr(mesh, "source_vertex_indices", ()) or ())
        mesh_values["source_face_indices"] = list(getattr(mesh, "source_face_indices", ()) or ())
        meshes.append(ModelPreviewMesh(**mesh_values))
    values = {field_info.name: getattr(model_preview, field_info.name) for field_info in fields(ModelPreviewData)}
    values["meshes"] = meshes
    values["physics_overlay"] = None
    return ModelPreviewData(**values)


def _get_hkx_context_model_preview_cache(cache_key: str) -> Optional[ModelPreviewData]:
    key = str(cache_key or "").strip()
    if not key:
        return None
    cached = _HKX_CONTEXT_MODEL_PREVIEW_CACHE.get(key)
    if not isinstance(cached, ModelPreviewData):
        return None
    _HKX_CONTEXT_MODEL_PREVIEW_CACHE.move_to_end(key)
    return _clone_hkx_context_model_preview(cached)


def _remember_hkx_context_model_preview_cache(cache_key: str, model_preview: ModelPreviewData) -> None:
    key = str(cache_key or "").strip()
    if not key or not isinstance(model_preview, ModelPreviewData):
        return
    _HKX_CONTEXT_MODEL_PREVIEW_CACHE[key] = _clone_hkx_context_model_preview(model_preview)
    _HKX_CONTEXT_MODEL_PREVIEW_CACHE.move_to_end(key)
    while len(_HKX_CONTEXT_MODEL_PREVIEW_CACHE) > _HKX_CONTEXT_MODEL_PREVIEW_CACHE_LIMIT:
        _HKX_CONTEXT_MODEL_PREVIEW_CACHE.popitem(last=False)


def _clear_hkx_context_model_preview_cache() -> None:
    _HKX_CONTEXT_MODEL_PREVIEW_CACHE.clear()


def _retarget_model_preview(model_preview: ModelPreviewData, path: str) -> None:
    model_preview.path = path
    model_preview.summary = _build_model_preview_summary_text(path, model_preview)


def _inspect_pam_declared_geometry(data: bytes) -> Tuple[int, int]:
    if len(data) < 64 or data[:4] != b"PAR ":
        return 0, 0
    mesh_count = struct.unpack_from("<I", data, 16)[0]
    declared_index_count = 0
    for index in range(mesh_count):
        entry_offset = 1040 + index * 536
        if entry_offset + 8 > len(data):
            break
        declared_index_count += struct.unpack_from("<I", data, entry_offset + 4)[0]
    return mesh_count, declared_index_count


def _pam_preview_looks_incomplete(data: bytes, model_preview: ModelPreviewData) -> bool:
    declared_mesh_count, declared_index_count = _inspect_pam_declared_geometry(data)
    if declared_mesh_count > 0 and model_preview.mesh_count < declared_mesh_count:
        return True
    if declared_index_count > 0 and (model_preview.face_count * 3) < int(declared_index_count * 0.85):
        return True
    return False


def _normalize_archive_preview_quality_tier(value: object) -> str:
    return "fast" if str(value or "").strip().lower() == "fast" else "full"


def _archive_preview_fast_lod_index() -> int:
    return -1


def _reduce_archive_preview_model_geometry(
    model_preview: ModelPreviewData,
    *,
    max_faces: int = _FAST_ARCHIVE_PREVIEW_MAX_FACES,
) -> ModelPreviewData:
    face_count = int(getattr(model_preview, "face_count", 0) or 0)
    if face_count <= max_faces or max_faces <= 0:
        return model_preview
    ratio = max_faces / max(1, face_count)
    reduced_meshes: List[ModelPreviewMesh] = []
    for mesh in tuple(getattr(model_preview, "meshes", ()) or ()):
        if not isinstance(mesh, ModelPreviewMesh):
            reduced_meshes.append(mesh)
            continue
        indices = list(getattr(mesh, "indices", ()) or ())
        mesh_face_count = len(indices) // 3
        if mesh_face_count <= 0:
            reduced_meshes.append(mesh)
            continue
        target_faces = max(1, int(mesh_face_count * ratio))
        step = max(1, math.ceil(mesh_face_count / target_faces))
        selected_triangles: List[Tuple[int, int, int]] = []
        selected_source_faces: List[int] = []
        raw_source_faces = list(getattr(mesh, "source_face_indices", ()) or ())
        for face_index in range(0, mesh_face_count, step):
            base = face_index * 3
            if base + 2 >= len(indices):
                continue
            selected_triangles.append((indices[base], indices[base + 1], indices[base + 2]))
            selected_source_faces.append(
                int(raw_source_faces[face_index]) if face_index < len(raw_source_faces) else int(face_index)
            )
            if len(selected_triangles) >= target_faces:
                break
        used_indices: List[int] = []
        seen_indices: set[int] = set()
        position_count = len(getattr(mesh, "positions", ()) or ())
        for triangle in selected_triangles:
            for vertex_index in triangle:
                if vertex_index < 0 or vertex_index >= position_count or vertex_index in seen_indices:
                    continue
                seen_indices.add(vertex_index)
                used_indices.append(vertex_index)
        if len(used_indices) < 3:
            reduced_meshes.append(mesh)
            continue
        index_map = {old_index: new_index for new_index, old_index in enumerate(used_indices)}
        reduced_indices: List[int] = []
        for triangle in selected_triangles:
            if all(vertex_index in index_map for vertex_index in triangle):
                reduced_indices.extend(index_map[vertex_index] for vertex_index in triangle)
        if len(reduced_indices) < 3:
            reduced_meshes.append(mesh)
            continue

        def remap(values: Sequence[object]) -> list[object]:
            return [values[index] for index in used_indices] if len(values) == position_count else list(values)

        mesh_values = {field_info.name: getattr(mesh, field_info.name) for field_info in fields(ModelPreviewMesh)}
        mesh_values["positions"] = remap(getattr(mesh, "positions", ()) or ())
        mesh_values["texture_coordinates"] = remap(getattr(mesh, "texture_coordinates", ()) or ())
        mesh_values["normals"] = remap(getattr(mesh, "normals", ()) or ())
        mesh_values["source_vertex_indices"] = remap(getattr(mesh, "source_vertex_indices", ()) or ())
        mesh_values["source_face_indices"] = selected_source_faces[: len(reduced_indices) // 3]
        mesh_values["indices"] = reduced_indices
        reduced_meshes.append(ModelPreviewMesh(**mesh_values))

    reduced_face_count = sum(len(getattr(mesh, "indices", ()) or ()) // 3 for mesh in reduced_meshes)
    reduced_vertex_count = sum(len(getattr(mesh, "positions", ()) or ()) for mesh in reduced_meshes)
    summary = str(getattr(model_preview, "summary", "") or "")
    if summary:
        summary = f"{summary}\nFast preview: {reduced_face_count:,} sampled faces shown while full preview builds."
    else:
        summary = f"Fast preview: {reduced_face_count:,} sampled faces shown while full preview builds."
    return ModelPreviewData(
        **{
            field_info.name: (
                reduced_meshes
                if field_info.name == "meshes"
                else reduced_vertex_count
                if field_info.name == "vertex_count"
                else reduced_face_count
                if field_info.name == "face_count"
                else summary
                if field_info.name == "summary"
                else getattr(model_preview, field_info.name)
            )
            for field_info in fields(ModelPreviewData)
        }
    )


def _build_pam_model_preview_with_fallback(
    entry: ArchiveEntry,
    data: bytes,
    note_flags: set[str],
    *,
    companion_entry: Optional[ArchiveEntry] = None,
    quality_tier: str = "full",
    stop_event: Optional[threading.Event] = None,
) -> Tuple[ModelPreviewData, List[str]]:
    normalized_quality_tier = _normalize_archive_preview_quality_tier(quality_tier)
    info_extra_parts: List[str] = []
    recovery_errors: List[str] = []
    raw_model_preview: Optional[ModelPreviewData] = None
    skip_padded_recovery = False

    try:
        candidate_raw_model_preview = build_pam_model_preview(entry, data, stop_event=stop_event)
        ensure_model_preview_is_reasonable(candidate_raw_model_preview, stop_event=stop_event)
        raw_model_preview = candidate_raw_model_preview
        if (
            "PartialRaw" in note_flags
            and companion_entry is not None
            and _pam_preview_looks_incomplete(data, raw_model_preview)
        ):
            info_extra_parts.append(
                "Stored PAM geometry recovery looks incomplete for this Partial entry; a companion PAMLOD preview will be preferred when available."
            )
        else:
            if normalized_quality_tier == "fast":
                raw_model_preview = _reduce_archive_preview_model_geometry(raw_model_preview)
                info_extra_parts.append("Fast preview uses sampled PAM geometry while the full preview builds.")
            return raw_model_preview, info_extra_parts
    except RunCancelled:
        raise
    except Exception as exc:
        raw_error_text = str(exc)
        recovery_errors.append(f"Stored PAM geometry recovery failed: {raw_error_text}")
        if "suppressed" in raw_error_text.lower() or "scrambled" in raw_error_text.lower():
            skip_padded_recovery = True

    if companion_entry is not None:
        try:
            companion_data, _companion_decompressed, companion_note = read_archive_entry_data(
                companion_entry,
                stop_event=stop_event,
            )
            model_preview = build_pamlod_model_preview(
                companion_entry,
                companion_data,
                lod_index=_archive_preview_fast_lod_index() if normalized_quality_tier == "fast" else None,
                stop_event=stop_event,
            )
            ensure_model_preview_is_reasonable(model_preview, stop_event=stop_event)
            _retarget_model_preview(model_preview, entry.path)
            info_extra_parts.append(
                f"Visual model preview uses companion {companion_entry.basename} geometry because the selected PAM payload did not yield a complete renderable mesh preview."
            )
            companion_note_flags = parse_archive_note_flags(companion_note)
            if "ChaCha20" in companion_note_flags:
                info_extra_parts.append("Companion PAMLOD geometry was decrypted via deterministic ChaCha20 filename derivation.")
            if normalized_quality_tier == "fast" and getattr(model_preview, "lod_count", 0) > 1:
                info_extra_parts.append("Fast preview uses a lower-detail companion PAMLOD level while the full preview builds.")
            return model_preview, info_extra_parts
        except RunCancelled:
            raise
        except Exception as exc:
            recovery_errors.append(f"Companion PAMLOD recovery failed: {exc}")

    if "PartialRaw" in note_flags and len(data) < entry.orig_size and not skip_padded_recovery:
        try:
            padded_data = data + (b"\x00" * (entry.orig_size - len(data)))
            model_preview = build_pam_model_preview(entry, padded_data, stop_event=stop_event)
            ensure_model_preview_is_reasonable(model_preview, stop_event=stop_event)
            if normalized_quality_tier == "fast":
                model_preview = _reduce_archive_preview_model_geometry(model_preview)
                info_extra_parts.append("Fast preview uses sampled PAM geometry while the full preview builds.")
            info_extra_parts.append(
                "Visual model preview uses zero-padded Partial reconstruction because the stored PAM payload is incomplete."
            )
            return model_preview, info_extra_parts
        except RunCancelled:
            raise
        except Exception as exc:
            recovery_errors.append(f"Zero-padded Partial reconstruction failed: {exc}")

    if raw_model_preview is not None:
        info_extra_parts.append(
            "Stored PAM geometry preview is being shown even though the recovered mesh set appears incomplete."
        )
        if normalized_quality_tier == "fast":
            raw_model_preview = _reduce_archive_preview_model_geometry(raw_model_preview)
            info_extra_parts.append("Fast preview uses sampled PAM geometry while the full preview builds.")
        return raw_model_preview, info_extra_parts

    if "PartialRaw" in note_flags and len(data) < entry.orig_size:
        recovery_errors.append("Stored Partial payload appears truncated beyond the geometry data needed for preview.")
    raise ValueError("; ".join(recovery_errors) if recovery_errors else "PAM geometry could not be recovered.")


def _build_pamlod_model_preview_with_fallback(
    entry: ArchiveEntry,
    data: bytes,
    note_flags: set[str],
    *,
    companion_entry: Optional[ArchiveEntry] = None,
    quality_tier: str = "full",
    stop_event: Optional[threading.Event] = None,
) -> Tuple[ModelPreviewData, List[str]]:
    normalized_quality_tier = _normalize_archive_preview_quality_tier(quality_tier)
    info_extra_parts: List[str] = []
    recovery_errors: List[str] = []

    try:
        model_preview = build_pamlod_model_preview(
            entry,
            data,
            lod_index=_archive_preview_fast_lod_index() if normalized_quality_tier == "fast" else None,
            stop_event=stop_event,
        )
        ensure_model_preview_is_reasonable(model_preview, stop_event=stop_event)
        if normalized_quality_tier == "fast" and getattr(model_preview, "lod_count", 0) > 1:
            info_extra_parts.append("Fast preview uses a lower-detail PAMLOD level while the full preview builds.")
        return model_preview, info_extra_parts
    except RunCancelled:
        raise
    except Exception as exc:
        recovery_errors.append(f"Stored PAMLOD geometry recovery failed: {exc}")

    if companion_entry is not None:
        try:
            companion_data, _companion_decompressed, companion_note = read_archive_entry_data(
                companion_entry,
                stop_event=stop_event,
            )
            model_preview = build_pam_model_preview(companion_entry, companion_data, stop_event=stop_event)
            ensure_model_preview_is_reasonable(model_preview, stop_event=stop_event)
            if normalized_quality_tier == "fast":
                model_preview = _reduce_archive_preview_model_geometry(model_preview)
                info_extra_parts.append("Fast preview uses sampled companion PAM geometry while the full preview builds.")
            _retarget_model_preview(model_preview, entry.path)
            info_extra_parts.append(
                f"Visual model preview uses companion {companion_entry.basename} geometry because the selected PAMLOD payload did not yield a complete renderable LOD preview."
            )
            companion_note_flags = parse_archive_note_flags(companion_note)
            if "ChaCha20" in companion_note_flags:
                info_extra_parts.append("Companion PAM geometry was decrypted via deterministic ChaCha20 filename derivation.")
            return model_preview, info_extra_parts
        except RunCancelled:
            raise
        except Exception as exc:
            recovery_errors.append(f"Companion PAM recovery failed: {exc}")

    if "PartialRaw" in note_flags and len(data) < entry.orig_size:
        try:
            padded_data = data + (b"\x00" * (entry.orig_size - len(data)))
            model_preview = build_pamlod_model_preview(
                entry,
                padded_data,
                lod_index=_archive_preview_fast_lod_index() if normalized_quality_tier == "fast" else None,
                stop_event=stop_event,
            )
            ensure_model_preview_is_reasonable(model_preview, stop_event=stop_event)
            if normalized_quality_tier == "fast" and getattr(model_preview, "lod_count", 0) > 1:
                info_extra_parts.append("Fast preview uses a lower-detail PAMLOD level while the full preview builds.")
            info_extra_parts.append(
                "Visual model preview uses zero-padded Partial reconstruction because the stored PAMLOD payload is incomplete."
            )
            return model_preview, info_extra_parts
        except RunCancelled:
            raise
        except Exception as exc:
            recovery_errors.append(f"Zero-padded PAMLOD reconstruction failed: {exc}")
        recovery_errors.append("Stored Partial payload appears truncated beyond the geometry data needed for preview.")

    raise ValueError("; ".join(recovery_errors) if recovery_errors else "PAMLOD geometry could not be recovered.")


def _build_pac_model_preview_with_fallback(
    entry: ArchiveEntry,
    data: bytes,
    note_flags: set[str],
    *,
    quality_tier: str = "full",
    stop_event: Optional[threading.Event] = None,
) -> Tuple[ModelPreviewData, ParsedMesh, List[str]]:
    normalized_quality_tier = _normalize_archive_preview_quality_tier(quality_tier)
    info_extra_parts: List[str] = []
    recovery_errors: List[str] = []

    try:
        model_preview, parsed_mesh = build_mesh_preview_from_bytes(data, entry.path)
        if normalized_quality_tier == "fast":
            model_preview = _reduce_archive_preview_model_geometry(model_preview)
            info_extra_parts.append("Fast preview uses sampled PAC geometry while the full preview builds.")
        return model_preview, parsed_mesh, info_extra_parts
    except RunCancelled:
        raise
    except Exception as exc:
        recovery_errors.append(f"Stored PAC geometry recovery failed: {exc}")

    if "PartialRaw" in note_flags and len(data) < entry.orig_size:
        try:
            padded_data = data + (b"\x00" * (entry.orig_size - len(data)))
            model_preview, parsed_mesh = build_mesh_preview_from_bytes(padded_data, entry.path)
            if normalized_quality_tier == "fast":
                model_preview = _reduce_archive_preview_model_geometry(model_preview)
                info_extra_parts.append("Fast preview uses sampled PAC geometry while the full preview builds.")
            info_extra_parts.append(
                "Visual model preview uses zero-padded Partial reconstruction because the stored PAC payload is incomplete."
            )
            return model_preview, parsed_mesh, info_extra_parts
        except RunCancelled:
            raise
        except Exception as exc:
            recovery_errors.append(f"Zero-padded PAC reconstruction failed: {exc}")
        recovery_errors.append("Stored Partial payload appears truncated beyond the geometry data needed for preview.")

    raise ValueError("; ".join(recovery_errors) if recovery_errors else "PAC geometry could not be recovered.")
