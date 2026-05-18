from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_modding import (
    ARCHIVE_MESH_EXTENSIONS,
    MESH_IMPORT_COMPANION_EXTENSIONS,
    MESH_IMPORT_SIDECAR_EXTENSIONS,
    MeshImportPreviewResult,
    MeshImportSupplementalFileSpec,
    _mesh_loose_export_payload_path,
    parsed_mesh_to_preview_model,
)
from cdmw.core.temp_cache import app_temp_cache_path, request_app_temp_cache_prune
from cdmw.core.upscale_profiles import (
    normalize_texture_reference_for_sidecar_lookup,
    parse_texture_sidecar_bindings,
)
from cdmw.models import ModelPreviewData, ModelPreviewMesh
from cdmw.modding.asset_replacement import classify_texture_binding
from cdmw.modding.mesh_parser import parse_mesh


FINAL_PREVIEW_READY = "ready"
FINAL_PREVIEW_MISSING_BASE = "missing_base"
FINAL_PREVIEW_MISSING_DDS = "missing_dds"
FINAL_PREVIEW_DECODE_FAILED = "decode_failed"
FINAL_PREVIEW_SUPPORT_MAPS_ONLY = "support_maps_only"
FINAL_PREVIEW_ADVANCED_SHADER_ONLY = "advanced_shader_only"

FINAL_PREVIEW_BINDING_GENERATED = "generated"
FINAL_PREVIEW_BINDING_ORIGINAL = "original"
FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC = "basename_diagnostic"
FINAL_PREVIEW_BINDING_MISSING = "missing"

FINAL_PREVIEW_PACKAGE_SIDE_EFFECT_EXTENSIONS = (
    ".json",
    ".txt",
    ".md",
    ".ini",
)


TEXTURE_PLAN_STATUS_READY = "Ready"
TEXTURE_PLAN_STATUS_REVIEW = "Review"
TEXTURE_PLAN_STATUS_SUPPORT_ONLY = "Support only"
TEXTURE_PLAN_STATUS_LIKELY_GREY = "Likely grey"
TEXTURE_PLAN_STATUS_IGNORED_ADVANCED = "Ignored / advanced"


@dataclass(slots=True, frozen=True)
class FinalPackageBindingRow:
    material_name: str
    part_name: str
    role: str
    parameter_name: str
    sidecar_path: str
    texture_path: str
    resolved_texture_path: str = ""
    status: str = FINAL_PREVIEW_MISSING_DDS
    material_status: str = FINAL_PREVIEW_MISSING_BASE
    confidence: str = "exact"
    binding_source: str = FINAL_PREVIEW_BINDING_MISSING
    detail: str = ""
    preview_texture_path: str = ""


@dataclass(slots=True, frozen=True)
class FinalPackageMaterialStatus:
    material_name: str
    status: str
    detail: str = ""


@dataclass(slots=True, frozen=True)
class TextureResolutionManifestRow:
    material_name: str
    submesh_name: str
    role: str
    parameter_name: str
    sidecar_path: str
    requested_texture_path: str
    resolved_texture_path: str = ""
    binding_source: str = FINAL_PREVIEW_BINDING_MISSING
    status: str = FINAL_PREVIEW_MISSING_DDS
    reason: str = ""
    skipped_reason: str = ""


@dataclass(slots=True, frozen=True)
class TextureResolutionManifest:
    schema: str = "cdmw_texture_resolution_manifest_v1"
    rows: Tuple[TextureResolutionManifestRow, ...] = ()
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "rows": [dataclasses.asdict(row) for row in self.rows],
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class FinalPackagePreviewResult:
    preview_model: ModelPreviewData
    binding_rows: Tuple[FinalPackageBindingRow, ...] = ()
    warnings: List[str] = field(default_factory=list)
    preflight_errors: List[str] = field(default_factory=list)
    likely_grey_materials: List[str] = field(default_factory=list)
    missing_texture_paths: List[str] = field(default_factory=list)
    summary_lines: List[str] = field(default_factory=list)
    material_statuses: Tuple[FinalPackageMaterialStatus, ...] = ()
    texture_resolution_manifest: TextureResolutionManifest = field(default_factory=TextureResolutionManifest)
    package_root: str = ""


@dataclass(slots=True, frozen=True)
class TexturePlanStatus:
    label: str
    color_key: str
    detail: str = ""


@dataclass(slots=True, frozen=True)
class ReplacementTexturePlanRow:
    part_material: str
    role: str
    source: str
    final_path: str
    status: TexturePlanStatus
    controls: str
    slot_kind: str = ""
    game_effective: bool = True
    part_label: str = ""
    full_part_material: str = ""


@dataclass(slots=True, frozen=True)
class DdsOverrideTableRow:
    part_material: str
    role: str
    original_slot: str
    override_source: str
    target_dds: str
    status: TexturePlanStatus
    controls: str
    slot_kind: str = ""
    target_name: str = ""
    part_label: str = ""
    full_part_material: str = ""


@dataclass(slots=True)
class _FinalPayload:
    final_path: str
    basename: str
    source_path: Path
    payload_data: bytes = b""
    kind: str = ""


@dataclass(slots=True, frozen=True)
class _FinalTextureBinding:
    texture_path: str
    parameter_name: str = ""
    material_name: str = ""
    part_name: str = ""
    submesh_name: str = ""


def _normalize_final_path(path_value: object) -> str:
    normalized = str(path_value or "").replace("\\", "/").strip().strip("/")
    return PurePosixPath(normalized).as_posix().lower() if normalized else ""


def _display_path(path_value: object) -> str:
    normalized = str(path_value or "").replace("\\", "/").strip().strip("/")
    return PurePosixPath(normalized).as_posix() if normalized else ""


_PART_LABEL_PRIORITY = (
    # Weapon and tool pieces.
    "handle",
    "blade",
    "guard",
    "hilt",
    "grip",
    "pommel",
    "sheath",
    "scabbard",
    "edge",
    "tip",
    "shaft",
    "barrel",
    "stock",
    "trigger",
    "scope",
    "magazine",
    "bow",
    "string",
    "quiver",
    # Wearable and humanoid body pieces.
    "helmet",
    "helm",
    "hood",
    "mask",
    "face",
    "hair",
    "head",
    "neck",
    "torso",
    "chest",
    "body",
    "back",
    "waist",
    "hip",
    "hips",
    "pelvis",
    "shoulder",
    "pauldron",
    "arm",
    "forearm",
    "elbow",
    "hand",
    "glove",
    "gauntlet",
    "gauntlets",
    "leg",
    "thigh",
    "knee",
    "shin",
    "foot",
    "boot",
    "boots",
    "greave",
    "greaves",
    "bracer",
    "belt",
    "buckle",
    "cape",
    "cloak",
    "coat",
    "jacket",
    "sleeve",
    "skirt",
    "pants",
    # Creature, organic, and monster pieces.
    "spike",
    "wing",
    "tail",
    "horn",
    "fang",
    "tooth",
    "claw",
    "scale",
    "eye",
    "ear",
    "mane",
    "fin",
    "shell",
    "carapace",
    "belly",
    "spine",
    # Props, attachments, and materials with clear visual meaning.
    "core",
    "strap",
    "chain",
    "rope",
    "ring",
    "gem",
    "jewel",
    "crystal",
    "cloth",
    "leather",
    "metal",
    "wood",
    "glass",
    # Environment pieces.
    "door",
    "window",
    "wall",
    "floor",
    "roof",
    "pillar",
    "column",
    "rock",
    "stone",
    "terrain",
    "ground",
    "grass",
    "tree",
    "leaf",
    "leaves",
    "branch",
    "root",
    "water",
)
_PART_LABEL_ALIASES = {
    "helm": "Helmet",
    "hips": "Hip",
    "pauldron": "Shoulder",
    "gauntlets": "Gauntlet",
    "boots": "Boot",
    "greaves": "Greaves",
    "greave": "Greaves",
    "tooth": "Fang",
    "leaves": "Leaf",
}
_PART_LABEL_IGNORED_TOKENS = {
    "cd",
    "phm",
    "pl",
    "em",
    "wp",
    "wep",
    "weapon",
    "model",
    "mesh",
    "material",
    "mat",
    "mtrl",
    "mt",
    "texture",
    "tex",
    "character",
    "char",
    "onehandweapon",
    "onehand",
    "sword",
    "dagger",
    "knife",
    "part",
    "submesh",
    "lod",
    "low",
    "high",
    "main",
    "meshpart",
}


