from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.core.archive_mesh_types import MeshImportSupplementalFileSpec
from cdmw.core.temp_cache import app_temp_cache_path, request_app_temp_cache_prune
from cdmw.models import (
    ArchiveEntry,
    ModelPreviewData,
    ModelPreviewMesh,
)
from cdmw.modding.material_replacer import TextureReplacementPayload

from cdmw.core.archive_mesh_import_supplemental import _find_first_archive_entry_by_virtual_path

def _texture_replacement_payloads_to_specs(
    payloads: Sequence[TextureReplacementPayload],
    *,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]],
) -> Tuple[MeshImportSupplementalFileSpec, ...]:
    specs: List[MeshImportSupplementalFileSpec] = []
    for payload in payloads:
        target_entry = _find_first_archive_entry_by_virtual_path(
            payload.target_path,
            archive_entries_by_normalized_path,
        )
        specs.append(
            MeshImportSupplementalFileSpec(
                source_path=payload.source_path,
                target_path=payload.target_path,
                kind=payload.kind,
                target_entry=target_entry,
                used_for_preview=True,
                payload_data=payload.payload_data,
                note=payload.note,
            )
        )
    return tuple(specs)

def _generated_texture_preview_file(payload: TextureReplacementPayload) -> Path:
    digest = hashlib.sha1(payload.payload_data).hexdigest()[:16]
    target_name = PurePosixPath(str(payload.target_path or "").replace("\\", "/")).name
    if not target_name:
        target_name = payload.source_path.with_suffix(".dds").name
    if not target_name.lower().endswith(".dds"):
        target_name = f"{Path(target_name).stem}.dds"
    output_dir = app_temp_cache_path("static_mesh_texture_previews")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{Path(target_name).stem}_{digest}.dds"
    if not output_path.is_file():
        atomic_write_bytes(output_path, payload.payload_data)
        request_app_temp_cache_prune()
    return output_path

def _generated_texture_tokens(value: str) -> set[str]:
    stop = {"cd", "phm", "pc", "texture", "textures", "dds", "png", "normal", "base", "color", "roughness", "metallic"}
    tokens = {re.sub(r"\d+$", "", token) for token in re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split()}
    return {token for token in tokens if len(token) > 1 and token not in stop and not token.isdigit()}


def _generated_mesh_match_score(mesh: ModelPreviewMesh, material_name: str, texture_path: str) -> float:
    mesh_material = str(getattr(mesh, "material_name", "") or "")
    if material_name.strip() and mesh_material.strip().lower() == material_name.strip().lower():
        return 100.0
    query = _generated_texture_tokens(f"{material_name} {texture_path}")
    mesh_tokens = _generated_texture_tokens(f"{mesh_material} {getattr(mesh, 'name', '')}")
    if not query or not mesh_tokens:
        return 0.0
    overlap = query & mesh_tokens
    score = float(len(overlap) * 12) + sum(min(6.0, len(token) * 0.75) for token in overlap)
    score += sum(3.0 for left in query for right in mesh_tokens if len(left) >= 4 and len(right) >= 4 and (left in right or right in left))
    return score


def _generated_candidate_meshes(model: ModelPreviewData, material_name: str, texture_path: str) -> List[ModelPreviewMesh]:
    scored = [(_generated_mesh_match_score(mesh, material_name, texture_path), mesh) for mesh in model.meshes]
    best = max((score for score, _mesh in scored), default=0.0)
    if best > 0.0:
        return [mesh for score, mesh in scored if score == best]
    return list(model.meshes) if len(model.meshes) == 1 else []


def _generated_payload_preview_path(payload: TextureReplacementPayload, texconv: Optional[Path], cache: Dict[str, str]) -> str:
    from cdmw.core.texture_pipeline.inspection import parse_dds
    from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
    path = _generated_texture_preview_file(payload)
    key = path.as_posix().lower()
    if key not in cache:
        try:
            info = parse_dds(path)
        except (OSError, ValueError):
            info = None
        cache[key] = ensure_dds_display_preview_png(texconv, path, dds_info=info)
    return cache[key]


def _assign_generated_texture_slot(mesh: ModelPreviewMesh, slot: str, preview_path: str, source_name: str, *, only_missing: bool = False) -> int:
    from cdmw.core.archive_model_textures import _resolve_model_texture_semantic_details
    attrs = {"base": "preview_texture_path", "normal": "preview_normal_texture_path", "height": "preview_height_texture_path", "material": "preview_material_texture_path"}
    normalized_slot = "material" if slot in {"material", "material_mask", "detail_mask"} else slot
    if normalized_slot not in attrs or (only_missing and str(getattr(mesh, attrs[normalized_slot], "") or "").strip()):
        return 0
    if normalized_slot == "base":
        mesh.preview_texture_path = preview_path; mesh.texture_name = source_name; mesh.preview_texture_flip_vertical = False
    elif normalized_slot == "normal":
        mesh.preview_normal_texture_path = preview_path; mesh.preview_normal_texture_name = source_name; mesh.preview_normal_texture_strength = 0.75
    elif normalized_slot == "height":
        mesh.preview_height_texture_path = preview_path; mesh.preview_height_texture_name = source_name
    else:
        semantic_type, subtype, _confidence, channels = _resolve_model_texture_semantic_details(source_name)
        mesh.preview_material_texture_path = preview_path; mesh.preview_material_texture_name = source_name
        mesh.preview_material_texture_type = semantic_type; mesh.preview_material_texture_subtype = subtype
        mesh.preview_material_texture_packed_channels = tuple(channels)
    return 1


