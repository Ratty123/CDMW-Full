from __future__ import annotations

import fnmatch
import re
from pathlib import PurePosixPath
from typing import (
    List,
    Optional,
    Sequence,
    Tuple,
)

from cdmw.models import (
    ArchiveEntry,
    ModelPreviewMesh,
    PreviewMaterialTextureInput,
)
from cdmw.core.archive_filtering import _COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS
from cdmw.core.archive_model_references import (
    _ArchiveModelSidecarTextureBinding,
    _iter_archive_attachment_side_family_stems,
    _iter_archive_prefab_equipment_family_stems,
    _normalize_model_submesh_reference,
    _normalize_model_texture_reference,
    _strip_archive_model_family_variant_suffix,
    iter_archive_character_equipment_root_alias_stems,
    iter_archive_equipment_model_alias_stems,
)
from cdmw.core.upscale_profiles import infer_texture_semantics

from cdmw.core.archive_model_texture_config import MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES, MODEL_TEXTURE_VISIBLE_FAMILY_SUFFIXES

_MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES = MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES
_MODEL_TEXTURE_VISIBLE_FAMILY_SUFFIXES = MODEL_TEXTURE_VISIBLE_FAMILY_SUFFIXES

def _iter_parsed_model_submeshes(parsed_mesh: Optional[object]) -> List[object]:
    if parsed_mesh is None:
        return []
    if str(getattr(parsed_mesh, "format", "") or "").strip().lower() == "pamlod":
        lod_levels = getattr(parsed_mesh, "lod_levels", None) or [[]]
        return list(lod_levels[0] or [])
    return list(getattr(parsed_mesh, "submeshes", ()) or [])