def simplified_part_label(name_value: object, *, fallback_index: Optional[int] = None) -> str:
    """Return a compact, human-readable part label while preserving full names elsewhere."""

    text = str(name_value or "").replace("\\", "/").strip()
    if not text:
        return f"Part {fallback_index}" if fallback_index is not None else "Part"
    stem = PurePosixPath(text).stem if "/" in text else text
    stem = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", stem)
    tokens = [
        token
        for token in re.split(r"[^A-Za-z0-9]+", stem)
        if token and not token.isdigit()
    ]
    lower_tokens = [token.lower() for token in tokens]
    for preferred in _PART_LABEL_PRIORITY:
        if preferred in lower_tokens:
            return _PART_LABEL_ALIASES.get(preferred, preferred.replace("_", " ").title())
    compact = re.sub(r"[^a-z0-9]+", "", stem.lower())
    for preferred in _PART_LABEL_PRIORITY:
        if len(preferred) >= 4 and preferred in compact:
            return _PART_LABEL_ALIASES.get(preferred, preferred.replace("_", " ").title())
    candidates = [
        token
        for token in tokens
        if token.lower() not in _PART_LABEL_IGNORED_TOKENS
        and not re.fullmatch(r"[a-zA-Z]?\d+[a-zA-Z]?", token)
    ]
    if candidates:
        candidate = candidates[-1]
        if len(candidate) <= 3 and fallback_index is not None:
            return f"Part {fallback_index}"
        return candidate.replace("_", " ").title()
    return f"Part {fallback_index}" if fallback_index is not None else "Part"


def _final_payload_path(path_value: object, export_options: object = None) -> str:
    return _display_path(_mesh_loose_export_payload_path(path_value, export_options))


def _spec_payload_bytes(spec: MeshImportSupplementalFileSpec) -> bytes:
    payload = bytes(getattr(spec, "payload_data", b"") or b"")
    if payload:
        return payload
    source_path = getattr(spec, "source_path", None)
    if isinstance(source_path, Path) and source_path.expanduser().is_file():
        try:
            return source_path.expanduser().read_bytes()
        except OSError:
            return b""
    return b""


def _spec_payload_text(spec: MeshImportSupplementalFileSpec) -> str:
    payload = _spec_payload_bytes(spec)
    if payload:
        for encoding in ("utf-8", "utf-16", "cp1252"):
            try:
                return payload.decode(encoding, errors="replace")
            except Exception:
                continue
    return ""


def _is_sidecar_spec(spec: MeshImportSupplementalFileSpec) -> bool:
    kind = str(getattr(spec, "kind", "") or "").strip().lower()
    target_suffix = PurePosixPath(str(getattr(spec, "target_path", "") or "")).suffix.lower()
    source_suffix = getattr(getattr(spec, "source_path", None), "suffix", "").lower()
    return kind in {"sidecar", "sidecar_generated"} or target_suffix in MESH_IMPORT_SIDECAR_EXTENSIONS or source_suffix in MESH_IMPORT_SIDECAR_EXTENSIONS


def _is_dds_spec(spec: MeshImportSupplementalFileSpec) -> bool:
    kind = str(getattr(spec, "kind", "") or "").strip().lower()
    target_suffix = PurePosixPath(str(getattr(spec, "target_path", "") or "")).suffix.lower()
    source_suffix = getattr(getattr(spec, "source_path", None), "suffix", "").lower()
    return kind in {"texture", "texture_generated"} or target_suffix == ".dds" or source_suffix == ".dds"


def _clone_preview_model(model: ModelPreviewData) -> ModelPreviewData:
    meshes: List[ModelPreviewMesh] = []
    for mesh in getattr(model, "meshes", []) or []:
        if isinstance(mesh, ModelPreviewMesh):
            meshes.append(
                ModelPreviewMesh(
                    **{field_info.name: getattr(mesh, field_info.name) for field_info in dataclasses.fields(ModelPreviewMesh)}
                )
            )
    return ModelPreviewData(
        **{
            field_info.name: (
                meshes
                if field_info.name == "meshes"
                else getattr(model, field_info.name)
            )
            for field_info in dataclasses.fields(ModelPreviewData)
        }
    )


def _rebuilt_preview_model(preview_result: MeshImportPreviewResult, warnings: List[str]) -> ModelPreviewData:
    rebuilt_data = bytes(getattr(preview_result, "rebuilt_data", b"") or b"")
    virtual_path = str(getattr(getattr(preview_result, "parsed_mesh", None), "path", "") or "") or str(
        getattr(getattr(preview_result, "preview_model", None), "path", "") or ""
    )
    if rebuilt_data:
        try:
            parsed = parse_mesh(rebuilt_data, virtual_path)
            return parsed_mesh_to_preview_model(parsed)
        except Exception as exc:
            warnings.append(f"Final preview could not parse rebuilt mesh bytes; using rebuilt preview geometry metadata fallback: {exc}")
    fallback_model = getattr(preview_result, "preview_model", None)
    if isinstance(fallback_model, ModelPreviewData):
        return _clone_preview_model(fallback_model)
    return ModelPreviewData(path=virtual_path)


def _clear_texture_slots(preview_model: ModelPreviewData) -> None:
    for mesh in getattr(preview_model, "meshes", []) or []:
        for attribute_name in (
            "preview_texture_path",
            "preview_normal_texture_path",
            "preview_material_texture_path",
            "preview_height_texture_path",
            "preview_texture_image",
            "preview_normal_texture_image",
            "preview_material_texture_image",
            "preview_height_texture_image",
        ):
            if hasattr(mesh, attribute_name):
                setattr(mesh, attribute_name, None if attribute_name.endswith("_image") else "")
        if hasattr(mesh, "preview_texture_flip_vertical"):
            mesh.preview_texture_flip_vertical = False


def _payload_preview_file(payload: _FinalPayload) -> Path:
    if not payload.payload_data and payload.source_path.is_file():
        return payload.source_path
    digest = hashlib.sha1(payload.payload_data or payload.final_path.encode("utf-8")).hexdigest()[:16]
    target_name = PurePosixPath(payload.final_path).name or payload.source_path.name or "texture.dds"
    if not target_name.lower().endswith(".dds"):
        target_name = f"{Path(target_name).stem}.dds"
    output_dir = app_temp_cache_path("final_package_preview")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{Path(target_name).stem}_{digest}.dds"
    if not output_path.exists() or output_path.stat().st_size != len(payload.payload_data):
        output_path.write_bytes(payload.payload_data)
        request_app_temp_cache_prune()
    return output_path


def _preview_texture_path_for_payload(
    payload: _FinalPayload,
    *,
    texconv_path: Optional[Path],
) -> Tuple[str, str]:
    dds_path = _payload_preview_file(payload)
    try:
        from cdmw.core.pipeline import ensure_dds_display_preview_png, parse_dds

        dds_info = None
        try:
            dds_info = parse_dds(dds_path)
        except Exception:
            dds_info = None
        resolved_texconv = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
        preview_path = ensure_dds_display_preview_png(resolved_texconv, dds_path, dds_info=dds_info)
        return Path(preview_path).as_posix(), ""
    except Exception as exc:
        if texconv_path is None or not texconv_path.expanduser().is_file():
            return dds_path.as_posix(), ""
        return "", str(exc)


def _preview_texture_path_for_original(
    dds_path: Path,
    *,
    texconv_path: Optional[Path],
) -> Tuple[str, str]:
    if not isinstance(dds_path, Path):
        return "", "Original DDS resolver did not return a file path."
    source = dds_path.expanduser()
    if not source.is_file():
        return "", f"Original DDS file is unavailable: {source}"
    try:
        from cdmw.core.pipeline import ensure_dds_display_preview_png, parse_dds

        dds_info = None
        try:
            dds_info = parse_dds(source)
        except Exception:
            dds_info = None
        resolved_texconv = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
        preview_path = ensure_dds_display_preview_png(resolved_texconv, source, dds_info=dds_info)
        return Path(preview_path).as_posix(), ""
    except Exception as exc:
        if texconv_path is None or not texconv_path.expanduser().is_file():
            return source.as_posix(), ""
        return "", str(exc)


def _material_semantics_for_binding(parameter_name: str, texture_path: str) -> Tuple[str, str, Tuple[str, ...]]:
    parameter_normalized = re.sub(r"[^a-z0-9]+", "", str(parameter_name or "").lower())
    path_normalized = re.sub(r"[^a-z0-9]+", "", PurePosixPath(str(texture_path or "")).name.lower())
    normalized = f"{parameter_normalized} {path_normalized}"
    path_stem = PurePosixPath(str(texture_path or "")).stem.lower()
    path_tokens = tuple(token for token in re.split(r"[^a-z0-9]+", path_stem) if token)
    if path_tokens and path_tokens[-1] == "mg":
        return "material", "detail_mask", ("detail",)
    if path_tokens and path_tokens[-1] == "ma":
        return "material", "material_mask", ("ao", "roughness", "metallic")
    if any(token in parameter_normalized for token in ("metallic", "metalness", "metal")):
        return "material", "metallic", ("metallic",)
    if any(token in parameter_normalized for token in ("roughness", "rough", "smoothness", "gloss")):
        return "material", "roughness", ("roughness",)
    if any(token in parameter_normalized for token in ("ambientocclusion", "occlusion", "cavity", "ao")):
        return "material", "ao", ("ao",)
    if any(token in parameter_normalized for token in ("specular", "shine", "gloss")):
        return "material", "specular", ("specular",)
    if any(token in normalized for token in ("orm", "rma", "mra", "arm", "materialmask", "material", "mask")):
        return "material", "material_mask", ("ao", "roughness", "metallic")
    if any(token in normalized for token in ("metallic", "metalness", "metal")):
        return "material", "metallic", ("metallic",)
    if any(token in normalized for token in ("roughness", "rough", "smoothness", "gloss")):
        return "material", "roughness", ("roughness",)
    if any(token in normalized for token in ("ambientocclusion", "occlusion", "cavity", "ao")):
        return "material", "ao", ("ao",)
    if any(token in normalized for token in ("specular", "shine", "gloss")):
        return "material", "specular", ("specular",)
    return "material", "material_mask", ()