def _apply_generated_mapping_pass(
    model: ModelPreviewData, mappings: Sequence[object], payloads: Mapping[str, TextureReplacementPayload],
    texconv: Optional[Path], cache: Dict[str, str], source_by_target: Dict[str, str], base_targets: set[str],
) -> int:
    assigned = 0
    for mapping in mappings:
        target_path = str(getattr(mapping, "output_texture_path", "") or "").replace("\\", "/").strip().lower()
        payload = payloads.get(target_path)
        if payload is None:
            continue
        target_material = str(getattr(mapping, "target_material_name", "") or "")
        source_material = str(getattr(mapping, "source_material_name", "") or "")
        if target_material and source_material:
            source_by_target.setdefault(target_material.strip().lower(), source_material)
        try:
            preview = _generated_payload_preview_path(payload, texconv, cache)
        except (OSError, RuntimeError, ValueError):
            continue
        slot = str(getattr(mapping, "slot_kind", "") or "").strip().lower()
        if slot == "base" and target_material:
            base_targets.add(target_material.strip().lower())
        source_name = getattr(getattr(mapping, "source_path", None), "name", "") or PurePosixPath(payload.target_path).name
        for mesh in _generated_candidate_meshes(model, target_material, str(getattr(mapping, "target_texture_path", "") or "")):
            assigned += _assign_generated_texture_slot(mesh, slot, preview, source_name)
    return assigned


def _apply_generated_missing_pass(model: ModelPreviewData, mappings: Sequence[object], payloads: Mapping[str, TextureReplacementPayload], texconv: Optional[Path], cache: Dict[str, str]) -> int:
    assigned = 0
    for mapping in mappings:
        payload = payloads.get(str(getattr(mapping, "output_texture_path", "") or "").replace("\\", "/").strip().lower())
        if payload is None:
            continue
        try:
            preview = _generated_payload_preview_path(payload, texconv, cache)
        except (OSError, RuntimeError, ValueError):
            continue
        target = str(getattr(mapping, "target_material_name", "") or "")
        target_tokens = _generated_texture_tokens(target)
        slot = str(getattr(mapping, "slot_kind", "") or "").strip().lower()
        source_name = getattr(getattr(mapping, "source_path", None), "name", "") or PurePosixPath(payload.target_path).name
        for mesh in model.meshes:
            mesh_tokens = _generated_texture_tokens(f"{getattr(mesh, 'material_name', '')} {getattr(mesh, 'name', '')}")
            if target_tokens and mesh_tokens and not target_tokens.intersection(mesh_tokens):
                continue
            assigned += _assign_generated_texture_slot(mesh, slot, preview, source_name, only_missing=True)
    return assigned


def _apply_source_base_fallbacks(model: ModelPreviewData, report: object, source_by_target: Mapping[str, str], base_targets: set[str]) -> int:
    sets = {str(getattr(item, "material_name", "") or "").strip().lower(): item for item in (getattr(report, "texture_sets", ()) or ())}
    assigned = 0
    for target, source_material in source_by_target.items():
        if target in base_targets:
            continue
        texture_set = sets.get(str(source_material or "").strip().lower())
        base_slot = getattr(texture_set, "slots", {}).get("base") if texture_set is not None else None
        source_path = getattr(base_slot, "source_path", None)
        if not isinstance(source_path, Path) or not source_path.is_file():
            continue
        for mesh in _generated_candidate_meshes(model, target, ""):
            mesh.preview_texture_path = source_path.as_posix(); mesh.texture_name = source_path.name
            mesh.preview_texture_flip_vertical = False; assigned += 1
    return assigned


def _apply_generated_static_texture_previews(
    preview_model: ModelPreviewData,
    *,
    generated_payloads: Sequence[TextureReplacementPayload],
    texture_replacement_report: object,
    texconv_path: Optional[Path],
) -> int:
    if not preview_model.meshes:
        return 0
    payloads = {str(payload.target_path or "").replace("\\", "/").strip().lower(): payload for payload in generated_payloads if payload.kind == "texture_generated" and payload.payload_data}
    if not payloads:
        return 0
    texconv = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
    mappings = list(getattr(texture_replacement_report, "slot_mappings", ()) or ())
    cache: Dict[str, str] = {}; source_by_target: Dict[str, str] = {}; base_targets: set[str] = set()
    assigned = _apply_generated_mapping_pass(preview_model, mappings, payloads, texconv, cache, source_by_target, base_targets)
    assigned += _apply_generated_missing_pass(preview_model, mappings, payloads, texconv, cache)
    assigned += _apply_source_base_fallbacks(preview_model, texture_replacement_report, source_by_target, base_targets)
    return assigned