def _iter_model_submesh_reference_candidates(*values: str) -> Tuple[str, ...]:
    ordered_candidates: List[str] = []
    seen: set[str] = set()

    def add_candidate(raw_value: str) -> None:
        normalized = _normalize_model_submesh_reference(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered_candidates.append(normalized)

    for raw_value in values:
        raw_text = str(raw_value or "").strip()
        if not raw_text:
            continue
        add_candidate(raw_text)
        pure_path = PurePosixPath(raw_text.replace("\\", "/"))
        basename = pure_path.name
        stem = pure_path.stem
        if basename and basename != raw_text:
            add_candidate(basename)
        if stem and stem not in {raw_text, basename}:
            add_candidate(stem)
    return tuple(ordered_candidates)

def _iter_model_sidecar_binding_submesh_keys(binding: _ArchiveModelSidecarTextureBinding) -> Tuple[str, ...]:
    values: List[str] = [
        str(getattr(binding, "submesh_name", "") or ""),
        str(getattr(binding, "part_name", "") or ""),
        str(getattr(binding, "material_name", "") or ""),
    ]
    explicit_keys = _iter_model_submesh_reference_candidates(*values)
    if explicit_keys:
        return explicit_keys
    linked_mesh_path = str(getattr(binding, "linked_mesh_path", "") or "").replace("\\", "/").strip()
    if linked_mesh_path:
        linked_mesh = PurePosixPath(linked_mesh_path)
        values.extend([linked_mesh_path, linked_mesh.name, linked_mesh.stem])
    return _iter_model_submesh_reference_candidates(*values)

def _archive_model_component_alias_stems(path: str) -> set[str]:
    normalized = _normalize_model_texture_reference(path)
    if not normalized:
        return set()
    stem = PurePosixPath(normalized).stem.strip().lower()
    if not stem:
        return set()
    stems: set[str] = {stem}
    stripped = _strip_archive_model_family_variant_suffix(stem)
    if stripped:
        stems.add(stripped)
    for alias in _iter_archive_attachment_side_family_stems(stem):
        stems.add(alias)
    for alias in _iter_archive_prefab_equipment_family_stems(stem):
        stems.add(alias)
    for alias in iter_archive_equipment_model_alias_stems(stem):
        stems.add(alias)
    for alias in iter_archive_character_equipment_root_alias_stems(stem):
        stems.add(alias)
    return {value for value in stems if value}

def _sidecar_binding_linked_model_path(binding: _ArchiveModelSidecarTextureBinding) -> str:
    linked_mesh_path = _normalize_model_texture_reference(str(getattr(binding, "linked_mesh_path", "") or ""))
    if linked_mesh_path:
        return linked_mesh_path
    sidecar_path = str(getattr(binding, "sidecar_path", "") or "").replace("\\", "/").strip()
    if not sidecar_path:
        return ""
    lowered = sidecar_path.lower()
    sidecar_kind = str(getattr(binding, "sidecar_kind", "") or "").strip().lower()
    if (sidecar_kind == "pac_xml" or lowered.endswith(".pac_xml")) and lowered.endswith(".pac_xml"):
        return _normalize_model_texture_reference(sidecar_path[: -len(".pac_xml")] + ".pac").replace(
            "/modelproperty/",
            "/model/",
        )
    if (sidecar_kind == "pam_xml" or lowered.endswith(".pam_xml")) and lowered.endswith(".pam_xml"):
        return _normalize_model_texture_reference(sidecar_path[: -len(".pam_xml")] + ".pam")
    if (sidecar_kind == "pamlod_xml" or lowered.endswith(".pamlod_xml")) and lowered.endswith(".pamlod_xml"):
        return _normalize_model_texture_reference(sidecar_path[: -len(".pamlod_xml")] + ".pamlod")
    return ""

def _model_sidecar_binding_matches_source_component(
    source_entry: ArchiveEntry,
    binding: _ArchiveModelSidecarTextureBinding,
) -> bool:
    source_path = _normalize_model_texture_reference(str(getattr(source_entry, "path", "") or ""))
    source_extension = str(getattr(source_entry, "extension", "") or PurePosixPath(source_path).suffix).strip().lower()
    if source_extension not in {".pac", ".pam", ".pamlod"}:
        return True
    linked_model_path = _sidecar_binding_linked_model_path(binding)
    if not linked_model_path or linked_model_path == source_path:
        return True
    source_stems = _archive_model_component_alias_stems(source_path)
    linked_stems = _archive_model_component_alias_stems(linked_model_path)
    if source_stems and linked_stems and source_stems.intersection(linked_stems):
        return True
    return False

def _iter_model_texture_family_reference_candidates(group_key: str) -> Tuple[str, ...]:
    normalized_group_key = _normalize_model_texture_reference(group_key)
    if not normalized_group_key:
        return ()

    ordered_candidates: List[str] = []
    seen: set[str] = set()

    def add_candidate(raw_value: str) -> None:
        normalized = _normalize_model_texture_reference(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered_candidates.append(normalized)

    if "/" in normalized_group_key:
        folder, _, family_name = normalized_group_key.rpartition("/")
    else:
        folder, family_name = "", normalized_group_key
    family_name = family_name.strip()
    if not family_name:
        return ()

    for suffix in _MODEL_TEXTURE_VISIBLE_FAMILY_SUFFIXES:
        basename = f"{family_name}{suffix}.dds"
        add_candidate(basename)
        if folder:
            add_candidate(f"{folder}/{basename}")

    return tuple(ordered_candidates)

def _iter_model_texture_slot_family_reference_candidates(
    group_key: str,
    preview_slot: str,
) -> Tuple[str, ...]:
    normalized_slot = str(preview_slot or "").strip().lower()
    if not normalized_slot or normalized_slot == "base":
        return _iter_model_texture_family_reference_candidates(group_key)

    suffixes = _MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES.get(normalized_slot, ())
    if not suffixes:
        return ()

    normalized_group_key = _normalize_model_texture_reference(group_key)
    if not normalized_group_key:
        return ()

    ordered_candidates: List[str] = []
    seen: set[str] = set()

    def add_candidate(raw_value: str) -> None:
        normalized = _normalize_model_texture_reference(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered_candidates.append(normalized)
        parts = [part for part in PurePosixPath(normalized).parts if part]
        if len(parts) >= 3 and parts[1].lower() == "texture":
            texture_folder_variant = "/".join((parts[0], *parts[2:]))
            if texture_folder_variant and texture_folder_variant not in seen:
                seen.add(texture_folder_variant)
                ordered_candidates.append(texture_folder_variant)

    if "/" in normalized_group_key:
        folder, _, family_name = normalized_group_key.rpartition("/")
    else:
        folder, family_name = "", normalized_group_key
    family_name = family_name.strip()
    if not family_name:
        return ()

    for suffix in suffixes:
        basename = f"{family_name}{suffix}.dds"
        add_candidate(basename)
        if folder:
            add_candidate(f"{folder}/{basename}")

    return tuple(ordered_candidates)

def _iter_model_texture_reference_candidates(
    texture_name: str,
    material_name: str = "",
) -> Tuple[str, ...]:
    ordered_candidates: List[str] = []
    seen: set[str] = set()

    def add_candidate(raw_value: str) -> None:
        normalized = _normalize_model_texture_reference(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        ordered_candidates.append(normalized)

    for raw_value in (texture_name, material_name):
        normalized = _normalize_model_texture_reference(raw_value)
        if not normalized:
            continue
        add_candidate(normalized)
        basename = PurePosixPath(normalized).name
        stem = PurePosixPath(normalized).stem
        suffix = PurePosixPath(normalized).suffix.lower()
        if basename:
            add_candidate(basename)
        if stem:
            add_candidate(stem)
        if suffix != ".dds":
            add_candidate(f"{normalized}.dds")
            if basename:
                add_candidate(f"{basename}.dds")
            if stem:
                add_candidate(f"{stem}.dds")

    return tuple(ordered_candidates)

def _match_model_texture_slot_family_suffix(
    texture_path: str,
    preview_slot: str,
) -> int:
    normalized_slot = str(preview_slot or "").strip().lower()
    suffixes = _MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES.get(normalized_slot, ())
    if not suffixes:
        return -1
    basename = PurePosixPath(_normalize_model_texture_reference(texture_path)).name
    if not basename.endswith(".dds"):
        return -1
    stem = basename[:-4]
    for index, suffix in enumerate(suffixes):
        if stem.endswith(suffix):
            return index
    return -1

def _looks_like_technical_model_texture(texture_path: str) -> bool:
    normalized = _normalize_model_texture_reference(texture_path)
    if not normalized:
        return False
    basename = PurePosixPath(normalized).name
    for pattern in _COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS:
        if (basename and fnmatch.fnmatch(basename, pattern)) or fnmatch.fnmatch(normalized, pattern):
            return True
    return False

def _is_placeholder_model_texture(texture_path: str) -> bool:
    normalized = _normalize_model_texture_reference(texture_path)
    if not normalized:
        return False
    stem = PurePosixPath(normalized).stem.lower()
    compact_stem = re.sub(r"[^a-z0-9]+", "", stem)
    if "nonetexture" in compact_stem or "nulltexture" in compact_stem or "dummytexture" in compact_stem:
        return True
    if compact_stem in {"none", "notexture", "placeholdertexture"}:
        return True
    return False

def _has_explicit_model_texture_reference(*values: str) -> bool:
    for raw_value in values:
        normalized = _normalize_model_texture_reference(raw_value)
        if normalized.endswith(".dds"):
            return True
    return False

def _is_visible_model_texture_type(texture_type: str) -> bool:
    return str(texture_type or "").strip().lower() in {"color", "ui", "emissive", "impostor"}

def _resolve_model_texture_semantics(
    texture_path: str,
    *,
    family_members: Sequence[str] = (),
    sidecar_texts: Sequence[str] = (),
) -> Tuple[str, str, int]:
    semantic = infer_texture_semantics(
        texture_path,
        family_members=family_members,
        sidecar_texts=sidecar_texts,
    )
    texture_type = str(getattr(semantic, "texture_type", "") or "").strip().lower() or "unknown"
    semantic_subtype = str(getattr(semantic, "semantic_subtype", "") or "").strip().lower() or texture_type
    confidence = int(getattr(semantic, "confidence", 0) or 0)
    if texture_type == "unknown":
        normalized = _normalize_model_texture_reference(texture_path)
        if (
            normalized.endswith(".dds")
            and not _is_placeholder_model_texture(normalized)
            and not _looks_like_technical_model_texture(normalized)
        ):
            return "color", "albedo", max(confidence, 64)
    return texture_type, semantic_subtype, confidence

def _resolve_model_texture_semantic_details(
    texture_path: str,
    *,
    family_members: Sequence[str] = (),
    sidecar_texts: Sequence[str] = (),
) -> Tuple[str, str, int, Tuple[str, ...]]:
    semantic = infer_texture_semantics(
        texture_path,
        family_members=family_members,
        sidecar_texts=sidecar_texts,
    )
    texture_type = str(getattr(semantic, "texture_type", "") or "").strip().lower() or "unknown"
    semantic_subtype = str(getattr(semantic, "semantic_subtype", "") or "").strip().lower() or texture_type
    confidence = int(getattr(semantic, "confidence", 0) or 0)
    packed_channels = tuple(
        str(item or "").strip().lower()
        for item in getattr(semantic, "packed_channels", ())
        if str(item or "").strip()
    )
    if texture_type == "unknown":
        normalized = _normalize_model_texture_reference(texture_path)
        if (
            normalized.endswith(".dds")
            and not _is_placeholder_model_texture(normalized)
            and not _looks_like_technical_model_texture(normalized)
        ):
            return "color", "albedo", max(confidence, 64), ()
    return texture_type, semantic_subtype, confidence, packed_channels

def _refine_model_texture_semantic_from_hint(
    texture_type: str,
    semantic_subtype: str,
    semantic_hint: str,
) -> Tuple[str, str]:
    normalized_hint = re.sub(r"[^a-z0-9]+", "", str(semantic_hint or "").strip().lower())
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    if not normalized_hint:
        return normalized_type, normalized_subtype

    if any(token in normalized_hint for token in ("orm", "occlusionroughnessmetallic")):
        return "mask", "orm"
    if any(token in normalized_hint for token in ("rma", "roughnessmetallicao")):
        return "mask", "rma"
    if any(token in normalized_hint for token in ("mra", "metallicroughnessao")):
        return "mask", "mra"
    if any(token in normalized_hint for token in ("arm", "aoroughnessmetallic")):
        return "mask", "arm"
    if "roughness" in normalized_hint:
        return "roughness", "roughness"
    if any(token in normalized_hint for token in ("specular", "gloss", "smoothness")):
        return "mask", "specular"
    if any(token in normalized_hint for token in ("metallic", "metalness")):
        return "mask", "metallic"
    if any(token in normalized_hint for token in ("ao", "occlusion")):
        return "mask", "ao"
    if "opacity" in normalized_hint or "alpha" in normalized_hint:
        return "mask", "opacity_mask"
    if "material" in normalized_hint and normalized_subtype in {"unknown", "mask"}:
        return "mask", "material_mask"
    if any(token in normalized_hint for token in ("basecolor", "basecolour", "overlaycolor", "diffuse", "albedo", "colortexture")):
        return "color", "albedo"
    if "emissive" in normalized_hint:
        return "emissive", "emissive"
    return normalized_type, normalized_subtype

def _infer_model_preview_texture_slot(
    texture_path: str,
    *,
    semantic_hint: str = "",
    sidecar_texts: Sequence[str] = (),
) -> str:
    normalized_hint = re.sub(r"[^a-z0-9]+", "", str(semantic_hint or "").strip().lower())
    if normalized_hint:
        if "normal" in normalized_hint:
            return "normal"
        if any(token in normalized_hint for token in ("emissive", "emission", "illumination", "glow")):
            return "emissive"
        if any(token in normalized_hint for token in ("height", "displacement", "parallax", "pom", "ssdm", "bump")):
            return "height"
        if any(token in normalized_hint for token in ("material", "roughness", "metallic", "metalness", "specular", "ao", "occlusion", "mask")):
            return "material"
        if any(token in normalized_hint for token in ("basecolor", "overlaycolor", "diffuse", "albedo", "colortexture")):
            return "base"
    texture_type, semantic_subtype, _confidence = _resolve_model_texture_semantics(
        texture_path,
        sidecar_texts=sidecar_texts,
    )
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    if normalized_type == "normal":
        return "normal"
    if normalized_type == "height" or normalized_subtype in {"displacement", "parallax_height", "height", "bump"}:
        return "height"
    if normalized_type in {"mask", "roughness", "vector"}:
        return "material"
    if normalized_type == "emissive" or normalized_subtype == "emissive":
        return "emissive"
    return "base"

def _model_texture_candidate_slot_priority(
    preview_slot: str,
    texture_path: str,
    *,
    sidecar_texts: Sequence[str] = (),
) -> Optional[Tuple[int, int]]:
    normalized_slot = str(preview_slot or "").strip().lower()
    if normalized_slot not in {"normal", "material", "height", "emissive"}:
        return None

    texture_type, semantic_subtype, _confidence = _resolve_model_texture_semantics(
        texture_path,
        sidecar_texts=sidecar_texts,
    )
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    suffix_index = _match_model_texture_slot_family_suffix(texture_path, normalized_slot)
    suffix_priority = (
        len(_MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES.get(normalized_slot, ())) - suffix_index
        if suffix_index >= 0
        else 0
    )

    if normalized_slot == "normal":
        if normalized_type == "normal":
            return (12, 3)
        if suffix_index >= 0:
            return (10, suffix_priority)
        return None

    if normalized_slot == "height":
        if normalized_type == "height" or normalized_subtype in {"displacement", "parallax_height", "height", "bump"}:
            return (12, 3)
        if suffix_index >= 0:
            return (10, suffix_priority)
        return None

    if normalized_slot == "emissive":
        if normalized_type == "emissive" or normalized_subtype == "emissive":
            return (12, 3)
        if suffix_index >= 0:
            return (10, suffix_priority)
        return None

    if normalized_slot == "material":
        if normalized_type in {"mask", "roughness", "vector"}:
            return (12, 3)
        if normalized_subtype in {"packed_mask", "specular", "metallic", "ao", "mask", "opacity_mask"}:
            return (11, 2)
        if suffix_index >= 0:
            return (10, suffix_priority)
        return None

    return None

def _infer_model_preview_normal_strength(
    *,
    base_texture_path: str = "",
    normal_texture_path: str = "",
    material_name: str = "",
    semantic_hint: str = "",
    prefer_stronger: bool = False,
) -> float:
    normalized_hint = str(semantic_hint or "").strip().lower().replace("_", "")
    combined = " ".join(
        part
        for part in (
            _normalize_model_texture_reference(base_texture_path),
            _normalize_model_texture_reference(normal_texture_path),
            str(material_name or "").strip().lower(),
            normalized_hint,
        )
        if part
    )

    strength = 0.36
    if prefer_stronger:
        strength += 0.08
    if normalized_hint in {"normaltexture", "basenormaltexture"}:
        strength += 0.06
    elif "detailnormal" in normalized_hint or "grimenormal" in normalized_hint:
        strength -= 0.05

    soft_tokens = (
        "wood",
        "plank",
        "timber",
        "fabric",
        "cloth",
        "rope",
        "leather",
        "skin",
        "paper",
        "parchment",
        "banner",
        "canvas",
        "fur",
        "hair",
    )
    hard_tokens = (
        "stone",
        "rock",
        "brick",
        "concrete",
        "cliff",
        "marble",
        "granite",
        "dungeon",
        "ancient",
        "wall",
        "masonry",
        "ruin",
    )
    medium_tokens = (
        "metal",
        "rust",
        "iron",
        "steel",
        "armor",
        "shield",
        "weapon",
    )

    if any(token in combined for token in soft_tokens):
        strength -= 0.04
    if any(token in combined for token in hard_tokens):
        strength += 0.14
    if any(token in combined for token in medium_tokens):
        strength += 0.08

    return max(0.22, min(0.72, strength))

def _set_model_preview_texture_slot(
    mesh: ModelPreviewMesh,
    *,
    slot: str,
    preview_path: str,
    texture_path: str,
    normal_strength: Optional[float] = None,
    semantic_type: str = "",
    semantic_subtype: str = "",
    packed_channels: Sequence[str] = (),
    flip_vertical: Optional[bool] = None,
) -> bool:
    normalized_slot = str(slot or "").strip().lower()
    preview_path_text = str(preview_path or "").strip()
    texture_path_text = str(texture_path or "").strip()
    if not preview_path_text:
        return False

    if normalized_slot == "normal":
        if not str(getattr(mesh, "preview_normal_texture_path", "") or "").strip():
            mesh.preview_normal_texture_path = preview_path_text
            mesh.preview_normal_texture_image = None
            mesh.preview_normal_texture_name = texture_path_text
            if normal_strength is not None:
                mesh.preview_normal_texture_strength = float(normal_strength)
            if texture_path_text and not str(getattr(mesh, "texture_name", "") or "").strip():
                mesh.texture_name = texture_path_text
            _append_model_preview_material_input(
                mesh,
                PreviewMaterialTextureInput(
                    slot_kind="normal",
                    source_texture_path=texture_path_text,
                    source_dds_path=texture_path_text,
                    texture_name=PurePosixPath(texture_path_text.replace("\\", "/")).name,
                    preview_texture_path=preview_path_text,
                    semantic_type="normal",
                    semantic_subtype="normal",
                    material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                    confidence="resolved",
                    visualized=True,
                ),
            )
            return True
        return False
    if normalized_slot == "material":
        if not str(getattr(mesh, "preview_material_texture_path", "") or "").strip():
            mesh.preview_material_texture_path = preview_path_text
            mesh.preview_material_texture_image = None
            mesh.preview_material_texture_name = texture_path_text
            mesh.preview_material_texture_type = str(semantic_type or "").strip().lower()
            mesh.preview_material_texture_subtype = str(semantic_subtype or "").strip().lower()
            mesh.preview_material_texture_packed_channels = tuple(
                str(channel or "").strip().lower()
                for channel in packed_channels
                if str(channel or "").strip()
            )
            _append_model_preview_material_input(
                mesh,
                PreviewMaterialTextureInput(
                    slot_kind="material",
                    source_texture_path=texture_path_text,
                    source_dds_path=texture_path_text,
                    texture_name=PurePosixPath(texture_path_text.replace("\\", "/")).name,
                    preview_texture_path=preview_path_text,
                    semantic_type=str(semantic_type or "material").strip().lower(),
                    semantic_subtype=str(semantic_subtype or "").strip().lower(),
                    packed_channels=tuple(
                        str(channel or "").strip().lower()
                        for channel in packed_channels
                        if str(channel or "").strip()
                    ),
                    material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                    confidence="resolved",
                    visualized=True,
                ),
            )
            return True
        return False
    if normalized_slot == "height":
        if not str(getattr(mesh, "preview_height_texture_path", "") or "").strip():
            mesh.preview_height_texture_path = preview_path_text
            mesh.preview_height_texture_image = None
            mesh.preview_height_texture_name = texture_path_text
            _append_model_preview_material_input(
                mesh,
                PreviewMaterialTextureInput(
                    slot_kind="height",
                    source_texture_path=texture_path_text,
                    source_dds_path=texture_path_text,
                    texture_name=PurePosixPath(texture_path_text.replace("\\", "/")).name,
                    preview_texture_path=preview_path_text,
                    semantic_type="height",
                    semantic_subtype="displacement",
                    material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                    confidence="resolved",
                    visualized=True,
                ),
            )
            return True
        return False
    if normalized_slot == "emissive":
        if not str(getattr(mesh, "preview_emissive_texture_path", "") or "").strip():
            mesh.preview_emissive_texture_path = preview_path_text
            mesh.preview_emissive_texture_image = None
            mesh.preview_emissive_texture_name = texture_path_text
            _append_model_preview_material_input(
                mesh,
                PreviewMaterialTextureInput(
                    slot_kind="emissive",
                    source_texture_path=texture_path_text,
                    source_dds_path=texture_path_text,
                    texture_name=PurePosixPath(texture_path_text.replace("\\", "/")).name,
                    preview_texture_path=preview_path_text,
                    semantic_type="emissive",
                    semantic_subtype="emissive",
                    material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                    confidence="resolved",
                    visualized=True,
                ),
            )
            return True
        return False

    changed = False
    if not str(getattr(mesh, "preview_texture_path", "") or "").strip():
        mesh.preview_texture_path = preview_path_text
        mesh.preview_texture_image = None
        changed = True
    if texture_path_text:
        current_texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
        if not current_texture_name or not current_texture_name.lower().endswith(".dds"):
            mesh.texture_name = texture_path_text
            changed = True
    if flip_vertical is not None:
        mesh.preview_texture_flip_vertical = bool(flip_vertical)
        changed = True
    if changed:
        _append_model_preview_material_input(
            mesh,
            PreviewMaterialTextureInput(
                slot_kind="base",
                source_texture_path=texture_path_text,
                source_dds_path=texture_path_text,
                texture_name=PurePosixPath(texture_path_text.replace("\\", "/")).name,
                preview_texture_path=preview_path_text,
                semantic_type="color",
                semantic_subtype="albedo",
                material_name=str(getattr(mesh, "material_name", "") or "").strip(),
                confidence="resolved",
                visualized=True,
            ),
        )
    return changed

def _append_model_preview_material_input(
    mesh: ModelPreviewMesh,
    input_item: PreviewMaterialTextureInput,
) -> bool:
    existing = list(getattr(mesh, "preview_material_texture_inputs", ()) or ())
    key = (
        str(input_item.slot_kind or "").strip().lower(),
        str(input_item.preview_texture_path or "").strip().lower(),
        str(input_item.source_texture_path or "").strip().lower(),
        str(input_item.parameter_name or "").strip().lower(),
    )
    for item in existing:
        existing_key = (
            str(getattr(item, "slot_kind", "") or "").strip().lower(),
            str(getattr(item, "preview_texture_path", "") or "").strip().lower(),
            str(getattr(item, "source_texture_path", "") or "").strip().lower(),
            str(getattr(item, "parameter_name", "") or "").strip().lower(),
        )
        if existing_key == key:
            return False
    existing.append(input_item)
    mesh.preview_material_texture_inputs = tuple(existing)
    return True