def _material_label_for_mesh(mesh: ModelPreviewMesh, index: int) -> str:
    return (
        str(getattr(mesh, "material_name", "") or "").strip()
        or str(getattr(mesh, "texture_name", "") or "").strip()
        or f"Material {index + 1}"
    )


def _material_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _material_loose_key(value: object) -> str:
    key = _material_key(value)
    return re.sub(r"\d+", lambda match: str(int(match.group(0) or "0")), key)


def _binding_material_name(binding: object) -> str:
    return (
        str(getattr(binding, "material_name", "") or "").strip()
        or str(getattr(binding, "part_name", "") or "").strip()
        or str(getattr(binding, "submesh_name", "") or "").strip()
        or "Material"
    )


def _candidate_mesh_indices(preview_model: ModelPreviewData, binding: object) -> Tuple[int, ...]:
    meshes = list(getattr(preview_model, "meshes", []) or [])
    if not meshes:
        return ()
    binding_candidates = [
        _material_key(getattr(binding, attribute_name, ""))
        for attribute_name in ("material_name", "part_name", "submesh_name")
    ]
    binding_candidates = [candidate for candidate in binding_candidates if candidate]
    matched: List[int] = []
    if binding_candidates:
        for index, mesh in enumerate(meshes):
            mesh_candidates = [
                _material_key(getattr(mesh, attribute_name, ""))
                for attribute_name in ("material_name", "texture_name")
            ]
            if any(candidate and candidate in mesh_candidates for candidate in binding_candidates):
                matched.append(index)
    if matched:
        return tuple(matched)
    loose_binding_candidates = {
        _material_loose_key(getattr(binding, attribute_name, ""))
        for attribute_name in ("material_name", "part_name", "submesh_name")
        if _material_loose_key(getattr(binding, attribute_name, ""))
    }
    if loose_binding_candidates:
        for index, mesh in enumerate(meshes):
            loose_mesh_candidates = {
                _material_loose_key(getattr(mesh, attribute_name, ""))
                for attribute_name in ("material_name", "texture_name")
                if _material_loose_key(getattr(mesh, attribute_name, ""))
            }
            if loose_binding_candidates & loose_mesh_candidates:
                matched.append(index)
    if matched:
        return tuple(matched)
    if len(meshes) == 1:
        return (0,)
    return ()


def _build_texture_resolution_manifest(
    binding_rows: Sequence[FinalPackageBindingRow],
    warnings: Sequence[str],
) -> TextureResolutionManifest:
    manifest_rows: List[TextureResolutionManifestRow] = []
    for row in binding_rows:
        requested = str(row.texture_path or "")
        normalized_requested = requested.replace("\\", "/").lower()
        skipped_reason = ""
        if "nonetexture" in normalized_requested or "none_texture" in normalized_requested:
            skipped_reason = "engine null texture sentinel"
        elif row.status == FINAL_PREVIEW_MISSING_DDS:
            skipped_reason = "missing final DDS payload"
        elif row.status == FINAL_PREVIEW_ADVANCED_SHADER_ONLY:
            skipped_reason = "advanced/support shader binding"
        manifest_rows.append(
            TextureResolutionManifestRow(
                material_name=row.material_name,
                submesh_name=row.part_name or row.material_name,
                role=row.role,
                parameter_name=row.parameter_name,
                sidecar_path=row.sidecar_path,
                requested_texture_path=requested,
                resolved_texture_path=row.resolved_texture_path,
                binding_source=row.binding_source,
                status=row.status,
                reason=row.detail,
                skipped_reason=skipped_reason,
            )
        )
    return TextureResolutionManifest(
        rows=tuple(manifest_rows),
        warnings=tuple(str(warning) for warning in warnings),
    )


def _slot_role(parameter_name: str, texture_path: str) -> Tuple[str, str, bool]:
    normalized = re.sub(r"[^a-z0-9]+", "", f"{parameter_name} {PurePosixPath(texture_path).name}".lower())
    if any(token in normalized for token in ("emissive", "glow", "illum")):
        return "emissive", "Emissive", True
    classification = classify_texture_binding(parameter_name, texture_path)
    slot_kind = str(getattr(classification, "slot_kind", "") or "").strip().lower() or "material"
    semantic_type = str(getattr(classification, "semantic_type", "") or "").strip().lower()
    combined = f"{parameter_name} {texture_path}".lower()
    if semantic_type == "emissive" or any(token in combined for token in ("emissive", "glow", "illum")):
        return "emissive", "Emissive", bool(getattr(classification, "visualized", False))
    if slot_kind == "base":
        return "base", "Base / Color", bool(getattr(classification, "visualized", False))
    if slot_kind == "normal":
        return "normal", "Normal", bool(getattr(classification, "visualized", False))
    if slot_kind == "height":
        return "height", "Height", bool(getattr(classification, "visualized", False))
    if slot_kind == "material_mask":
        return "material", "Material / Mask", bool(getattr(classification, "visualized", False))
    if slot_kind == "detail_mask":
        return "material", "Detail Mask", bool(getattr(classification, "visualized", False))
    if any(token in normalized for token in ("colorblendingmask", "detailmask", "material", "metallic", "roughness", "occlusion", "mask")):
        return "material", "Material / Mask", True
    if "normal" in normalized:
        return "normal", "Normal", True
    if any(token in normalized for token in ("height", "displacement", "depth", "parallax", "bump")):
        return "height", "Height", True
    if any(token in normalized for token in ("basecolor", "overlaycolor", "diffuse", "albedo", "colortexture", "basetexture")):
        return "base", "Base / Color", True
    return "material", "Material / Mask", bool(getattr(classification, "visualized", False))


def _assign_row_to_meshes(
    preview_model: ModelPreviewData,
    mesh_indices: Sequence[int],
    role_key: str,
    preview_texture_path: str,
    texture_name: str,
    *,
    parameter_name: str = "",
    texture_path: str = "",
) -> None:
    if not preview_texture_path:
        return
    meshes = list(getattr(preview_model, "meshes", []) or [])
    for mesh_index in mesh_indices:
        if mesh_index < 0 or mesh_index >= len(meshes):
            continue
        mesh = meshes[mesh_index]
        if role_key in {"base", "emissive"}:
            mesh.preview_texture_path = preview_texture_path
            mesh.texture_name = texture_name
            mesh.preview_texture_flip_vertical = False
        elif role_key == "normal":
            mesh.preview_normal_texture_path = preview_texture_path
            mesh.preview_normal_texture_name = texture_name
            mesh.preview_normal_texture_strength = 0.75
        elif role_key == "height":
            mesh.preview_height_texture_path = preview_texture_path
            mesh.preview_height_texture_name = texture_name
        elif role_key == "material":
            semantic_type, semantic_subtype, packed_channels = _material_semantics_for_binding(parameter_name, texture_path or texture_name)
            mesh.preview_material_texture_path = preview_texture_path
            mesh.preview_material_texture_name = texture_name
            mesh.preview_material_texture_type = semantic_type
            mesh.preview_material_texture_subtype = semantic_subtype
            mesh.preview_material_texture_packed_channels = tuple(packed_channels)


def _assign_unmatched_visible_textures_by_order(
    preview_model: ModelPreviewData,
    binding_rows: Sequence[FinalPackageBindingRow],
) -> int:
    ready_visible_rows = [
        row
        for row in binding_rows
        if row.role in {"Base / Color", "Emissive"}
        and row.status == FINAL_PREVIEW_READY
        and row.confidence == "exact"
        and str(row.preview_texture_path or "").strip()
    ]
    if not ready_visible_rows:
        return 0
    unmatched_meshes = [
        (index, mesh)
        for index, mesh in enumerate(getattr(preview_model, "meshes", []) or [])
        if not str(getattr(mesh, "preview_texture_path", "") or "").strip()
    ]
    assigned_count = 0
    for (mesh_index, _mesh), row in zip(unmatched_meshes, ready_visible_rows):
        _assign_row_to_meshes(
            preview_model,
            (mesh_index,),
            "base",
            row.preview_texture_path,
            PurePosixPath(row.resolved_texture_path or row.texture_path).name,
            parameter_name=row.parameter_name,
            texture_path=row.texture_path,
        )
        assigned_count += 1
    return assigned_count


def _dedupe(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _visible_preview_texture_count(model: object) -> int:
    textures: set[str] = set()
    for mesh in getattr(model, "meshes", ()) or ():
        texture_path = str(getattr(mesh, "preview_texture_path", "") or "").replace("\\", "/").strip()
        if texture_path:
            textures.add(texture_path.lower())
    return len(textures)


def _preview_result_texture_contract_warnings(preview_result: MeshImportPreviewResult) -> List[str]:
    warnings: List[str] = []
    for line in tuple(getattr(preview_result, "summary_lines", ()) or ()):
        text = str(line or "").strip()
        if not text:
            continue
        if "Texture routing blocker:" in text:
            warnings.append(
                text
                + " Final preview uses the rebuilt game draw/material slots, so separate source textures cannot be shown on "
                "one merged target slot. Split the added parts across separate original draw slots, or bake/atlas those "
                "source textures into one material before export."
            )
            continue
        if "[Blocked;" in text and "<-" in text:
            warnings.append(
                "Static texture routing is blocked for one or more source materials. The replacement placement preview can "
                "show source-material convenience textures, but the final preview can only show the validated rebuilt "
                "sidecar/DDS contract."
            )
    return warnings


def _is_stock_or_shared_texture_path(texture_path: str) -> bool:
    basename = PurePosixPath(str(texture_path or "").replace("\\", "/")).name.lower()
    return (
        basename.startswith("cd_texturelayer_")
        or basename.startswith("cd_temp")
        or basename.startswith("cd_metal_")
        or basename.startswith("blackoil")
        or basename.startswith("cd_common_default")
        or basename.startswith("nonetexture")
        or basename.startswith("none_texture")
    )


def _looks_like_normal_texture_path(texture_path: str) -> bool:
    stem = PurePosixPath(str(texture_path or "").replace("\\", "/")).stem.lower()
    if "normal" in stem or stem.endswith(("_n", "_wn", "_nm", "_nrm", "_nor", "_no")):
        return True
    return bool(re.search(r"(?:^|[_\-.])n(?:$|[_\-.])", stem))


def _looks_like_normal_source_path(source_path: object) -> bool:
    if not isinstance(source_path, Path):
        return False
    return _looks_like_normal_texture_path(source_path.name)


def _package_spec_kind_for_path(path_value: object) -> str:
    suffix = PurePosixPath(str(path_value or "").replace("\\", "/")).suffix.lower()
    if suffix in ARCHIVE_MESH_EXTENSIONS:
        return "mesh"
    if suffix == ".dds":
        return "texture_generated"
    if suffix in MESH_IMPORT_SIDECAR_EXTENSIONS:
        return "sidecar_generated"
    if suffix in MESH_IMPORT_COMPANION_EXTENSIONS:
        return "companion"
    return "file"


def _is_final_preview_payload_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in ARCHIVE_MESH_EXTENSIONS:
        return True
    if suffix == ".dds":
        return True
    if suffix in MESH_IMPORT_SIDECAR_EXTENSIONS:
        return True
    if suffix in MESH_IMPORT_COMPANION_EXTENSIONS:
        return True
    return False


def _is_mesh_payload_spec(spec: MeshImportSupplementalFileSpec) -> bool:
    kind = str(getattr(spec, "kind", "") or "").strip().lower()
    target_suffix = PurePosixPath(str(getattr(spec, "target_path", "") or "")).suffix.lower()
    source_suffix = getattr(getattr(spec, "source_path", None), "suffix", "").lower()
    return kind == "mesh" or target_suffix in ARCHIVE_MESH_EXTENSIONS or source_suffix in ARCHIVE_MESH_EXTENSIONS


def _spec_payload_raw_bytes(spec: MeshImportSupplementalFileSpec) -> bytes:
    payload_data = bytes(getattr(spec, "payload_data", b"") or b"")
    if payload_data:
        return payload_data
    source_path = getattr(spec, "source_path", None)
    if isinstance(source_path, Path):
        try:
            resolved = source_path.expanduser().resolve()
            if resolved.is_file():
                return resolved.read_bytes()
        except OSError:
            return b""
    return b""


def _package_rebuilt_mesh_data(
    specs: Sequence[MeshImportSupplementalFileSpec],
    preview_result: MeshImportPreviewResult,
    export_options: object = None,
) -> bytes:
    parsed_path = str(getattr(getattr(preview_result, "parsed_mesh", None), "path", "") or "").replace("\\", "/").strip()
    model_path = str(getattr(getattr(preview_result, "preview_model", None), "path", "") or "").replace("\\", "/").strip()
    expected_keys = {
        _normalize_final_path(_final_payload_path(path, export_options))
        for path in (parsed_path, model_path)
        if path
    }
    mesh_specs = [spec for spec in tuple(specs or ()) if isinstance(spec, MeshImportSupplementalFileSpec) and _is_mesh_payload_spec(spec)]
    if not mesh_specs:
        return b""
    for spec in mesh_specs:
        target_key = _normalize_final_path(str(getattr(spec, "target_path", "") or ""))
        if target_key and target_key in expected_keys:
            return _spec_payload_raw_bytes(spec)
    if len(mesh_specs) == 1:
        return _spec_payload_raw_bytes(mesh_specs[0])
    return b""


def _package_specs_from_manifest(package_root: Path, manifest_payload: Mapping[str, object]) -> Tuple[MeshImportSupplementalFileSpec, ...]:
    files_root = str(manifest_payload.get("files_root") or manifest_payload.get("files_dir") or "").strip().strip("/\\")
    if files_root in {"", "."}:
        payload_root = package_root
    else:
        payload_root = package_root / files_root
    specs: List[MeshImportSupplementalFileSpec] = []
    for row in tuple(manifest_payload.get("files", ()) or ()):
        if not isinstance(row, Mapping):
            continue
        target_path = _display_path(row.get("path"))
        if not target_path:
            continue
        source_path = payload_root.joinpath(*PurePosixPath(target_path).parts)
        if not source_path.is_file() or not _is_final_preview_payload_file(source_path):
            continue
        specs.append(
            MeshImportSupplementalFileSpec(
                source_path=source_path,
                target_path=target_path,
                kind=_package_spec_kind_for_path(target_path),
                used_for_preview=True,
                payload_data=b"",
                note="Scanned from exact final loose package manifest.",
            )
        )
    return tuple(specs)


def build_final_package_specs_from_package_root(package_root: Path) -> Tuple[MeshImportSupplementalFileSpec, ...]:
    """Return preview specs from files that actually exist in a written loose package."""

    root = package_root.expanduser().resolve()
    if not root.is_dir():
        return ()
    manifest_path = root / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest_payload = {}
        if isinstance(manifest_payload, Mapping):
            manifest_specs = _package_specs_from_manifest(root, manifest_payload)
            if manifest_specs:
                return manifest_specs

    candidate_roots: List[Tuple[Path, PurePosixPath]] = []
    files_root = root / "files"
    if files_root.is_dir():
        candidate_roots.append((files_root, PurePosixPath()))
    candidate_roots.append((root, PurePosixPath()))
    specs_by_key: Dict[str, MeshImportSupplementalFileSpec] = {}
    ignored_names = {
        ".no_encrypt",
        "manifest.json",
        "mod.json",
        "modinfo.json",
        "info.json",
        "readme.txt",
        "cdmw_texture_resolution_manifest.json",
    }
    for physical_root, virtual_prefix in candidate_roots:
        try:
            files = tuple(path for path in physical_root.rglob("*") if path.is_file())
        except OSError:
            continue
        for path in files:
            if path.name.lower() in ignored_names or not _is_final_preview_payload_file(path):
                continue
            try:
                relative = path.relative_to(physical_root)
            except ValueError:
                continue
            target_path = PurePosixPath(virtual_prefix, *relative.parts).as_posix()
            normalized_target = _normalize_final_path(target_path)
            if not normalized_target or normalized_target in specs_by_key:
                continue
            specs_by_key[normalized_target] = MeshImportSupplementalFileSpec(
                source_path=path,
                target_path=target_path,
                kind=_package_spec_kind_for_path(target_path),
                used_for_preview=True,
                payload_data=b"",
                note="Scanned from exact final loose package files.",
            )
    return tuple(specs_by_key[key] for key in sorted(specs_by_key))


def stage_final_package_preview_payloads(
    preview_result: MeshImportPreviewResult,
    *,
    supplemental_file_specs: Sequence[MeshImportSupplementalFileSpec],
    export_options: object = None,
    label: str = "test_build_preview",
) -> Path:
    """Write an in-memory final package candidate to the app temp cache and return its package root."""

    hasher = hashlib.sha1()
    hasher.update(bytes(getattr(preview_result, "rebuilt_data", b"") or b""))
    for spec in tuple(supplemental_file_specs or ()):
        if not isinstance(spec, MeshImportSupplementalFileSpec):
            continue
        hasher.update(str(getattr(spec, "target_path", "") or "").encode("utf-8", errors="ignore"))
        payload = bytes(getattr(spec, "payload_data", b"") or b"")
        if payload:
            hasher.update(payload[:4096])
            hasher.update(str(len(payload)).encode("ascii"))
        else:
            source_path = getattr(spec, "source_path", None)
            if isinstance(source_path, Path):
                hasher.update(source_path.as_posix().encode("utf-8", errors="ignore"))
    digest = hasher.hexdigest()[:16]
    safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(label or "test_build_preview")).strip("._") or "test_build_preview"
    package_root = app_temp_cache_path("final_package_preview_stage") / f"{safe_label}_{digest}"
    if package_root.exists():
        shutil.rmtree(package_root)
    package_root.mkdir(parents=True, exist_ok=True)
    manifest_files: List[dict] = []

    parsed_path = str(getattr(getattr(preview_result, "parsed_mesh", None), "path", "") or "").strip()
    rebuilt_data = bytes(getattr(preview_result, "rebuilt_data", b"") or b"")
    if parsed_path and rebuilt_data:
        target_path = _final_payload_path(parsed_path, export_options)
        if target_path:
            output_path = package_root.joinpath(*PurePosixPath(target_path).parts)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(rebuilt_data)
            manifest_files.append({"path": target_path, "format": output_path.suffix.lstrip(".").lower()})

    seen: set[str] = {str(row["path"]).lower() for row in manifest_files}
    for spec in tuple(supplemental_file_specs or ()):
        if not isinstance(spec, MeshImportSupplementalFileSpec):
            continue
        target_path = _final_payload_path(str(getattr(spec, "target_path", "") or ""), export_options)
        if not target_path:
            continue
        key = target_path.lower()
        if key in seen:
            continue
        payload = _spec_payload_raw_bytes(spec)
        if not payload:
            continue
        output_path = package_root.joinpath(*PurePosixPath(target_path).parts)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(payload)
        manifest_files.append({"path": target_path, "format": output_path.suffix.lstrip(".").lower()})
        seen.add(key)

    (package_root / "manifest.json").write_text(
        json.dumps(
            {
                "format": "v1",
                "kind": "mesh_loose_mod_preview_stage",
                "files_root": ".",
                "files": manifest_files,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    request_app_temp_cache_prune()
    return package_root


def build_final_package_preview(
    preview_result: MeshImportPreviewResult,
    *,
    supplemental_file_specs: Optional[Sequence[MeshImportSupplementalFileSpec]] = None,
    export_options: object = None,
    texconv_path: Optional[Path] = None,
    original_dds_resolver: Optional[Callable[[str], Optional[Path]]] = None,
    original_dds_basename_resolver: Optional[Callable[[str], Sequence[Path]]] = None,
    package_root: Optional[Path] = None,
    require_source_owned_colors: bool = False,
) -> FinalPackagePreviewResult:
    """Build the texture-authoritative mesh preview for the package payloads that would be exported."""

    warnings: List[str] = []
    package_root_text = ""
    if package_root is not None:
        try:
            resolved_package_root = package_root.expanduser().resolve()
            package_root_text = resolved_package_root.as_posix()
        except Exception:
            resolved_package_root = package_root
            package_root_text = str(package_root)
        package_specs = build_final_package_specs_from_package_root(resolved_package_root)
        if package_specs:
            specs = package_specs
        else:
            specs = tuple(supplemental_file_specs if supplemental_file_specs is not None else getattr(preview_result, "supplemental_file_specs", ()) or ())
            warnings.append(f"Final package preview could not scan package payloads from {package_root_text}; using in-memory payload specs.")
    else:
        specs = tuple(supplemental_file_specs if supplemental_file_specs is not None else getattr(preview_result, "supplemental_file_specs", ()) or ())

    effective_preview_result = preview_result
    package_mesh_data = _package_rebuilt_mesh_data(specs, preview_result, export_options)
    if package_mesh_data:
        effective_preview_result = dataclasses.replace(preview_result, rebuilt_data=package_mesh_data)

    preview_model = _rebuilt_preview_model(effective_preview_result, warnings)
    _clear_texture_slots(preview_model)
    warnings.extend(_preview_result_texture_contract_warnings(effective_preview_result))

    sidecars: Dict[str, Tuple[str, MeshImportSupplementalFileSpec]] = {}
    dds_by_path: Dict[str, _FinalPayload] = {}
    dds_by_basename: Dict[str, List[_FinalPayload]] = {}
    generated_sidecar_count = 0
    for spec in specs:
        if not isinstance(spec, MeshImportSupplementalFileSpec):
            continue
        target_path = str(getattr(spec, "target_path", "") or "").strip()
        if not target_path:
            continue
        final_path = _final_payload_path(target_path, export_options)
        if not final_path:
            continue
        final_key = _normalize_final_path(final_path)
        if _is_sidecar_spec(spec):
            text = _spec_payload_text(spec)
            if text.strip():
                sidecars[final_key] = (final_path, spec)
                if str(getattr(spec, "kind", "") or "").strip().lower() == "sidecar_generated":
                    generated_sidecar_count += 1
            continue
        if _is_dds_spec(spec):
            payload_data = bytes(getattr(spec, "payload_data", b"") or b"")
            source_path = getattr(spec, "source_path", Path())
            resolved_source = source_path.expanduser().resolve() if isinstance(source_path, Path) else Path()
            if not payload_data and not resolved_source.is_file():
                continue
            payload = _FinalPayload(
                final_path=final_path,
                basename=PurePosixPath(final_path).name.lower(),
                source_path=resolved_source,
                payload_data=payload_data,
                kind=str(getattr(spec, "kind", "") or ""),
            )
            dds_by_path.setdefault(final_key, payload)
            if payload.basename:
                dds_by_basename.setdefault(payload.basename, []).append(payload)
            if _is_stock_or_shared_texture_path(final_path):
                warnings.append(
                    f"Texture contract warning: generated/copied payload overrides stock/shared shader texture {final_path}. "
                    "This can tint the model, add grime/speckles, or affect shared material layers."
                )

    binding_rows: List[FinalPackageBindingRow] = []
    missing_paths: List[str] = []
    rows_by_material: Dict[str, List[FinalPackageBindingRow]] = {}
    material_display_by_key: Dict[str, str] = {}
    mesh_indices_by_material: Dict[str, List[int]] = {}
    for index, mesh in enumerate(getattr(preview_model, "meshes", []) or []):
        material_name = _material_label_for_mesh(mesh, index)
        key = _material_key(material_name) or f"mesh{index}"
        material_display_by_key.setdefault(key, material_name)
        mesh_indices_by_material.setdefault(key, []).append(index)

    binding_sources: List[Tuple[str, object]] = []
    for sidecar_path, spec in sidecars.values():
        sidecar_text = _spec_payload_text(spec)
        for binding in parse_texture_sidecar_bindings(sidecar_text, sidecar_path=sidecar_path):
            binding_sources.append((sidecar_path, binding))
    if not binding_sources:
        for reference in tuple(getattr(preview_result, "texture_references", ()) or ()):
            if str(getattr(reference, "reference_kind", "texture") or "texture").strip().lower() != "texture":
                continue
            texture_path = str(
                getattr(reference, "resolved_archive_path", "")
                or getattr(reference, "reference_name", "")
                or ""
            ).replace("\\", "/").strip()
            if not texture_path.lower().endswith(".dds"):
                continue
            binding_sources.append(
                (
                    "kept original sidecar bindings",
                    _FinalTextureBinding(
                        texture_path=texture_path,
                        parameter_name=str(getattr(reference, "sidecar_parameter_name", "") or ""),
                        material_name=str(getattr(reference, "material_name", "") or ""),
                        part_name=str(getattr(reference, "part_name", "") or ""),
                        submesh_name=str(getattr(reference, "material_name", "") or ""),
                    ),
                )
            )

    for sidecar_path, binding in binding_sources:
            texture_path = str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
            if not texture_path.lower().endswith(".dds"):
                continue
            parameter_name = str(getattr(binding, "parameter_name", "") or "").strip()
            if parameter_name.lower() == "_normaltexture" and not _looks_like_normal_texture_path(texture_path):
                warnings.append(
                    f"Texture contract warning: _normalTexture points at a non-normal-looking DDS path: {texture_path}."
                )
            role_key, role_label, visualized = _slot_role(parameter_name, texture_path)
            final_texture_path = _final_payload_path(texture_path, export_options)
            final_texture_key = _normalize_final_path(final_texture_path)
            texture_basename = PurePosixPath(final_texture_path or texture_path).name.lower()
            payload = dds_by_path.get(final_texture_key)
            if payload is not None and role_key == "base" and _looks_like_normal_source_path(payload.source_path):
                warnings.append(
                    f"Texture contract warning: base/overlay color slot {texture_path} resolves to a generated DDS "
                    f"from normal-map source {payload.source_path.name}."
                )
            confidence = "exact"
            binding_source = FINAL_PREVIEW_BINDING_MISSING
            detail = ""
            if payload is None:
                original_path: Optional[Path] = None
                if original_dds_resolver is not None:
                    try:
                        original_path = original_dds_resolver(final_texture_path or texture_path)
                    except Exception as exc:
                        warnings.append(f"Original DDS resolver failed for {final_texture_path or texture_path}: {exc}")
                if isinstance(original_path, Path) and original_path.expanduser().is_file():
                    preview_texture_path, decode_error = _preview_texture_path_for_original(original_path, texconv_path=texconv_path)
                    if decode_error:
                        status = FINAL_PREVIEW_DECODE_FAILED
                        detail = f"Original archive DDS exists at the exact final sidecar path but could not be decoded for preview: {decode_error}"
                        warnings.append(detail)
                    else:
                        status = FINAL_PREVIEW_READY
                        detail = "Resolved to the kept original archive DDS at the exact final sidecar path."
                    binding_source = FINAL_PREVIEW_BINDING_ORIGINAL
                    resolved_texture_path = final_texture_path or texture_path
                else:
                    fallback_payloads = list(dds_by_basename.get(texture_basename, ()))
                    fallback_original_paths: Sequence[Path] = ()
                    if original_dds_basename_resolver is not None and texture_basename:
                        try:
                            fallback_original_paths = tuple(original_dds_basename_resolver(texture_basename) or ())
                        except Exception:
                            fallback_original_paths = ()
                    if fallback_payloads or fallback_original_paths:
                        confidence = "basename"
                        binding_source = FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC
                        detail = (
                            "A DDS with the same basename exists, but the final sidecar path did not match exactly; "
                            "basename fallback is diagnostic only and is not treated as texture-ready."
                        )
                    else:
                        detail = "No generated/copied or kept-original DDS exists at the final sidecar texture path."
                    status = FINAL_PREVIEW_MISSING_DDS
                    missing_paths.append(final_texture_path or texture_path)
                    resolved_texture_path = ""
                    preview_texture_path = ""
            else:
                preview_texture_path, decode_error = _preview_texture_path_for_payload(payload, texconv_path=texconv_path)
                if decode_error:
                    status = FINAL_PREVIEW_DECODE_FAILED
                    detail = f"Generated/copied DDS exists but could not be decoded for preview: {decode_error}"
                    warnings.append(detail)
                    resolved_texture_path = payload.final_path
                    binding_source = FINAL_PREVIEW_BINDING_GENERATED
                else:
                    status = FINAL_PREVIEW_READY
                    detail = "Resolved to a generated/copied DDS payload at the exact final sidecar path."
                    resolved_texture_path = payload.final_path
                    binding_source = FINAL_PREVIEW_BINDING_GENERATED

            binding_material = _binding_material_name(binding)
            binding_key = _material_key(binding_material)
            mesh_indices = _candidate_mesh_indices(preview_model, binding)
            if mesh_indices:
                for mesh_index in mesh_indices:
                    mesh = preview_model.meshes[mesh_index]
                    material_name = _material_label_for_mesh(mesh, mesh_index)
                    material_key = _material_key(material_name) or f"mesh{mesh_index}"
                    material_display_by_key.setdefault(material_key, material_name)
                    rows_by_material.setdefault(material_key, [])
                if status == FINAL_PREVIEW_READY and confidence == "exact":
                    _assign_row_to_meshes(
                        preview_model,
                        mesh_indices,
                        role_key,
                        preview_texture_path,
                        PurePosixPath(resolved_texture_path or texture_path).name,
                        parameter_name=parameter_name,
                        texture_path=texture_path,
                    )
            else:
                material_key = binding_key or f"sidecar{len(rows_by_material)}"
                material_display_by_key.setdefault(material_key, binding_material)
                rows_by_material.setdefault(material_key, [])

            row = FinalPackageBindingRow(
                material_name=binding_material,
                part_name=str(getattr(binding, "part_name", "") or getattr(binding, "submesh_name", "") or "").strip(),
                role=role_label,
                parameter_name=parameter_name,
                sidecar_path=sidecar_path,
                texture_path=texture_path,
                resolved_texture_path=resolved_texture_path,
                status=status,
                confidence=confidence,
                binding_source=binding_source,
                detail=detail,
                preview_texture_path=preview_texture_path,
            )
            binding_rows.append(row)
            target_keys = []
            if mesh_indices:
                target_keys.extend(
                    _material_key(_material_label_for_mesh(preview_model.meshes[mesh_index], mesh_index)) or f"mesh{mesh_index}"
                    for mesh_index in mesh_indices
                )
            else:
                target_keys.append(binding_key or row.material_name.lower())
            for target_key in target_keys:
                rows_by_material.setdefault(target_key, []).append(row)

    referenced_dds_keys = {
        _normalize_final_path(_final_payload_path(str(row.texture_path or ""), export_options))
        for row in binding_rows
        if str(row.texture_path or "").strip()
    }
    orphan_payload_paths = [
        payload.final_path
        for key, payload in sorted(dds_by_path.items())
        if key not in referenced_dds_keys
        and "/ui/" not in payload.final_path.replace("\\", "/").lower()
        and not payload.final_path.replace("\\", "/").lower().startswith("ui/")
    ]
    if sidecars and orphan_payload_paths:
        warnings.append(
            "Texture contract warning: generated/copied DDS payloads not referenced by parsed material sidecar: "
            + ", ".join(orphan_payload_paths[:8])
            + (" ..." if len(orphan_payload_paths) > 8 else "")
        )

    fallback_assignment_count = _assign_unmatched_visible_textures_by_order(preview_model, binding_rows)
    if fallback_assignment_count:
        warnings.append(
            "Final preview assigned visible textures by draw-order fallback for "
            f"{fallback_assignment_count:,} unmatched mesh batch(es). This is preview-only; material names did not match final sidecar bindings exactly."
        )

    source_visible_texture_count = _visible_preview_texture_count(getattr(preview_result, "preview_model", None))
    final_visible_texture_count = _visible_preview_texture_count(preview_model)
    if source_visible_texture_count > final_visible_texture_count:
        warnings.append(
            "Final preview is showing fewer visible texture set(s) than the replacement placement preview "
            f"({final_visible_texture_count:,}/{source_visible_texture_count:,}). This usually means imported source "
            "materials were merged into fewer game draw slots, or the final sidecar/DDS paths could not be validated. "
            "Use separate original target slots where possible, or bake/atlas the source textures when parts must share one slot."
        )

    material_statuses: List[FinalPackageMaterialStatus] = []
    likely_grey_materials: List[str] = []
    all_material_keys = (set(material_display_by_key) if sidecars else set()) | set(rows_by_material)
    for material_key in sorted(all_material_keys, key=lambda key: material_display_by_key.get(key, key).lower()):
        material_name = material_display_by_key.get(material_key, material_key or "Material")
        rows = rows_by_material.get(material_key, [])
        visible_rows = [row for row in rows if row.role in {"Base / Color", "Emissive"}]
        support_rows = [row for row in rows if row.role in {"Normal", "Height", "Material / Mask", "Detail Mask"}]
        ready_visible = [row for row in visible_rows if row.status == FINAL_PREVIEW_READY and row.confidence == "exact"]
        missing_visible = [row for row in visible_rows if row.status == FINAL_PREVIEW_MISSING_DDS]
        decode_failed_visible = [row for row in visible_rows if row.status == FINAL_PREVIEW_DECODE_FAILED]
        if ready_visible:
            status = FINAL_PREVIEW_READY
            detail = "Final sidecar visible texture binding resolves to a generated/copied DDS payload."
        elif missing_visible:
            status = FINAL_PREVIEW_MISSING_DDS
            detail = "Visible base/color/emissive sidecar binding points at a DDS that is not in the generated/copied payload set."
        elif decode_failed_visible:
            status = FINAL_PREVIEW_DECODE_FAILED
            detail = "Visible texture payload exists but failed preview decoding."
        elif support_rows:
            if any(row.role in {"Normal", "Height"} for row in support_rows):
                status = FINAL_PREVIEW_SUPPORT_MAPS_ONLY
                detail = "Only support maps are bound; normal/height/material maps do not add visible color."
            else:
                status = FINAL_PREVIEW_ADVANCED_SHADER_ONLY
                detail = "Only advanced material/mask shader inputs are bound; no base/color/emissive texture is available."
        else:
            status = FINAL_PREVIEW_MISSING_BASE
            detail = "No final base/color/emissive sidecar binding was found for this visible material."
        material_statuses.append(FinalPackageMaterialStatus(material_name=material_name, status=status, detail=detail))
        if status != FINAL_PREVIEW_READY:
            likely_grey_materials.append(material_name)

    material_status_by_name = {status.material_name: status.status for status in material_statuses}
    if material_statuses:
        status_by_key = {
            _material_key(status.material_name): status.status
            for status in material_statuses
        }
        binding_rows = [
            dataclasses.replace(row, material_status=status_by_key.get(_material_key(row.material_name), row.material_status))
            for row in binding_rows
        ]

    if likely_grey_materials:
        warnings.append(
            "This will likely be grey in-game for: "
            + ", ".join(likely_grey_materials[:8])
            + (" ..." if len(likely_grey_materials) > 8 else "")
        )
    if not sidecars and not binding_sources:
        warnings.append("No generated/copied material sidecar payloads were available for final package texture validation.")

    ready_materials = sum(1 for status in material_statuses if status.status == FINAL_PREVIEW_READY)
    contract_base_count = sum(1 for row in binding_rows if row.role in {"Base / Color", "Emissive"})
    contract_normal_count = sum(1 for row in binding_rows if row.role == "Normal")
    contract_material_count = sum(1 for row in binding_rows if row.role == "Material / Mask")
    ready_binding_count = sum(1 for row in binding_rows if row.status == FINAL_PREVIEW_READY)
    missing_binding_count = sum(1 for row in binding_rows if row.status == FINAL_PREVIEW_MISSING_DDS)
    visible_mesh_parts = len(tuple(getattr(preview_model, "meshes", ()) or ()))
    source_owned_color_count = sum(
        1
        for row in binding_rows
        if row.role in {"Base / Color", "Emissive"}
        and row.binding_source == FINAL_PREVIEW_BINDING_GENERATED
        and row.status == FINAL_PREVIEW_READY
    )
    inherited_color_count = sum(
        1
        for row in binding_rows
        if row.role in {"Base / Color", "Emissive"}
        and row.binding_source == FINAL_PREVIEW_BINDING_ORIGINAL
        and row.status == FINAL_PREVIEW_READY
    )
    missing_color_count = sum(
        1
        for row in binding_rows
        if row.role in {"Base / Color", "Emissive"}
        and row.status != FINAL_PREVIEW_READY
    )
    unresolved_stock_count = sum(
        1
        for row in binding_rows
        if _is_stock_or_shared_texture_path(row.texture_path)
        and row.status != FINAL_PREVIEW_READY
    )
    stock_preserved_count = sum(
        1
        for row in binding_rows
        if _is_stock_or_shared_texture_path(row.texture_path)
        and row.binding_source == FINAL_PREVIEW_BINDING_ORIGINAL
    )
    preflight_errors: List[str] = []
    for row in binding_rows:
        basename = PurePosixPath(str(row.texture_path or "").replace("\\", "/")).name.lower()
        stem = PurePosixPath(basename).stem.lower()
        parameter_key = re.sub(r"[^a-z0-9]+", "", str(row.parameter_name or "").lower())
        if row.binding_source == FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC:
            preflight_errors.append(
                f"Exact texture path mismatch: {row.sidecar_path} -> {row.texture_path}. A same-basename DDS exists, but the packaged path does not match."
            )
        if row.role in {"Base / Color", "Emissive"} and row.status in {FINAL_PREVIEW_MISSING_DDS, FINAL_PREVIEW_DECODE_FAILED}:
            preflight_errors.append(
                f"Visible color texture is not package-resolved: {row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
            )
        if row.role == "Base / Color" and stem.endswith(("_mg", "_sp", "_n", "_normal", "_disp", "_height")):
            preflight_errors.append(
                f"Support map is bound as visible base color: {row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
            )
        if (
            any(token in parameter_key for token in ("basecolor", "overlaycolor", "diffuse", "albedo", "colortexture"))
            and stem.endswith(("_mg", "_sp", "_n", "_normal", "_disp", "_height"))
        ):
            preflight_errors.append(
                f"Support map path is assigned to a visible color parameter: {row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
            )
        if (
            require_source_owned_colors
            and row.role in {"Base / Color", "Emissive"}
            and row.status == FINAL_PREVIEW_READY
            and row.binding_source != FINAL_PREVIEW_BINDING_GENERATED
        ):
            preflight_errors.append(
                f"Complete source-owned swap still inherits visible color from the game archive: {row.material_name} -> {row.texture_path}."
            )
    if orphan_payload_paths:
        preflight_errors.append(
            "Generated/copied DDS payloads are not referenced by parsed material sidecars: "
            + ", ".join(orphan_payload_paths[:8])
            + (" ..." if len(orphan_payload_paths) > 8 else "")
        )
    if require_source_owned_colors and not sidecars:
        preflight_errors.append("Complete source-owned swap has no packaged material sidecar payload to control visible color.")
    if require_source_owned_colors and source_visible_texture_count > final_visible_texture_count:
        preflight_errors.append(
            "Complete source-owned swap lost visible texture coverage in the final package contract "
            f"({final_visible_texture_count:,}/{source_visible_texture_count:,})."
        )
    preflight_errors = _dedupe(preflight_errors)

    summary_lines = [
        "Final Output Preview",
        f"Package root: {package_root_text or '-'}",
        f"Visible mesh parts: {visible_mesh_parts:,}",
        f"Parsed sidecar payloads: {len(sidecars):,}" + ("; using kept original sidecar bindings" if binding_sources and not sidecars else ""),
        f"Patched sidecar payloads: {generated_sidecar_count:,}",
        f"Generated/copied DDS payloads: {len(dds_by_path):,}",
        f"Ready material(s): {ready_materials:,}/{len(material_statuses):,}",
        f"Sidecar texture refs used: {len(binding_rows):,}; found {ready_binding_count:,}; missing {missing_binding_count:,}",
        f"Color authority: source-owned {source_owned_color_count:,}, inherited {inherited_color_count:,}, missing {missing_color_count:,}",
        (
            "Texture Contract: "
            f"base/color {contract_base_count:,}, normal {contract_normal_count:,}, "
            f"material/mask {contract_material_count:,}, stock/shared preserved {stock_preserved_count:,}, "
            f"unresolved stock {unresolved_stock_count:,}, orphan DDS {len(orphan_payload_paths):,}"
        ),
    ]
    if preflight_errors:
        summary_lines.append(f"Preflight blocker(s): {len(preflight_errors):,}")
    if likely_grey_materials:
        summary_lines.append(f"Likely grey material(s): {', '.join(likely_grey_materials[:8])}" + (" ..." if len(likely_grey_materials) > 8 else ""))
    if missing_paths:
        summary_lines.append(f"Missing final DDS payload path(s): {len(_dedupe(missing_paths)):,}")
    texture_resolution_manifest = _build_texture_resolution_manifest(binding_rows, _dedupe(warnings))
    if texture_resolution_manifest.rows:
        summary_lines.append(f"Texture resolution manifest rows: {len(texture_resolution_manifest.rows):,}")

    return FinalPackagePreviewResult(
        preview_model=preview_model,
        binding_rows=tuple(binding_rows),
        warnings=_dedupe(warnings),
        preflight_errors=preflight_errors,
        likely_grey_materials=_dedupe(likely_grey_materials),
        missing_texture_paths=_dedupe(missing_paths),
        summary_lines=summary_lines,
        material_statuses=tuple(material_statuses),
        texture_resolution_manifest=texture_resolution_manifest,
        package_root=package_root_text,
    )


def texture_plan_role_label(slot_kind: str, source_path: object = None) -> str:
    normalized = str(slot_kind or "").strip().lower()
    source_text = str(source_path or "").lower()
    if normalized == "base":
        if any(token in source_text for token in ("emissive", "glow", "illum")):
            return "Emissive"
        return "Base / Color"
    if normalized == "normal":
        return "Normal"
    if normalized == "height":
        return "Height"
    if normalized in {"material", "material_mask"}:
        return "Material / Mask"
    if normalized == "detail_mask":
        return "Detail Mask"
    if normalized in {"metallic", "roughness", "ao"}:
        return "Metallic / Roughness / AO"
    return "Material / Mask"


def texture_plan_control_description(slot_kind: str, source_path: object = None) -> str:
    normalized = str(slot_kind or "").strip().lower()
    if normalized == "base":
        source_text = str(source_path or "").lower()
        if any(token in source_text for token in ("emissive", "glow", "illum")):
            return "Glow/light contribution."
        return "Visible color; missing means likely grey."
    if normalized == "normal":
        return "Bumps/surface detail; does not add color."
    if normalized == "height":
        return "Depth/displacement/parallax; does not add color."
    if normalized in {"material", "material_mask"}:
        return "Packed material/mask data: roughness, metal, AO, dye/blend response, and shine depending on channels."
    if normalized == "detail_mask":
        return "Detail mask: selects shader/detail layers; useful when the source has a matching CD _mg texture."
    if normalized in {"metallic", "roughness", "ao"}:
        return "Detected standalone PBR map; not game-effective unless packed into or mapped to a compatible material mask."
    return "Advanced shader input; exported only when mapped to a compatible material parameter."


def texture_plan_status_for_slot(slot_kind: str, *, missing_base: bool = False) -> TexturePlanStatus:
    normalized = str(slot_kind or "").strip().lower()
    if missing_base:
        return TexturePlanStatus(
            TEXTURE_PLAN_STATUS_LIKELY_GREY,
            "red",
            "No base/color/emissive map is detected for this material.",
        )
    if normalized == "base":
        return TexturePlanStatus(TEXTURE_PLAN_STATUS_READY, "green", "Visible color source is present.")
    if normalized in {"material", "material_mask"}:
        return TexturePlanStatus(TEXTURE_PLAN_STATUS_READY, "green", "Packed material/mask source can be mapped to the game shader.")
    if normalized == "detail_mask":
        return TexturePlanStatus(TEXTURE_PLAN_STATUS_READY, "green", "Detail-mask source can be mapped to the game shader.")
    if normalized in {"normal", "height"}:
        return TexturePlanStatus(TEXTURE_PLAN_STATUS_SUPPORT_ONLY, "orange", "Support map only; it does not add visible color.")
    if normalized in {"metallic", "roughness", "ao"}:
        return TexturePlanStatus(
            TEXTURE_PLAN_STATUS_REVIEW,
            "yellow",
            "Standalone PBR map is detected but must be packed or mapped to a compatible material mask.",
        )
    return TexturePlanStatus(TEXTURE_PLAN_STATUS_IGNORED_ADVANCED, "gray", "Advanced or unsupported source map.")


def _basename_or_text(path_value: object) -> str:
    path_text = str(path_value or "").replace("\\", "/").strip()
    if not path_text:
        return ""
    return PurePosixPath(path_text).name or path_text


def build_dds_override_table_row(row_state: Mapping[str, object]) -> DdsOverrideTableRow:
    """Summarize one original DDS override row for compact UI display."""

    slot_kind = str(row_state.get("slot_kind") or row_state.get("original_slot_kind") or "material").strip().lower()
    source_path = str(row_state.get("source_path") or "").strip()
    suggested_source = str(row_state.get("suggested_source") or "").strip()
    target_path = _display_path(row_state.get("target_path"))
    target_name = str(row_state.get("target_name") or "").strip()
    part_display = str(row_state.get("part_display") or "").strip()
    parameter_name = str(row_state.get("parameter_name") or "").strip()
    role_label = str(row_state.get("role_label") or "").strip() or texture_plan_role_label(slot_kind, source_path)
    checked = bool(row_state.get("checked")) and bool(source_path)
    advanced = bool(row_state.get("advanced"))
    visualized = bool(row_state.get("visualized", True))

    if part_display and target_name and part_display.lower() != target_name.lower():
        part_material = f"{part_display} / {target_name}"
    else:
        part_material = part_display or target_name or "Original slot"
    fallback_index_value = row_state.get("target_index", None)
    try:
        fallback_index = int(fallback_index_value)
    except (TypeError, ValueError):
        fallback_index = None
    part_label = simplified_part_label(part_display or target_name, fallback_index=fallback_index)

    target_basename = _basename_or_text(target_path)
    original_slot = parameter_name or target_basename or "DDS slot"
    if parameter_name and target_basename:
        original_slot = f"{parameter_name}: {target_basename}"

    if checked:
        override_source = _basename_or_text(source_path) or "Assigned"
    elif suggested_source:
        override_source = f"Suggested: {_basename_or_text(suggested_source)}"
    else:
        override_source = "Keep original"

    if checked:
        if slot_kind == "base":
            status = texture_plan_status_for_slot("base")
        elif slot_kind in {"normal", "height"}:
            status = texture_plan_status_for_slot(slot_kind)
        elif slot_kind in {"material", "material_mask", "detail_mask"}:
            status = texture_plan_status_for_slot("material")
        elif slot_kind in {"metallic", "roughness", "ao"}:
            status = texture_plan_status_for_slot(slot_kind)
        else:
            status = texture_plan_status_for_slot(slot_kind)
    elif slot_kind == "base":
        status = texture_plan_status_for_slot("base", missing_base=True)
    elif slot_kind in {"normal", "height"}:
        status = texture_plan_status_for_slot(slot_kind)
    elif advanced or not visualized:
        status = TexturePlanStatus(
            TEXTURE_PLAN_STATUS_IGNORED_ADVANCED,
            "gray",
            "Manual compatibility row; keep original unless repairing this shader slot.",
        )
    elif suggested_source:
        status = TexturePlanStatus(
            TEXTURE_PLAN_STATUS_REVIEW,
            "yellow",
            "Suggested source exists but has not been explicitly assigned.",
        )
    else:
        status = TexturePlanStatus(
            TEXTURE_PLAN_STATUS_REVIEW,
            "yellow",
            "No replacement source is assigned for this original DDS slot.",
        )

    return DdsOverrideTableRow(
        part_material=part_material,
        role=role_label,
        original_slot=original_slot,
        override_source=override_source,
        target_dds=target_path,
        status=status,
        controls=texture_plan_control_description(slot_kind, source_path or suggested_source or target_path),
        slot_kind=slot_kind,
        target_name=target_name,
        part_label=part_label,
        full_part_material=part_material,
    )


def texture_plan_status_for_material(slot_kinds: Sequence[str]) -> TexturePlanStatus:
    normalized = {str(slot_kind or "").strip().lower() for slot_kind in slot_kinds}
    if normalized & {"base"}:
        return TexturePlanStatus(TEXTURE_PLAN_STATUS_READY, "green", "Base/color source is present.")
    return texture_plan_status_for_slot("base", missing_base=True)


def build_replacement_texture_plan_rows(
    texture_sets: Mapping[str, object],
    *,
    final_path_for_source: Optional[Callable[[Path], str]] = None,
    part_summary_for_material: Optional[Callable[[str], str]] = None,
) -> Tuple[ReplacementTexturePlanRow, ...]:
    rows: List[ReplacementTexturePlanRow] = []
    for texture_set in sorted(texture_sets.values(), key=lambda item: str(getattr(item, "material_name", "") or "").lower()):
        material_name = str(getattr(texture_set, "material_name", "") or "Replacement").strip() or "Replacement"
        part_summary = part_summary_for_material(material_name) if part_summary_for_material is not None else ""
        part_material = f"{part_summary} / {material_name}" if part_summary and part_summary != material_name else material_name
        part_label = simplified_part_label(part_summary or material_name)
        slots = getattr(texture_set, "slots", {}) or {}
        if "base" not in {str(key).lower() for key in slots}:
            rows.append(
                ReplacementTexturePlanRow(
                    part_material=part_material,
                    role="Base / Color",
                    source="Missing",
                    final_path="-",
                    status=texture_plan_status_for_slot("base", missing_base=True),
                    controls=texture_plan_control_description("base"),
                    slot_kind="base",
                    game_effective=False,
                    part_label=part_label,
                    full_part_material=part_material,
                )
            )
        for slot_kind, slot in sorted(
            slots.items(),
            key=lambda item: {"base": 0, "normal": 1, "height": 2, "material": 3, "metallic": 4, "roughness": 5, "ao": 6}.get(
                str(item[0]).lower(),
                20,
            ),
        ):
            normalized_slot = str(slot_kind or getattr(slot, "slot_kind", "") or "").strip().lower()
            source_path = getattr(slot, "source_path", Path())
            source = source_path.name if isinstance(source_path, Path) else str(source_path or "")
            if normalized_slot in {"metallic", "roughness", "ao"}:
                final_path = "Pack/map to Material / Mask"
                game_effective = False
            elif final_path_for_source is not None and isinstance(source_path, Path):
                final_path = final_path_for_source(source_path)
                game_effective = True
            else:
                final_path = ""
                game_effective = normalized_slot in {"base", "normal", "height", "material"}
            rows.append(
                ReplacementTexturePlanRow(
                    part_material=part_material,
                    role=texture_plan_role_label(normalized_slot, source_path),
                    source=source,
                    final_path=final_path,
                    status=texture_plan_status_for_slot(normalized_slot),
                    controls=texture_plan_control_description(normalized_slot, source_path),
                    slot_kind=normalized_slot,
                    game_effective=game_effective,
                    part_label=part_label,
                    full_part_material=part_material,
                )
            )
    return tuple(rows)
