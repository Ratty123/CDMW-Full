from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import re
import shutil
import struct
import zipfile
from collections import defaultdict
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
from cdmw.core.pipeline import inspect_crimson_dds
from cdmw.models import ModelPreviewData, ModelPreviewMesh, PreviewMaterialTextureInput
from cdmw.modding.asset_replacement import classify_texture_binding
from cdmw.modding.mesh_parser import _find_pac_descriptors, _parse_par_sections, parse_mesh
from cdmw.modding.pac_xml_profiles import build_pac_xml_material_authority_report
from cdmw.rendering.asset_fidelity_preflight import normal_y_policy_report


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

SOURCE_OWNED_FORBIDDEN_ORIGINAL_PARAMETER_TOKENS = (
    "grime",
    "detaildiffuse",
    "detailmask",
    "detailnormal",
    "detailheight",
    "detailmaterial",
    "dyeing",
    "texturelayer",
    "damage",
    "heighttexture",
    "materialtexture",
    "colorblending",
)

SOURCE_OWNED_ALLOWED_RELIEF_SUPPORT_PARAMETER_TOKENS = (
    "heighttexture",
    "detailmask",
    "detailnormal",
    "detailheight",
)

MATERIAL_PREFLIGHT_OVERRIDE_WARNING = (
    "Material preflight override used; in-game result may inherit original tint/gloss/layers or render grey/missing textures."
)

SOURCE_TEXTURE_FACT_MAX_IMAGE_BYTES = 256 * 1024 * 1024

MATERIAL_PREFLIGHT_HARD_BLOCKER_TOKENS = (
    "visible color texture is not package-resolved",
    "exact texture path mismatch",
    "support map is bound as visible base color",
    "support map path is assigned to a visible color parameter",
    "pac runtime abi",
    "wrapper was emitted outside _submeshresources",
    "duplicates skinnedmeshmaterialwrapper itemid",
    "duplicates material parameter itemid",
    "material shader name is the source material label",
    "_submeshresources idbase",
    "_submeshresources wrapper order does not match",
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
class CDMaterialBindingContract:
    material_key: str
    display_name: str
    fatal_errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    source_visible_binding_count: int = 0


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


@dataclass(slots=True, frozen=True)
class FinalPackageMaterialAuthorityReport:
    schema: str = "cdmw_material_authority_report_v1"
    source_path: str = ""
    package_root: str = ""
    authority_contract: str = ""
    target_sections: Tuple[Mapping[str, object], ...] = ()
    source_materials: Tuple[Mapping[str, object], ...] = ()
    texture_outputs: Tuple[Mapping[str, object], ...] = ()
    routing: Tuple[Mapping[str, object], ...] = ()
    sidecar_reports: Tuple[Mapping[str, object], ...] = ()
    sidecar_outputs: Tuple[Mapping[str, object], ...] = ()
    preview_settings: Mapping[str, object] = field(default_factory=dict)
    unknown_material_response_parameters: Tuple[Mapping[str, object], ...] = ()
    risk_flags: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    preflight_errors: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "source_path": self.source_path,
            "package_root": self.package_root,
            "authority_contract": self.authority_contract,
            "target_sections": [dict(row) for row in self.target_sections],
            "source_materials": [dict(row) for row in self.source_materials],
            "texture_outputs": [dict(row) for row in self.texture_outputs],
            "routing": [dict(row) for row in self.routing],
            "sidecar_reports": [dict(row) for row in self.sidecar_reports],
            "sidecar_outputs": [dict(row) for row in self.sidecar_outputs],
            "preview_settings": dict(self.preview_settings),
            "unknown_material_response_parameters": [dict(row) for row in self.unknown_material_response_parameters],
            "risk_flags": list(self.risk_flags),
            "warnings": list(self.warnings),
            "preflight_errors": list(self.preflight_errors),
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
    material_authority_report: FinalPackageMaterialAuthorityReport = field(default_factory=FinalPackageMaterialAuthorityReport)
    package_root: str = ""


def material_preflight_hard_blockers(lines: Sequence[str]) -> Tuple[str, ...]:
    """Return material preflight blockers that are unsafe to bypass."""

    hard: List[str] = []
    for line in tuple(lines or ()):
        text = str(line or "").strip()
        if not text:
            continue
        normalized = text.casefold()
        if any(token in normalized for token in MATERIAL_PREFLIGHT_HARD_BLOCKER_TOKENS):
            hard.append(text)
    return tuple(_dedupe(hard))


def apply_material_preflight_override(result: FinalPackagePreviewResult) -> Tuple[str, ...]:
    """Downgrade overridable material preflight errors to warnings.

    Returns hard blockers that were left in place.
    """

    blockers = tuple(str(line) for line in tuple(getattr(result, "preflight_errors", ()) or ()) if str(line or "").strip())
    hard = material_preflight_hard_blockers(blockers)
    if not blockers or hard:
        return hard
    if MATERIAL_PREFLIGHT_OVERRIDE_WARNING not in result.warnings:
        result.warnings.append(MATERIAL_PREFLIGHT_OVERRIDE_WARNING)
    for line in blockers:
        warning = f"Unsafe material preflight override: {line}"
        if warning not in result.warnings:
            result.warnings.append(warning)
    result.preflight_errors.clear()
    return ()


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
    note: str = ""


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


def _decode_sidecar_bytes(payload: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "cp1252"):
        try:
            return bytes(payload or b"").decode(encoding, errors="replace")
        except Exception:
            continue
    return ""


def _spec_source_file_text(spec: MeshImportSupplementalFileSpec) -> str:
    source_path = getattr(spec, "source_path", None)
    if not isinstance(source_path, Path):
        return ""
    try:
        expanded = source_path.expanduser()
    except OSError:
        return ""
    if not expanded.is_file():
        return ""
    try:
        return _decode_sidecar_bytes(expanded.read_bytes())
    except OSError:
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


def _pac_xml_material_wrapper_structure_errors(sidecar_text: str, sidecar_path: str) -> Tuple[str, ...]:
    normalized_path = str(sidecar_path or "").replace("\\", "/").lower()
    if not (normalized_path.endswith(".pac_xml") or normalized_path.endswith(".pac.xml")):
        return ()
    text = str(sidecar_text or "")
    if "<ModelProperty" not in text or "<SkinnedMeshMaterialWrapper" not in text:
        return ()
    tag_pattern = re.compile(r"<\s*(/?)\s*([A-Za-z0-9_:.-]+)\b([^>]*)>", flags=re.IGNORECASE | re.DOTALL)
    stack: List[Tuple[str, str, int]] = []
    item_ids_by_container: Dict[int, Dict[str, str]] = {}
    errors: List[str] = []
    for match in tag_pattern.finditer(text):
        is_close = bool(match.group(1))
        raw_tag = match.group(2)
        tag = raw_tag.split(":")[-1]
        attrs = match.group(3) or ""
        if is_close:
            normalized_tag = tag.lower()
            for index in range(len(stack) - 1, -1, -1):
                if stack[index][0].lower() == normalized_tag:
                    del stack[index:]
                    break
            continue
        self_closing = attrs.rstrip().endswith("/")
        if tag.lower() == "skinnedmeshmaterialwrapper":
            name_match = re.search(
                r'(?:_subMeshName|subMeshName|SubMeshName|Name|name)="([^"]+)"',
                attrs,
                flags=re.IGNORECASE,
            )
            wrapper_name = str(name_match.group(1) if name_match else "unnamed wrapper").strip()
            submesh_vector = next(
                (
                    ancestor
                    for ancestor in reversed(stack)
                    if ancestor[0].lower() == "vector"
                    and re.search(
                        r'\b(?:Name|name|_name)="_subMeshResources"',
                        ancestor[1],
                        flags=re.IGNORECASE,
                    )
                ),
                None,
            )
            if submesh_vector is None:
                errors.append(
                    f"{wrapper_name} wrapper was emitted outside _subMeshResources in {PurePosixPath(sidecar_path).name}."
                )
            else:
                item_match = re.search(r'\bItemID="(\d+)"', attrs, flags=re.IGNORECASE)
                if item_match is not None:
                    item_id = item_match.group(1)
                    by_id = item_ids_by_container.setdefault(submesh_vector[2], {})
                    previous = by_id.get(item_id)
                    if previous is not None:
                        errors.append(
                            f"{wrapper_name} duplicates SkinnedMeshMaterialWrapper ItemID {item_id} with {previous} "
                            f"inside _subMeshResources in {PurePosixPath(sidecar_path).name}."
                        )
                    else:
                        by_id[item_id] = wrapper_name
        if not self_closing:
            stack.append((tag, attrs, match.start()))
    wrapper_pattern = re.compile(
        r"<SkinnedMeshMaterialWrapper\b(?P<attrs>[^>]*)>(?P<body>.*?)</SkinnedMeshMaterialWrapper>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    parameter_pattern = re.compile(
        r"<MaterialParameter[A-Za-z0-9_:.-]*\b(?P<attrs>[^>]*)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for wrapper_match in wrapper_pattern.finditer(text):
        wrapper_attrs = wrapper_match.group("attrs") or ""
        name_match = re.search(
            r'(?:_subMeshName|subMeshName|SubMeshName|Name|name)="([^"]+)"',
            wrapper_attrs,
            flags=re.IGNORECASE,
        )
        wrapper_name = str(name_match.group(1) if name_match else "unnamed wrapper").strip()
        parameter_names_by_item_id: Dict[str, str] = {}
        for parameter_match in parameter_pattern.finditer(wrapper_match.group("body") or ""):
            parameter_attrs = parameter_match.group("attrs") or ""
            item_match = re.search(r'\bItemID="(\d+)"', parameter_attrs, flags=re.IGNORECASE)
            if item_match is None:
                continue
            parameter_name_match = re.search(
                r'(?:StringItemID|_name|Name|name)="([^"]+)"',
                parameter_attrs,
                flags=re.IGNORECASE,
            )
            parameter_name = str(parameter_name_match.group(1) if parameter_name_match else "unnamed parameter").strip()
            item_id = item_match.group(1)
            previous = parameter_names_by_item_id.get(item_id)
            if previous is not None and previous != parameter_name:
                errors.append(
                    f"{wrapper_name} duplicates material parameter ItemID {item_id} for {previous} and {parameter_name} "
                    f"in {PurePosixPath(sidecar_path).name}."
                )
            else:
                parameter_names_by_item_id[item_id] = parameter_name
    return tuple(_dedupe(errors))


def _pac_xml_submesh_resource_wrapper_names(sidecar_text: str, sidecar_path: str) -> Tuple[str, ...]:
    normalized_path = str(sidecar_path or "").replace("\\", "/").lower()
    if not (normalized_path.endswith(".pac_xml") or normalized_path.endswith(".pac.xml")):
        return ()
    text = str(sidecar_text or "")
    if "<ModelProperty" not in text or "<SkinnedMeshMaterialWrapper" not in text:
        return ()
    tag_pattern = re.compile(r"<\s*(/?)\s*([A-Za-z0-9_:.-]+)\b([^>]*)>", flags=re.IGNORECASE | re.DOTALL)
    stack: List[Tuple[str, str, int]] = []
    names: List[str] = []
    for match in tag_pattern.finditer(text):
        is_close = bool(match.group(1))
        tag = match.group(2).split(":")[-1]
        attrs = match.group(3) or ""
        if is_close:
            normalized_tag = tag.lower()
            for index in range(len(stack) - 1, -1, -1):
                if stack[index][0].lower() == normalized_tag:
                    del stack[index:]
                    break
            continue
        self_closing = attrs.rstrip().endswith("/")
        if tag.lower() == "skinnedmeshmaterialwrapper":
            submesh_vector = next(
                (
                    ancestor
                    for ancestor in reversed(stack)
                    if ancestor[0].lower() == "vector"
                    and re.search(
                        r'\b(?:Name|name|_name)="_subMeshResources"',
                        ancestor[1],
                        flags=re.IGNORECASE,
                    )
                ),
                None,
            )
            if submesh_vector is not None:
                name_match = re.search(
                    r'(?:_subMeshName|subMeshName|SubMeshName|Name|name)="([^"]+)"',
                    attrs,
                    flags=re.IGNORECASE,
                )
                wrapper_name = str(name_match.group(1) if name_match else "").strip()
                if wrapper_name:
                    names.append(wrapper_name)
        if not self_closing:
            stack.append((tag, attrs, match.start()))
    return tuple(_dedupe(names))


def _pac_xml_material_shader_name_errors(sidecar_text: str, sidecar_path: str) -> Tuple[str, ...]:
    normalized_path = str(sidecar_path or "").replace("\\", "/").lower()
    if not (normalized_path.endswith(".pac_xml") or normalized_path.endswith(".pac.xml")):
        return ()
    errors: List[str] = []
    wrapper_pattern = re.compile(
        r"<SkinnedMeshMaterialWrapper\b(?P<attrs>[^>]*)>.*?</SkinnedMeshMaterialWrapper>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in wrapper_pattern.finditer(str(sidecar_text or "")):
        block = match.group(0)
        attrs = match.group("attrs") or ""
        name_match = re.search(
            r'(?:_subMeshName|subMeshName|SubMeshName|Name|name)="([^"]+)"',
            attrs,
            flags=re.IGNORECASE,
        )
        material_match = re.search(r'<Material\b[^>]*\b_materialName="([^"]*)"', block, flags=re.IGNORECASE | re.DOTALL)
        wrapper_name = str(name_match.group(1) if name_match else "unnamed wrapper").strip()
        material_name = str(material_match.group(1) if material_match else "").strip()
        if not material_name:
            continue
        if _material_key(material_name) == _material_key(wrapper_name):
            errors.append(
                f"{wrapper_name} material shader name is the source material label ({material_name}) in {PurePosixPath(sidecar_path).name}; "
                "complete source-owned swap must keep a game shader family such as SkinnedMeshStandard_Ver2."
            )
    return tuple(_dedupe(errors))


def _pac_xml_submesh_resource_order_errors(
    sidecar_wrapper_names: Sequence[str],
    visible_material_names: Sequence[str],
) -> Tuple[str, ...]:
    visible_names = [
        str(name or "").strip()
        for name in tuple(visible_material_names or ())
        if _material_key(name)
    ]
    if len(visible_names) <= 1:
        return ()
    visible_keys = [_material_key(name) for name in visible_names]
    visible_key_set = set(visible_keys)
    sidecar_names = [
        str(name or "").strip()
        for name in tuple(sidecar_wrapper_names or ())
        if _material_key(name) in visible_key_set
    ]
    if len(sidecar_names) < len(visible_names):
        return ()
    sidecar_names = sidecar_names[: len(visible_names)]
    sidecar_keys = [_material_key(name) for name in sidecar_names]
    if sidecar_keys == visible_keys:
        return ()
    return (
        "Complete source-owned swap PAC XML _subMeshResources wrapper order does not match rebuilt PAC draw order. "
        f"PAC: {', '.join(visible_names[:8])}; sidecar: {', '.join(sidecar_names[:8])}."
        + (" ..." if len(visible_names) > 8 else ""),
    )


def _pac_xml_submesh_resource_idbase_errors(sidecar_text: str, sidecar_path: str) -> Tuple[str, ...]:
    normalized_path = str(sidecar_path or "").replace("\\", "/").lower()
    if not (normalized_path.endswith(".pac_xml") or normalized_path.endswith(".pac.xml")):
        return ()
    text = str(sidecar_text or "")
    errors: List[str] = []
    tag_pattern = re.compile(r"<\s*(/?)\s*([A-Za-z0-9_:.-]+)\b([^>]*)>", flags=re.IGNORECASE | re.DOTALL)
    stack: List[Tuple[str, bool, int, int, str]] = []

    def validate_vector(attrs: str, body: str) -> None:
        item_ids: List[int] = []
        for item_match in re.finditer(r"<SkinnedMeshMaterialWrapper\b[^>]*\bItemID=\"(\d+)\"", body, flags=re.IGNORECASE | re.DOTALL):
            try:
                item_ids.append(int(item_match.group(1)))
            except ValueError:
                continue
        if not item_ids:
            return
        idbase_match = re.search(r'\bIdBase="(\d+)"', attrs, flags=re.IGNORECASE)
        if idbase_match is None:
            errors.append(
                f"_subMeshResources in {PurePosixPath(sidecar_path).name} has material wrapper ItemID(s) but no IdBase."
            )
            return
        try:
            idbase = int(idbase_match.group(1))
        except ValueError:
            idbase = -1
        required = max(item_ids)
        if idbase < required:
            errors.append(
                f"_subMeshResources IdBase {idbase} is lower than source-owned material wrapper ItemID {required} in {PurePosixPath(sidecar_path).name}."
            )

    for match in tag_pattern.finditer(text):
        is_close = bool(match.group(1))
        tag = match.group(2).split(":")[-1].lower()
        attrs = match.group(3) or ""
        if is_close:
            for index in range(len(stack) - 1, -1, -1):
                open_tag, is_target, _start, open_end, open_attrs = stack[index]
                if open_tag.lower() != tag:
                    continue
                del stack[index:]
                if is_target:
                    validate_vector(open_attrs, text[open_end:match.start()])
                break
            continue
        if attrs.rstrip().endswith("/"):
            continue
        is_target = (
            tag == "vector"
            and re.search(r'\b(?:Name|name|_name)="_subMeshResources"', attrs, flags=re.IGNORECASE) is not None
        )
        stack.append((tag, is_target, match.start(), match.end(), attrs))
    return tuple(_dedupe(errors))


def _pac_runtime_abi_preflight_errors(
    rebuilt_data: bytes,
    preview_result: MeshImportPreviewResult,
) -> Tuple[str, ...]:
    data = bytes(rebuilt_data or b"")
    parsed_mesh = getattr(preview_result, "parsed_mesh", None)
    if not data or data[:4] != b"PAR " or not str(getattr(parsed_mesh, "format", "") or "").lower() == "pac":
        return ()
    planned_sections = tuple(getattr(preview_result, "source_owned_output_draw_sections", ()) or ())
    if not planned_sections:
        return ()
    try:
        sections = _parse_par_sections(data)
        sec0 = next((section for section in sections if int(section.get("index", -1)) == 0), None)
        if not sec0:
            return ("Complete source-owned swap PAC runtime ABI validation failed: section 0 is missing.",)
        n_lods = data[int(sec0["offset"]) + 4] if int(sec0["size"]) >= 5 else 0
        descriptors = _find_pac_descriptors(data, int(sec0["offset"]), int(sec0["size"]), n_lods)
    except Exception as exc:
        return (f"Complete source-owned swap PAC runtime ABI validation failed: {exc}",)

    errors: List[str] = []
    if len(descriptors) != len(planned_sections):
        errors.append(
            "Complete source-owned swap PAC runtime ABI changed descriptor count: "
            f"{len(descriptors):,} descriptor(s), expected {len(planned_sections):,} original runtime slot(s)."
        )

    total_vertices = int(getattr(parsed_mesh, "total_vertices", 0) or 0)
    if total_vertices > 1000 and int(sec0.get("size", 0) or 0) < 1024:
        errors.append(
            "Complete source-owned swap PAC runtime ABI has a suspiciously small section 0 "
            f"({int(sec0.get('size', 0) or 0):,} bytes); original descriptor/metadata tail was likely rebuilt instead of preserved."
        )

    for index, (desc, planned) in enumerate(zip(descriptors, planned_sections)):
        expected_name = str(getattr(planned, "runtime_slot_name", "") or "").strip()
        expected_material = str(getattr(planned, "runtime_material_name", "") or "").strip()
        if expected_name and _material_key(getattr(desc, "name", "")) != _material_key(expected_name):
            errors.append(
                f"Complete source-owned swap PAC runtime ABI changed draw slot {index} name: "
                f"{getattr(desc, 'name', '')} != {expected_name}."
            )
        if expected_material and _material_key(getattr(desc, "material", "")) != _material_key(expected_material):
            errors.append(
                f"Complete source-owned swap PAC runtime ABI changed draw slot {index} material: "
                f"{getattr(desc, 'material', '')} != {expected_material}."
            )
        vertex_counts = [int(value or 0) for value in tuple(getattr(desc, "vertex_counts", ()) or ())]
        index_counts = [int(value or 0) for value in tuple(getattr(desc, "index_counts", ()) or ())]
        active_vertex_counts = [value for value in vertex_counts[: int(getattr(desc, "stored_lod_count", 0) or 0)] if value > 0]
        active_index_counts = [value for value in index_counts[: int(getattr(desc, "stored_lod_count", 0) or 0)] if value > 0]
        if len(active_vertex_counts) > 1 and any(active_vertex_counts[i] > active_vertex_counts[i - 1] for i in range(1, len(active_vertex_counts))):
            errors.append(f"Complete source-owned swap PAC draw slot {index} has non-monotonic LOD vertex counts: {active_vertex_counts}.")
        if len(active_index_counts) > 1 and any(active_index_counts[i] > active_index_counts[i - 1] for i in range(1, len(active_index_counts))):
            errors.append(f"Complete source-owned swap PAC draw slot {index} has non-monotonic LOD index counts: {active_index_counts}.")
        if (
            len(active_vertex_counts) > 1
            and len(set(active_vertex_counts)) == 1
            and len(active_index_counts) > 1
            and len(set(active_index_counts)) == 1
            and active_vertex_counts[0] > 8
            and active_index_counts[0] > 24
        ):
            errors.append(
                f"Complete source-owned swap PAC draw slot {index} duplicates full LOD geometry across all LODs "
                f"({active_vertex_counts[0]:,} vertices, {active_index_counts[0]:,} indices)."
            )
    return tuple(_dedupe(errors))


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


def _build_material_authority_report(
    preview_result: MeshImportPreviewResult,
    *,
    source_path: str,
    final_preview_model: ModelPreviewData,
    package_root: str,
    authority_contract: str,
    sidecars: Mapping[str, Tuple[str, MeshImportSupplementalFileSpec]],
    dds_by_path: Mapping[str, _FinalPayload],
    binding_rows: Sequence[FinalPackageBindingRow],
    material_statuses: Sequence[FinalPackageMaterialStatus],
    texture_resolution_manifest: TextureResolutionManifest,
    warnings: Sequence[str],
    preflight_errors: Sequence[str],
    require_source_owned_colors: bool,
    strict_source_owned_material_contract: bool,
    allow_inherited_layer_color_bindings: bool,
    render_settings: object = None,
) -> FinalPackageMaterialAuthorityReport:
    contract = str(authority_contract or "").strip() or (
        "true_source_authority" if strict_source_owned_material_contract else "runtime_xml_preserve" if allow_inherited_layer_color_bindings else ""
    )
    sidecar_reports: List[Mapping[str, object]] = []
    sidecar_outputs: List[Mapping[str, object]] = []
    unknowns: List[Mapping[str, object]] = []
    inherited_count = 0
    for sidecar_path, spec in sidecars.values():
        sidecar_text = _spec_payload_text(spec)
        if not sidecar_text.strip():
            sidecar_outputs.append(_material_authority_sidecar_output_row(sidecar_path, spec))
            continue
        report = build_pac_xml_material_authority_report(
            sidecar_text,
            sidecar_path,
            authority_contract=contract or "true_source_authority",
        )
        report_dict = report.to_dict()
        sidecar_reports.append(report_dict)
        sidecar_outputs.append(_material_authority_sidecar_output_row(sidecar_path, spec, report_dict=report_dict))
        inherited_count += len(report.inherited_influence_parameters)
        for parameter in report.unknown_material_response_parameters:
            parameter_row = parameter.to_dict()
            parameter_row["sidecar_path"] = sidecar_path
            unknowns.append(parameter_row)

    normal_y_mode = _material_authority_render_normal_y_mode(render_settings)
    routing = tuple(_material_authority_routing_row(row) for row in binding_rows)
    target_sections = tuple(_material_authority_target_section_rows(preview_result, material_statuses, binding_rows))
    source_materials = _material_authority_source_material_rows_for_report(preview_result, source_path)
    texture_outputs = tuple(
        _material_authority_texture_output_row(
            payload,
            binding_rows=binding_rows,
            source_materials=source_materials,
            normal_y_mode=normal_y_mode,
        )
        for _key, payload in sorted(dds_by_path.items(), key=lambda item: item[1].final_path.lower())
    )
    risk_flags = _material_authority_risk_flags(
        binding_rows=binding_rows,
        texture_outputs=texture_outputs,
        sidecar_reports=sidecar_reports,
        source_materials=source_materials,
        unknowns=unknowns,
        inherited_count=inherited_count,
        warnings=warnings,
        preflight_errors=preflight_errors,
        require_source_owned_colors=require_source_owned_colors,
    )
    preview_settings = _material_authority_preview_settings(
        preview_result,
        final_preview_model,
        texture_resolution_manifest,
        require_source_owned_colors=require_source_owned_colors,
        strict_source_owned_material_contract=strict_source_owned_material_contract,
        allow_inherited_layer_color_bindings=allow_inherited_layer_color_bindings,
        render_settings=render_settings,
    )
    return FinalPackageMaterialAuthorityReport(
        source_path=str(source_path or "").replace("\\", "/"),
        package_root=str(package_root or "").replace("\\", "/"),
        authority_contract=contract,
        target_sections=target_sections,
        source_materials=source_materials,
        texture_outputs=texture_outputs,
        routing=routing,
        sidecar_reports=tuple(sidecar_reports),
        sidecar_outputs=tuple(sidecar_outputs),
        preview_settings=preview_settings,
        unknown_material_response_parameters=tuple(unknowns),
        risk_flags=risk_flags,
        warnings=tuple(str(warning) for warning in tuple(warnings or ()) if str(warning or "").strip()),
        preflight_errors=tuple(str(error) for error in tuple(preflight_errors or ()) if str(error or "").strip()),
    )


def _material_authority_sidecar_output_row(
    sidecar_path: str,
    spec: MeshImportSupplementalFileSpec,
    *,
    report_dict: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    payload = _spec_payload_bytes(spec)
    payload_text = _decode_sidecar_bytes(payload)
    source_path = getattr(spec, "source_path", None)
    source_text = source_path.as_posix() if isinstance(source_path, Path) else str(source_path or "")
    kind = str(getattr(spec, "kind", "") or "")
    report_mapping = dict(report_dict or {})
    return {
        "target_path": str(sidecar_path or "").replace("\\", "/"),
        "source_path": source_text.replace("\\", "/"),
        "kind": kind,
        "generated": bool(payload) or kind.endswith("_generated") or kind == "sidecar_generated",
        "used_for_preview": bool(getattr(spec, "used_for_preview", False)),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest() if payload else "",
        "note": str(getattr(spec, "note", "") or ""),
        "authority_status": str(report_mapping.get("status", "") or ""),
        "wrapper_count": int(report_mapping.get("wrapper_count", 0) or 0),
        "submesh_binding_count": len(tuple(report_mapping.get("submesh_bindings", ()) or ())),
        "parameter_count": int(report_mapping.get("parameter_count", 0) or 0),
        "unknown_material_response_count": len(tuple(report_mapping.get("unknown_material_response_parameters", ()) or ())),
        "inherited_influence_count": len(tuple(report_mapping.get("inherited_influence_parameters", ()) or ())),
        "neutralization_action_count": len(tuple(report_mapping.get("neutralization_actions", ()) or ())),
        "pac_xml_edit_summary": _material_authority_sidecar_edit_summary(sidecar_path, spec, payload, payload_text),
    }


def _material_authority_sidecar_edit_summary(
    sidecar_path: str,
    spec: MeshImportSupplementalFileSpec,
    payload: bytes,
    payload_text: str,
) -> Mapping[str, object]:
    source_text = _spec_source_file_text(spec)
    source_payload = source_text.encode("utf-8") if source_text else b""
    source_bindings = tuple(parse_texture_sidecar_bindings(source_text, sidecar_path=sidecar_path)) if source_text else ()
    payload_bindings = tuple(parse_texture_sidecar_bindings(payload_text, sidecar_path=sidecar_path)) if payload_text else ()
    changes = _material_authority_sidecar_texture_ref_changes(source_bindings, payload_bindings)
    structural_compare = _material_authority_sidecar_structural_compare(sidecar_path, source_text, payload_text)
    status = "payload_empty" if not payload_text.strip() else "source_compared" if source_text.strip() else "source_unavailable"
    changed = bool(source_text.strip() and source_text != payload_text)
    return {
        "status": status,
        "changed_from_source": changed,
        "source_available": bool(source_text.strip()),
        "source_sha256": hashlib.sha256(source_payload).hexdigest() if source_payload else "",
        "payload_sha256": hashlib.sha256(payload).hexdigest() if payload else "",
        "source_texture_ref_count": len(source_bindings),
        "payload_texture_ref_count": len(payload_bindings),
        "texture_refs_added_count": sum(1 for row in changes if row["change"] == "added"),
        "texture_refs_removed_count": sum(1 for row in changes if row["change"] == "removed"),
        "texture_refs_changed_count": sum(1 for row in changes if row["change"] == "changed"),
        "texture_ref_changes": changes,
        "changed_parameter_names": tuple(
            sorted({str(row.get("parameter_name", "") or "") for row in changes if str(row.get("parameter_name", "") or "")})
        ),
        **structural_compare,
    }


def _material_authority_sidecar_structural_compare(
    sidecar_path: str,
    source_text: str,
    payload_text: str,
) -> Mapping[str, object]:
    source_report = _material_authority_sidecar_report_dict(source_text, sidecar_path)
    payload_report = _material_authority_sidecar_report_dict(payload_text, sidecar_path)
    if not source_report or not payload_report:
        return {
            "structural_compare_status": "source_unavailable" if not source_report else "payload_unavailable",
            "wrapper_order_preserved": False,
            "wrapper_item_ids_preserved": False,
            "submesh_bindings_preserved": False,
            "submesh_item_ids_preserved": False,
            "parameter_abi_preserved": False,
            "source_wrapper_order_count": len(tuple(source_report.get("wrapper_order", ()) or ())) if source_report else 0,
            "payload_wrapper_order_count": len(tuple(payload_report.get("wrapper_order", ()) or ())) if payload_report else 0,
            "source_submesh_binding_count": len(tuple(source_report.get("submesh_bindings", ()) or ())) if source_report else 0,
            "payload_submesh_binding_count": len(tuple(payload_report.get("submesh_bindings", ()) or ())) if payload_report else 0,
            "source_parameter_abi_count": len(_material_authority_parameter_abi_rows(source_report)) if source_report else 0,
            "payload_parameter_abi_count": len(_material_authority_parameter_abi_rows(payload_report)) if payload_report else 0,
        }
    source_wrappers = _material_authority_named_rows(
        source_report.get("wrapper_order"),
        ("order", "wrapper_name", "item_id", "shader_name"),
    )
    payload_wrappers = _material_authority_named_rows(
        payload_report.get("wrapper_order"),
        ("order", "wrapper_name", "item_id", "shader_name"),
    )
    source_wrapper_ids = _material_authority_named_rows(source_report.get("wrapper_order"), ("order", "wrapper_name", "item_id"))
    payload_wrapper_ids = _material_authority_named_rows(payload_report.get("wrapper_order"), ("order", "wrapper_name", "item_id"))
    source_bindings = _material_authority_named_rows(
        source_report.get("submesh_bindings"),
        ("order", "wrapper_name", "item_id", "id_base", "shader_name"),
    )
    payload_bindings = _material_authority_named_rows(
        payload_report.get("submesh_bindings"),
        ("order", "wrapper_name", "item_id", "id_base", "shader_name"),
    )
    source_binding_ids = _material_authority_named_rows(
        source_report.get("submesh_bindings"),
        ("order", "wrapper_name", "item_id", "id_base"),
    )
    payload_binding_ids = _material_authority_named_rows(
        payload_report.get("submesh_bindings"),
        ("order", "wrapper_name", "item_id", "id_base"),
    )
    source_parameter_abi = _material_authority_parameter_abi_rows(source_report)
    payload_parameter_abi = _material_authority_parameter_abi_rows(payload_report)
    return {
        "structural_compare_status": "source_compared",
        "wrapper_order_preserved": source_wrappers == payload_wrappers,
        "wrapper_item_ids_preserved": source_wrapper_ids == payload_wrapper_ids,
        "submesh_bindings_preserved": source_bindings == payload_bindings,
        "submesh_item_ids_preserved": source_binding_ids == payload_binding_ids,
        "parameter_abi_preserved": source_parameter_abi == payload_parameter_abi,
        "source_wrapper_order_count": len(source_wrappers),
        "payload_wrapper_order_count": len(payload_wrappers),
        "source_submesh_binding_count": len(source_bindings),
        "payload_submesh_binding_count": len(payload_bindings),
        "source_parameter_abi_count": len(source_parameter_abi),
        "payload_parameter_abi_count": len(payload_parameter_abi),
    }


def _material_authority_sidecar_report_dict(sidecar_text: str, sidecar_path: str) -> Mapping[str, object]:
    if not str(sidecar_text or "").strip():
        return {}
    try:
        return build_pac_xml_material_authority_report(sidecar_text, sidecar_path).to_dict()
    except Exception:
        return {}


def _material_authority_named_rows(rows: object, fields: Sequence[str]) -> Tuple[Tuple[str, ...], ...]:
    output: List[Tuple[str, ...]] = []
    for row in tuple(rows or ()):
        if not isinstance(row, Mapping):
            continue
        output.append(tuple(str(row.get(field, "") or "") for field in fields))
    return tuple(output)


def _material_authority_parameter_abi_rows(report: Mapping[str, object]) -> Tuple[Tuple[str, ...], ...]:
    rows: List[Tuple[str, ...]] = []
    for group_name in (
        "runtime_abi_parameters",
        "source_authority_parameters",
        "inherited_influence_parameters",
        "unknown_material_response_parameters",
    ):
        for row in tuple(report.get(group_name, ()) or ()):
            if not isinstance(row, Mapping):
                continue
            rows.append(
                (
                    str(row.get("wrapper_name", "") or ""),
                    str(row.get("parameter_name", "") or ""),
                    str(row.get("parameter_type", "") or ""),
                    str(row.get("item_id", "") or ""),
                    str(row.get("index", "") or ""),
                )
            )
    return tuple(sorted(rows))


def _material_authority_sidecar_texture_ref_changes(
    source_bindings: Sequence[object],
    payload_bindings: Sequence[object],
) -> Tuple[Mapping[str, object], ...]:
    source_by_key = {
        _material_authority_sidecar_binding_key(binding): binding
        for binding in tuple(source_bindings or ())
        if str(getattr(binding, "texture_path", "") or "").strip()
    }
    payload_by_key = {
        _material_authority_sidecar_binding_key(binding): binding
        for binding in tuple(payload_bindings or ())
        if str(getattr(binding, "texture_path", "") or "").strip()
    }
    rows: List[Mapping[str, object]] = []
    for key in sorted(set(payload_by_key) - set(source_by_key)):
        binding = payload_by_key[key]
        rows.append(_material_authority_sidecar_change_row("added", binding, before="", after=str(getattr(binding, "texture_path", "") or "")))
    for key in sorted(set(source_by_key) - set(payload_by_key)):
        binding = source_by_key[key]
        rows.append(_material_authority_sidecar_change_row("removed", binding, before=str(getattr(binding, "texture_path", "") or ""), after=""))
    for key in sorted(set(source_by_key) & set(payload_by_key)):
        source_binding = source_by_key[key]
        payload_binding = payload_by_key[key]
        before = str(getattr(source_binding, "texture_path", "") or "")
        after = str(getattr(payload_binding, "texture_path", "") or "")
        if normalize_texture_reference_for_sidecar_lookup(before) == normalize_texture_reference_for_sidecar_lookup(after):
            continue
        rows.append(_material_authority_sidecar_change_row("changed", payload_binding, before=before, after=after))
    return tuple(rows)


def _material_authority_sidecar_binding_key(binding: object) -> Tuple[str, str, str]:
    material_name = str(
        getattr(binding, "material_name", "")
        or getattr(binding, "submesh_name", "")
        or getattr(binding, "part_name", "")
        or ""
    ).strip().lower()
    parameter_name = str(getattr(binding, "parameter_name", "") or "").strip().lower()
    role = str(getattr(binding, "texture_role", "") or "").strip().lower()
    return material_name, parameter_name, role


def _material_authority_sidecar_change_row(
    change: str,
    binding: object,
    *,
    before: str,
    after: str,
) -> Mapping[str, object]:
    return {
        "change": change,
        "material_name": str(getattr(binding, "material_name", "") or getattr(binding, "submesh_name", "") or ""),
        "parameter_name": str(getattr(binding, "parameter_name", "") or ""),
        "texture_role": str(getattr(binding, "texture_role", "") or ""),
        "before": str(before or "").replace("\\", "/"),
        "after": str(after or "").replace("\\", "/"),
    }


def _material_authority_preview_settings(
    preview_result: MeshImportPreviewResult,
    final_preview_model: ModelPreviewData,
    texture_resolution_manifest: TextureResolutionManifest,
    *,
    require_source_owned_colors: bool,
    strict_source_owned_material_contract: bool,
    allow_inherited_layer_color_bindings: bool,
    render_settings: object = None,
) -> Mapping[str, object]:
    normal_y_mode = _material_authority_render_normal_y_mode(render_settings)
    source_preview_model = getattr(preview_result, "preview_model", None)
    source_preview_mesh_parts = len(tuple(getattr(source_preview_model, "meshes", ()) or ()))
    final_preview_mesh_parts = len(tuple(getattr(final_preview_model, "meshes", ()) or ()))
    source_preview_visible_texture_sets = _visible_preview_texture_count(source_preview_model)
    final_preview_visible_texture_sets = _visible_preview_texture_count(final_preview_model)
    settings = {
        "visible_mesh_parts": source_preview_mesh_parts,
        "final_visible_mesh_parts": final_preview_mesh_parts,
        "source_preview_mesh_parts": source_preview_mesh_parts,
        "final_preview_mesh_parts": final_preview_mesh_parts,
        "source_preview_visible_texture_sets": source_preview_visible_texture_sets,
        "final_preview_visible_texture_sets": final_preview_visible_texture_sets,
        "preview_visible_texture_delta": source_preview_visible_texture_sets - final_preview_visible_texture_sets,
        "require_source_owned_colors": bool(require_source_owned_colors),
        "strict_source_owned_material_contract": bool(strict_source_owned_material_contract),
        "allow_inherited_layer_color_bindings": bool(allow_inherited_layer_color_bindings),
        "texture_resolution_manifest_rows": len(tuple(texture_resolution_manifest.rows or ())),
        "normal_y_policy": normal_y_policy_report(normal_y_mode),
    }
    material_authority_settings = getattr(preview_result, "material_authority_settings", None)
    if isinstance(material_authority_settings, Mapping) and material_authority_settings:
        settings["material_authority_export"] = {
            str(key): value if isinstance(value, (bool, int, float, str)) or value is None else str(value)
            for key, value in material_authority_settings.items()
        }
    if render_settings is None:
        settings["render_settings_source"] = "not_provided"
        return settings
    settings["render_settings_source"] = "provided"
    for field_name in (
        "visible_texture_mode",
        "render_diagnostic_mode",
        "alpha_handling_mode",
        "texture_probe_source",
        "sampler_probe_mode",
        "diffuse_swizzle_mode",
        "d3d11_view_mode",
        "d3d11_normal_y_mode",
        "d3d11_texture_address_mode",
    ):
        settings[field_name] = str(getattr(render_settings, field_name, "") or "")
    for field_name in (
        "disable_tint",
        "disable_brightness",
        "disable_uv_scale",
        "force_nearest_no_mipmaps",
        "disable_normal_map",
        "disable_material_map",
        "disable_height_map",
        "disable_all_support_maps",
        "flip_texture_v",
        "disable_lighting",
        "show_texture_debug_strip",
    ):
        settings[field_name] = bool(getattr(render_settings, field_name, False))
    for field_name in (
        "d3d11_ao_strength",
        "d3d11_roughness_bias",
        "d3d11_metalness_scale",
        "d3d11_environment_strength",
        "d3d11_emissive_gain",
        "d3d11_tone_exposure",
        "d3d11_tone_contrast",
        "d3d11_tone_gamma",
        "ambient_strength",
        "diffuse_wrap_bias",
        "diffuse_light_scale",
    ):
        try:
            settings[field_name] = float(getattr(render_settings, field_name))
        except (TypeError, ValueError, OverflowError):
            settings[field_name] = 0.0
    return settings


def _material_authority_render_normal_y_mode(render_settings: object = None) -> str:
    mode = str(getattr(render_settings, "d3d11_normal_y_mode", "") or "asset").strip().lower() or "asset"
    if mode not in {"asset", "force_flip", "force_no_flip"}:
        return "asset"
    return mode


def _material_authority_texture_output_row(
    payload: _FinalPayload,
    *,
    binding_rows: Sequence[FinalPackageBindingRow] = (),
    source_materials: Sequence[Mapping[str, object]] = (),
    normal_y_mode: str = "asset",
) -> Mapping[str, object]:
    payload_bytes = bytes(getattr(payload, "payload_data", b"") or b"")
    source_path = getattr(payload, "source_path", Path())
    source_text = str(source_path) if isinstance(source_path, Path) and str(source_path) != "." else ""
    source_file_size = 0
    source_file_sha256 = ""
    if isinstance(source_path, Path) and source_path.is_file():
        try:
            source_file_size, source_file_sha256 = _sha256_file_evidence(source_path)
        except OSError:
            source_file_size = 0
            source_file_sha256 = ""
    size = len(payload_bytes)
    sha256 = hashlib.sha256(payload_bytes).hexdigest() if payload_bytes else ""
    payload_source = "inline_payload" if payload_bytes else "source_file" if source_file_sha256 else "missing"
    if not payload_bytes and source_file_sha256:
        size = source_file_size
        sha256 = source_file_sha256
    bound_rows = _material_authority_texture_binding_rows(payload.final_path, binding_rows)
    dds_validation = _material_authority_dds_validation(payload, payload_bytes)
    source_normal_space = _material_authority_source_normal_space(source_text)
    role_diagnostics = _material_authority_texture_role_diagnostics(
        bound_rows,
        dds_validation,
        source_normal_space=source_normal_space,
        normal_y_mode=normal_y_mode,
    )
    channel_visualization = _material_authority_texture_channel_visualization(bound_rows, dds_validation)
    conversion_policy = _material_authority_texture_conversion_policy(
        payload,
        bound_rows,
        source_materials,
        dds_validation,
        channel_visualization,
        source_normal_space=source_normal_space,
        normal_y_mode=normal_y_mode,
    )
    visible_luma_mean = _material_authority_visible_luma_mean(payload, payload_bytes, bound_rows)
    return {
        "target_path": payload.final_path,
        "source_path": source_text.replace("\\", "/"),
        "kind": payload.kind,
        "note": str(getattr(payload, "note", "") or ""),
        "bytes": size,
        "sha256": sha256,
        "output_sha256": sha256,
        "payload_source": payload_source,
        "source_bytes": source_file_size,
        "source_sha256": source_file_sha256,
        "stock_or_shared": _is_stock_or_shared_texture_path(payload.final_path),
        "bound_roles": tuple(_dedupe(str(row.role or "") for row in bound_rows if str(row.role or "").strip())),
        "bound_parameters": tuple(_dedupe(str(row.parameter_name or "") for row in bound_rows if str(row.parameter_name or "").strip())),
        "bound_materials": tuple(_dedupe(str(row.material_name or "") for row in bound_rows if str(row.material_name or "").strip())),
        "source_normal_space": source_normal_space,
        "dds_validation": dds_validation,
        "role_diagnostics": role_diagnostics,
        "channel_visualization": channel_visualization,
        "conversion_policy": conversion_policy,
        "visible_luma_mean": visible_luma_mean if visible_luma_mean is not None else "",
    }


def _sha256_file_evidence(path: Path) -> tuple[int, str]:
    size = int(path.stat().st_size)
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return size, hasher.hexdigest()


def _material_authority_texture_binding_rows(
    target_path: str,
    binding_rows: Sequence[FinalPackageBindingRow],
) -> Tuple[FinalPackageBindingRow, ...]:
    target_key = _normalize_final_path(target_path)
    if not target_key:
        return ()
    matches: List[FinalPackageBindingRow] = []
    for row in tuple(binding_rows or ()):
        resolved_key = _normalize_final_path(row.resolved_texture_path)
        requested_key = _normalize_final_path(row.texture_path)
        if resolved_key == target_key or requested_key == target_key:
            matches.append(row)
    return tuple(matches)


def _material_authority_texture_conversion_policy(
    payload: _FinalPayload,
    bound_rows: Sequence[FinalPackageBindingRow],
    source_materials: Sequence[Mapping[str, object]],
    dds_validation: Mapping[str, object],
    channel_visualization: Sequence[Mapping[str, object]],
    *,
    source_normal_space: str = "",
    normal_y_mode: str = "asset",
) -> Mapping[str, object]:
    source_path = getattr(payload, "source_path", Path())
    source_extension = str(getattr(source_path, "suffix", "") or "").strip().lower()
    role_classes = tuple(_dedupe(_material_authority_bound_role_classes(bound_rows)))
    channel_kinds = tuple(
        _dedupe(
            str(row.get("kind", "") or "")
            for row in tuple(channel_visualization or ())
            if isinstance(row, Mapping) and str(row.get("kind", "") or "").strip()
        )
    )
    texconv_format = str(dds_validation.get("texconv_format", "") or "")
    source_rows = _material_authority_bound_source_material_rows(bound_rows, source_materials)
    source_workflows = tuple(_dedupe(_material_authority_source_row_workflow(row) for row in source_rows))
    source_derived_channels = tuple(
        _dedupe(
            str(channel or "").strip().lower()
            for row in source_rows
            for channel in _material_authority_source_row_derived_channels(row)
            if str(channel or "").strip()
        )
    )
    source_classes = tuple(
        _dedupe(
            str(item.get("class", "") or item.get("material_class", "") or "").strip()
            for row in source_rows
            for item in tuple(row.get("material_classification", ()) or ())
            if isinstance(item, Mapping) and str(item.get("class", "") or item.get("material_class", "") or "").strip()
        )
    )
    spec_gloss_conversion = "material" in role_classes and "specular_glossiness" in source_workflows
    return {
        "source_extension": source_extension,
        "payload_kind": str(getattr(payload, "kind", "") or ""),
        "generated": str(getattr(payload, "kind", "") or "").strip().lower().endswith("_generated"),
        "inline_payload": bool(bytes(getattr(payload, "payload_data", b"") or b"")),
        "source_dds_passthrough": source_extension == ".dds",
        "source_image_to_dds": bool(source_extension and source_extension != ".dds"),
        "bound_role_classes": role_classes,
        "dds_format": texconv_format,
        "channel_order": str(dds_validation.get("channel_order", "") or ""),
        "mip_count": int(dds_validation.get("mip_count", 0) or 0),
        "normal_y_mode": str(normal_y_mode or "asset"),
        "source_normal_space": source_normal_space,
        "source_material_names": tuple(_dedupe(str(row.get("material_name", "") or "") for row in source_rows if str(row.get("material_name", "") or "").strip())),
        "source_workflows": source_workflows,
        "source_derived_channels": source_derived_channels,
        "source_material_classes": source_classes,
        "spec_gloss_conversion": spec_gloss_conversion,
        "spec_gloss_conversion_note": (
            "Specular/glossiness source workflow: glossiness is inverted to roughness and specular luminance is mapped into the Crimson packed material mask."
            if spec_gloss_conversion
            else ""
        ),
        "normal_y_policy_required": "normal" in role_classes,
        "channel_visualization_kinds": channel_kinds,
        "packed_channel_semantics": tuple(
            dict(row)
            for visualization in tuple(channel_visualization or ())
            if isinstance(visualization, Mapping)
            for row in tuple(visualization.get("channels", ()) or ())
            if isinstance(row, Mapping)
        ),
    }


def _material_authority_dds_validation(payload: _FinalPayload, payload_bytes: bytes) -> Mapping[str, object]:
    source_path = getattr(payload, "source_path", Path())
    source: object
    if payload_bytes:
        source = payload_bytes
    elif isinstance(source_path, Path) and source_path.is_file():
        source = source_path
    else:
        return {
            "status": "missing_payload",
            "width": 0,
            "height": 0,
            "mip_count": 0,
            "texconv_format": "",
            "channel_order": "",
            "findings": (
                {
                    "severity": "fatal",
                    "code": "missing_payload",
                    "message": "DDS payload bytes and source file are unavailable.",
                },
            ),
        }
    try:
        info = inspect_crimson_dds(source, vpath=str(getattr(payload, "final_path", "") or ""))
    except Exception as exc:
        return {
            "status": "error",
            "width": 0,
            "height": 0,
            "mip_count": 0,
            "texconv_format": "",
            "channel_order": "",
            "findings": (
                {
                    "severity": "fatal",
                    "code": "inspection_failed",
                    "message": str(exc),
                },
            ),
        }
    findings = tuple(
        {
            "severity": str(getattr(finding, "severity", "") or ""),
            "code": str(getattr(finding, "code", "") or ""),
            "message": str(getattr(finding, "message", "") or ""),
        }
        for finding in tuple(getattr(info, "findings", ()) or ())
    )
    severity_values = {str(row.get("severity", "") or "") for row in findings}
    status = "invalid" if "fatal" in severity_values else "warning" if "warning" in severity_values else "valid"
    effective_last4 = getattr(info, "effective_last4", None)
    return {
        "status": status,
        "width": int(getattr(info, "width", 0) or 0),
        "height": int(getattr(info, "height", 0) or 0),
        "mip_count": int(getattr(info, "mip_count", 0) or 0),
        "raw_mip_count": int(getattr(info, "raw_mip_count", 0) or 0),
        "depth": int(getattr(info, "depth", 0) or 0),
        "texconv_format": str(getattr(info, "texconv_format", "") or ""),
        "channel_order": _material_authority_dds_channel_order(getattr(info, "texconv_format", "")),
        "is_dx10": bool(getattr(info, "is_dx10", False)),
        "dxgi_format": int(getattr(info, "dxgi_format", 0) or 0),
        "fourcc": str(getattr(info, "fourcc", "") or ""),
        "block_bytes": int(getattr(info, "block_bytes", 0) or 0),
        "requires_pathc": bool(getattr(info, "requires_pathc", False)),
        "effective_last4": f"0x{int(effective_last4):04X}" if effective_last4 is not None else "",
        "findings": findings,
    }


def _material_authority_visible_luma_mean(
    payload: _FinalPayload,
    payload_bytes: bytes,
    bound_rows: Sequence[FinalPackageBindingRow],
) -> float | None:
    if "base_color" not in _material_authority_bound_role_classes(bound_rows):
        return None
    source_path = getattr(payload, "source_path", Path())
    try:
        from PIL import Image, ImageStat

        source = io.BytesIO(payload_bytes) if payload_bytes else source_path if isinstance(source_path, Path) and source_path.is_file() else None
        if source is None:
            return None
        with Image.open(source) as image:
            rgb = image.convert("RGB")
            rgb.thumbnail((256, 256))
            red, green, blue = ImageStat.Stat(rgb).mean[:3]
    except Exception:
        stats = dict(_material_authority_dds_channel_stats(_material_authority_payload_or_file_bytes(payload, payload_bytes)))
        luma = _material_authority_float(stats.get("luma_mean"), -1.0)
        return round(luma * 255.0, 4) if luma >= 0.0 else None
    luma = (0.2126 * float(red)) + (0.7152 * float(green)) + (0.0722 * float(blue))
    return round(luma, 4)


def _material_authority_dds_channel_order(texconv_format: object) -> str:
    normalized = str(texconv_format or "").strip().upper()
    if normalized.startswith("R8G8B8A8"):
        return "rgba"
    if normalized.startswith("B8G8R8A8"):
        return "bgra"
    if normalized.startswith("B8G8R8X8"):
        return "bgrx"
    if normalized.startswith("R8G8_"):
        return "rg"
    if normalized.startswith("R8_"):
        return "r"
    if normalized.startswith("A8_"):
        return "a"
    if normalized.startswith(("BC1_", "BC2_", "BC3_", "BC7_")):
        return "block_color"
    if normalized.startswith(("BC4_", "BC5_", "BC6H_")):
        return "block_linear"
    return ""


def _material_authority_texture_role_diagnostics(
    bound_rows: Sequence[FinalPackageBindingRow],
    dds_validation: Mapping[str, object],
    *,
    source_normal_space: str = "",
    normal_y_mode: str = "asset",
) -> Tuple[Mapping[str, object], ...]:
    texconv_format = str(dds_validation.get("texconv_format", "") or "").upper()
    if not texconv_format:
        return ()
    diagnostics: List[Mapping[str, object]] = []
    roles = {str(row.role or "").strip().lower() for row in tuple(bound_rows or ())}
    parameters = {str(row.parameter_name or "").strip().lower() for row in tuple(bound_rows or ())}
    role_text = " ".join(sorted(roles | parameters))
    role_classes = _material_authority_bound_role_classes(bound_rows)
    visible_role_classes = role_classes.intersection({"base_color", "emissive"})
    if "base_color" in role_classes and ("emissive" in role_classes or "emissive_control" in role_classes):
        diagnostics.append(
            {
                "severity": "warning",
                "code": "base_texture_used_as_emissive",
                "message": "Same DDS is bound to both base/color and emissive parameters; source emissive authority is ambiguous.",
                "role_classes": tuple(sorted(role_classes)),
            }
        )
    if visible_role_classes and role_classes.intersection({"normal", "material", "height"}):
        diagnostics.append(
            {
                "severity": "warning",
                "code": "texture_bound_to_visible_and_technical_roles",
                "message": "Same DDS is bound to visible color/emissive and technical material roles.",
                "role_classes": tuple(sorted(role_classes)),
            }
        )
    if len(role_classes) > 1:
        diagnostics.append(
            {
                "severity": "info",
                "code": "multi_role_texture_binding",
                "message": "DDS has multiple material binding roles; verify routing is intentional.",
                "role_classes": tuple(sorted(role_classes)),
            }
        )
    if "normal" in role_text:
        policy = normal_y_policy_report(normal_y_mode)
        diagnostics.append(
            {
                "severity": "info",
                "code": "normal_y_policy",
                "message": "Normal Y policy is recorded for preview/export review.",
                "normal_y_mode": str(policy.get("normal_y_mode", "") or ""),
                "d3d11_normal_y_mode": str(policy.get("d3d11_normal_y_mode", "") or ""),
                "effective_preview_policy": str(policy.get("effective_preview_policy", "") or ""),
                "archive_source_normal_space": str(policy.get("archive_source_normal_space", "") or ""),
                "source_normal_space": source_normal_space or "unknown",
            }
        )
        if not source_normal_space:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "normal_y_policy_unconfirmed",
                    "message": "Normal source filename did not declare green_up/directx; verify Y was not flipped incorrectly.",
                }
            )
        if not texconv_format.startswith("BC5_"):
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "normal_format_not_bc5",
                    "message": "Normal texture is not BC5; verify tangent-space XY packing and normal Y policy.",
                }
            )
        if "SRGB" in texconv_format:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "normal_srgb_format",
                    "message": "Normal texture uses an sRGB format; normals should be linear.",
                }
            )
    if visible_role_classes:
        if texconv_format.startswith(("BC4_", "BC5_", "R8_", "R8G8_")):
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "visible_color_technical_format",
                    "message": "Visible color slot uses a scalar/vector technical DDS format.",
                }
            )
        if texconv_format in {"BC1_UNORM", "BC2_UNORM", "BC3_UNORM", "BC7_UNORM", "R8G8B8A8_UNORM", "B8G8R8A8_UNORM"}:
            diagnostics.append(
                {
                    "severity": "info",
                    "code": "visible_color_linear_format_review",
                    "message": "Visible color DDS is not marked sRGB; verify intended color space.",
                }
            )
    if "emissive_control" in role_classes or any(
        token in role_text for token in ("material", "roughness", "metal", "ao", "height", "mask", "detail")
    ):
        if "SRGB" in texconv_format:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "technical_slot_srgb_format",
                    "message": "Technical/material slot uses sRGB format; packed scalar channels should be linear.",
                }
            )
    channel_order = str(dds_validation.get("channel_order", "") or "")
    if channel_order in {"rgba", "bgra", "bgrx"}:
        diagnostics.append(
            {
                "severity": "info",
                "code": "uncompressed_channel_order",
                "message": f"Uncompressed DDS channel order detected: {channel_order.upper()}. Verify RGBA/BGRA expectations.",
            }
        )
    return tuple(diagnostics)


def _material_authority_texture_channel_visualization(
    bound_rows: Sequence[FinalPackageBindingRow],
    dds_validation: Mapping[str, object],
) -> Tuple[Mapping[str, object], ...]:
    texconv_format = str(dds_validation.get("texconv_format", "") or "").upper()
    channel_order = str(dds_validation.get("channel_order", "") or "").strip().lower()
    width = int(dds_validation.get("width", 0) or 0)
    height = int(dds_validation.get("height", 0) or 0)
    role_classes = _material_authority_bound_role_classes(bound_rows)
    role_text = " ".join(
        sorted(
            str(value or "").strip().lower()
            for row in tuple(bound_rows or ())
            for value in (row.role, row.parameter_name, row.texture_path, row.resolved_texture_path)
            if str(value or "").strip()
        )
    )

    rows: list[Mapping[str, object]] = []

    def add(kind: str, channels: Sequence[tuple[str, str]], note: str) -> None:
        if not channels:
            return
        rows.append(
            {
                "kind": kind,
                "width": width,
                "height": height,
                "texconv_format": texconv_format,
                "channel_order": channel_order,
                "channels": tuple({"channel": channel, "semantic": semantic} for channel, semantic in channels),
                "note": note,
            }
        )

    if "normal" in role_classes:
        add(
            "normal_xy",
            (("R", "normal_x"), ("G", "normal_y")),
            "Visualize normal XY channels; blue/Z is reconstructed in shader/preview.",
        )
    if "height" in role_classes:
        add("height", (("R", "height"),), "Visualize height/displacement scalar channel.")
    if role_classes.intersection({"base_color", "emissive"}):
        if channel_order == "bgra":
            channels = (("B", "red"), ("G", "green"), ("R", "blue"), ("A", "alpha"))
        elif channel_order == "bgrx":
            channels = (("B", "red"), ("G", "green"), ("R", "blue"), ("X", "unused"))
        else:
            channels = (("R", "red"), ("G", "green"), ("B", "blue"), ("A", "alpha"))
        add(
            "visible_color",
            channels,
            "Visualize visible color with recorded DDS channel order to catch RGBA/BGRA mixups.",
        )
    if "emissive_control" in role_classes:
        channels = (("R", "emissive_intensity"), ("G", "emissive_progress_or_mask")) if (
            channel_order == "rg" or texconv_format.startswith("BC5_")
        ) else (("R", "emissive_intensity"),)
        add(
            "emissive_control",
            channels,
            "Visualize Crimson emissive intensity/progress control channels separately from RGB emissive color.",
        )
    if "material" in role_classes:
        packed_channels = _material_authority_packed_channel_semantics(role_text)
        add(
            "packed_material_mask",
            packed_channels,
            "Visualize packed Crimson material/mask scalar channels.",
        )
    if not rows and texconv_format:
        if channel_order == "r":
            add("scalar", (("R", "scalar"),), "Visualize single-channel scalar texture.")
        elif channel_order == "rg" or texconv_format.startswith("BC5_"):
            add("vector2", (("R", "x"), ("G", "y")), "Visualize two-channel vector/scalar texture.")
    return tuple(rows)


def _material_authority_packed_channel_semantics(role_text: str) -> Tuple[tuple[str, str], ...]:
    text = re.sub(r"[^a-z0-9]+", "", str(role_text or "").lower())
    if "detail" in text or text.endswith("mg") or "detailmask" in text:
        return (("R", "detail_or_grime"), ("G", "detail_or_grime"), ("B", "detail_or_grime"), ("A", "alpha"))
    if "specular" in text or "gloss" in text:
        return (("R", "specular"), ("G", "glossiness"), ("B", "unused_or_ao"), ("A", "alpha"))
    if "roughness" in text and "metal" not in text and "ao" not in text and "occlusion" not in text:
        return (("R", "roughness"),)
    if "metal" in text and "roughness" not in text and "ao" not in text and "occlusion" not in text:
        return (("R", "metallic"),)
    if "ao" in text or "occlusion" in text:
        return (("R", "ao"),)
    return (("R", "ao"), ("G", "roughness"), ("B", "metallic"), ("A", "alpha"))


def _material_authority_bound_source_material_rows(
    bound_rows: Sequence[FinalPackageBindingRow],
    source_materials: Sequence[Mapping[str, object]],
) -> Tuple[Mapping[str, object], ...]:
    if not bound_rows or not source_materials:
        return ()
    by_key: Dict[str, Mapping[str, object]] = {}
    for row in tuple(source_materials or ()):
        if not isinstance(row, Mapping):
            continue
        for value in (row.get("material_name"), row.get("runtime_material_name"), row.get("texture_name")):
            key = _material_key(str(value or ""))
            if key:
                by_key.setdefault(key, row)
    matched: List[Mapping[str, object]] = []
    seen: set[int] = set()
    for binding in tuple(bound_rows or ()):
        for value in (binding.material_name, binding.part_name):
            key = _material_key(str(value or ""))
            row = by_key.get(key)
            if row is None:
                continue
            row_id = id(row)
            if row_id in seen:
                continue
            seen.add(row_id)
            matched.append(row)
    return tuple(matched)


def _material_authority_source_row_workflow(row: Mapping[str, object]) -> str:
    profile = row.get("channel_profile")
    if isinstance(profile, Mapping):
        workflow = str(profile.get("workflow", "") or "").strip().lower()
        if workflow:
            return workflow
    return str(row.get("pbr_workflow", "") or "").strip().lower()


def _material_authority_source_row_derived_channels(row: Mapping[str, object]) -> Tuple[str, ...]:
    profile = row.get("channel_profile")
    if isinstance(profile, Mapping):
        return tuple(str(channel or "").strip().lower() for channel in tuple(profile.get("derived_channels", ()) or ()) if str(channel or "").strip())
    return ()


def _material_authority_bound_role_classes(bound_rows: Sequence[FinalPackageBindingRow]) -> set[str]:
    classes: set[str] = set()
    for row in tuple(bound_rows or ()):
        role = str(row.role or "").strip().lower()
        parameter = re.sub(r"[^a-z0-9]+", "", str(row.parameter_name or "").lower())
        combined = f"{role} {parameter}"
        emissive_control = any(token in parameter for token in ("emissiveintensitytexture", "emissiveprogresstexture"))
        material_like = any(token in combined for token in ("colorblending", "material", "rough", "metal", "ao", "occlusion", "mask", "detail", "specular", "gloss"))
        if any(token in combined for token in ("base", "overlay", "albedo", "diffuse")) or (
            "color" in combined and not material_like
        ):
            classes.add("base_color")
        if emissive_control:
            classes.add("emissive_control")
        elif any(token in combined for token in ("emissive", "emission", "glow", "illum")):
            classes.add("emissive")
        if "normal" in combined:
            classes.add("normal")
        if "height" in combined or "displacement" in combined or "bump" in combined:
            classes.add("height")
        if material_like:
            classes.add("material")
    return classes


def _material_authority_source_normal_space(source_path: object) -> str:
    stem = PurePosixPath(str(source_path or "").replace("\\", "/")).stem.lower()
    if "green_up" in stem or "opengl" in stem or stem.endswith("_gl"):
        return "green_up"
    if "directx" in stem or stem.endswith("_dx") or "_dx_" in stem:
        return "directx"
    return ""


def _material_authority_routing_row(row: FinalPackageBindingRow) -> Mapping[str, object]:
    return {
        "material_name": row.material_name,
        "part_name": row.part_name,
        "role": row.role,
        "parameter_name": row.parameter_name,
        "sidecar_path": row.sidecar_path,
        "requested_texture_path": row.texture_path,
        "resolved_texture_path": row.resolved_texture_path,
        "binding_source": row.binding_source,
        "status": row.status,
        "confidence": row.confidence,
        "detail": row.detail,
    }


def _material_authority_target_section_rows(
    preview_result: MeshImportPreviewResult,
    material_statuses: Sequence[FinalPackageMaterialStatus],
    binding_rows: Sequence[FinalPackageBindingRow],
) -> Iterable[Mapping[str, object]]:
    status_by_key = {_material_key(row.material_name): row for row in tuple(material_statuses or ())}
    rows_by_key: Dict[str, List[FinalPackageBindingRow]] = defaultdict(list)
    for row in tuple(binding_rows or ()):
        rows_by_key[_material_key(row.material_name)].append(row)
    emitted: set[str] = set()
    for section in tuple(getattr(preview_result, "source_owned_output_draw_sections", ()) or ()):
        name = str(
            getattr(section, "target_submesh_name", "")
            or getattr(section, "runtime_material_name", "")
            or getattr(section, "donor_material_name", "")
            or ""
        ).strip()
        key = _material_key(name)
        emitted.add(key)
        yield {
            "target_name": name,
            "runtime_material_name": str(getattr(section, "runtime_material_name", "") or ""),
            "source_material_name": str(getattr(section, "source_material_name", "") or ""),
            "source_submesh_indices": tuple(getattr(section, "source_submesh_indices", ()) or ()),
            "status": getattr(status_by_key.get(key), "status", ""),
            "binding_count": len(rows_by_key.get(key, ())),
        }
    for status in tuple(material_statuses or ()):
        key = _material_key(status.material_name)
        if key in emitted:
            continue
        yield {
            "target_name": status.material_name,
            "runtime_material_name": status.material_name,
            "source_material_name": "",
            "source_submesh_indices": (),
            "status": status.status,
            "binding_count": len(rows_by_key.get(key, ())),
            "detail": status.detail,
        }


def _material_authority_source_material_rows(preview_result: MeshImportPreviewResult) -> Iterable[Mapping[str, object]]:
    preview_model = getattr(preview_result, "preview_model", None)
    source_name_by_key, source_name_by_index = _material_authority_source_material_name_lookup(preview_result)
    for index, mesh in enumerate(tuple(getattr(preview_model, "meshes", ()) or ())):
        runtime_material_name = str(getattr(mesh, "material_name", "") or getattr(mesh, "texture_name", "") or "")
        source_index = _material_authority_safe_int(getattr(mesh, "source_submesh_index", -1), -1)
        source_material_name = (
            source_name_by_index.get(source_index)
            or source_name_by_key.get(_material_key(runtime_material_name))
            or runtime_material_name
        )
        texture_inputs = []
        input_tuple = tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())
        for texture_input in input_tuple:
            texture_inputs.append(
                {
                    "slot_kind": str(getattr(texture_input, "slot_kind", "") or ""),
                    "parameter_name": str(getattr(texture_input, "parameter_name", "") or ""),
                    "texture_path": str(
                        getattr(texture_input, "preview_texture_path", "")
                        or getattr(texture_input, "source_texture_path", "")
                        or ""
                    ).replace("\\", "/"),
                    "semantic_type": str(getattr(texture_input, "semantic_type", "") or ""),
                    "semantic_subtype": str(getattr(texture_input, "semantic_subtype", "") or ""),
                    "packed_channels": tuple(getattr(texture_input, "packed_channels", ()) or ()),
                    "srgb_mode": str(getattr(texture_input, "srgb_mode", "") or ""),
                    "confidence": str(getattr(texture_input, "confidence", "") or ""),
                }
            )
        channel_profile = _material_authority_source_channel_profile(mesh, input_tuple, material_name=source_material_name)
        sections = _material_authority_source_section_rows(index, mesh, material_name=source_material_name)
        yield {
            "mesh_index": index,
            "material_name": source_material_name,
            "runtime_material_name": runtime_material_name if runtime_material_name != source_material_name else "",
            "texture_name": str(getattr(mesh, "texture_name", "") or ""),
            "preview_texture_path": str(getattr(mesh, "preview_texture_path", "") or "").replace("\\", "/"),
            "preview_normal_texture_path": str(getattr(mesh, "preview_normal_texture_path", "") or "").replace("\\", "/"),
            "preview_material_texture_path": str(getattr(mesh, "preview_material_texture_path", "") or "").replace("\\", "/"),
            "preview_material_texture_subtype": str(getattr(mesh, "preview_material_texture_subtype", "") or ""),
            "alpha_mode": str(getattr(mesh, "preview_alpha_mode", "") or ""),
            "double_sided": bool(getattr(mesh, "preview_double_sided", False)),
            "vertex_color_factor": tuple(channel_profile.get("vertex_color_factor", ())),
            "vertex_alpha": tuple(channel_profile.get("vertex_alpha", ())),
            "sections": sections,
            "section_count": len(sections),
            "material_inputs": tuple(texture_inputs),
            "texture_facts": _material_authority_source_texture_fact_rows(mesh, input_tuple),
            "channel_profile": channel_profile,
            "detected_channels": tuple(channel_profile.get("detected_channels", ())),
            "missing_channels": tuple(channel_profile.get("missing_channels", ())),
            "material_classification": tuple(channel_profile.get("material_classification", ())),
            "diagnostics": tuple(channel_profile.get("diagnostics", ())),
        }


def _material_authority_source_material_rows_for_report(
    preview_result: MeshImportPreviewResult,
    source_path: object,
) -> Tuple[Mapping[str, object], ...]:
    external_rows = _material_authority_external_source_material_rows(source_path)
    if external_rows:
        return external_rows
    return tuple(_material_authority_source_material_rows(preview_result))


def _material_authority_external_source_material_rows(source_path: object) -> Tuple[Mapping[str, object], ...]:
    path_text = str(source_path or "").strip()
    if not path_text:
        return ()
    path = Path(path_text).expanduser()
    if not path.is_file() or path.suffix.lower() not in {".glb", ".gltf", ".obj", ".dae", ".fbx", ".zip"}:
        return ()
    if path.suffix.lower() == ".fbx":
        return _material_authority_fbx_source_material_rows(path)
    try:
        from cdmw.core.external_model_audit import _material_row_with_channel_profile
        from cdmw.modding.scene_importer import import_scene_mesh_with_report

        scene_result = import_scene_mesh_with_report(path)
        audit = getattr(scene_result, "external_audit", None)
    except Exception:
        return ()
    rows: List[Mapping[str, object]] = []
    for material in tuple(getattr(audit, "material_inventory", ()) or ()):
        row = _material_authority_external_inventory_source_row(material, _material_row_with_channel_profile)
        if row:
            rows.append(row)
    return tuple(rows)


def _material_authority_fbx_source_material_rows(path: Path) -> Tuple[Mapping[str, object], ...]:
    try:
        from cdmw.core.external_model_audit import _audit_external_model_file, _material_row_with_channel_profile
        from cdmw.core.model_catalogue import LocalModelFile

        resolved_path = path.expanduser().resolve()
        stat = resolved_path.stat()
        root = resolved_path.parent
        catalogue_row = LocalModelFile(
            path=resolved_path,
            root=root,
            name=resolved_path.stem,
            extension=resolved_path.suffix.lower(),
            size=int(stat.st_size),
            modified_at=float(stat.st_mtime),
            import_supported=False,
        )
        audited = _audit_external_model_file(catalogue_row)
    except Exception:
        return ()
    rows: List[Mapping[str, object]] = []
    for material in tuple(audited.get("material_inventory", ()) if isinstance(audited, Mapping) else ()):
        if not isinstance(material, Mapping):
            continue
        row = _material_authority_external_inventory_source_row(material, _material_row_with_channel_profile)
        if row:
            rows.append(row)
    return tuple(rows)


def _material_authority_external_value(row: object, key: str, default: object = None) -> object:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _material_authority_mapping_items(value: object) -> Tuple[tuple[object, object], ...]:
    if isinstance(value, Mapping):
        return tuple(value.items())
    try:
        return tuple(value or ())  # type: ignore[arg-type]
    except TypeError:
        return ()


def _material_authority_external_inventory_source_row(
    material: object,
    profile_builder: Callable[[Mapping[str, object]], Mapping[str, object]],
) -> Mapping[str, object]:
    texture_slot_values = tuple(_material_authority_external_value(material, "texture_slots", ()) or ())
    texture_slots = tuple(_material_authority_external_texture_slot_row(slot) for slot in texture_slot_values)
    texture_facts = tuple(_material_authority_external_texture_fact_row(slot) for slot in texture_slot_values)
    sections = tuple(_material_authority_external_section_row(section) for section in tuple(_material_authority_external_value(material, "sections", ()) or ()))
    classes = tuple(_material_authority_external_class_row(row) for row in tuple(_material_authority_external_value(material, "material_classes", ()) or ()))
    scalar_hints = {
        str(key or ""): _material_authority_float(value, 0.0)
        for key, value in _material_authority_mapping_items(_material_authority_external_value(material, "scalar_hints", ()))
        if str(key or "").strip()
    }
    payload: Dict[str, object] = {
        "material_name": str(_material_authority_external_value(material, "material_name", "") or ""),
        "texture_name": next((str(slot.get("texture_name", "") or "") for slot in texture_slots if str(slot.get("texture_name", "") or "")), ""),
        "texture_slots": texture_slots,
        "material_classes": classes,
        "pbr_workflow": str(_material_authority_external_value(material, "pbr_workflow", "") or ""),
        "alpha_mode": str(_material_authority_external_value(material, "alpha_mode", "") or ""),
        "double_sided": bool(_material_authority_external_value(material, "double_sided", False)),
        "scalar_hints": scalar_hints,
        "color_factor": tuple(_material_authority_external_value(material, "color_factor", ()) or ()),
        "vertex_color_factor": tuple(_material_authority_external_value(material, "vertex_color_factor", ()) or ()),
        "vertex_alpha": tuple(_material_authority_external_value(material, "vertex_alpha", ()) or ()),
        "emissive_color": tuple(_material_authority_external_value(material, "emissive_color", ()) or ()),
    }
    profiled = dict(profile_builder(payload))
    channel_profile = dict(profiled.get("channel_profile", {}) or {})
    return {
        "mesh_index": _material_authority_safe_int(_material_authority_external_value(material, "material_index", -1), -1),
        "material_name": payload["material_name"],
        "runtime_material_name": "",
        "texture_name": payload["texture_name"],
        "preview_texture_path": next((str(slot.get("texture_path", "") or "") for slot in texture_slots if str(slot.get("slot_kind", "") or "") == "base"), ""),
        "preview_normal_texture_path": next((str(slot.get("texture_path", "") or "") for slot in texture_slots if str(slot.get("slot_kind", "") or "") == "normal"), ""),
        "preview_material_texture_path": next((str(slot.get("texture_path", "") or "") for slot in texture_slots if str(slot.get("slot_kind", "") or "") == "material"), ""),
        "preview_material_texture_subtype": next((str(slot.get("semantic_subtype", "") or "") for slot in texture_slots if str(slot.get("slot_kind", "") or "") == "material"), ""),
        "alpha_mode": payload["alpha_mode"],
        "double_sided": payload["double_sided"],
        "color_factor": payload["color_factor"],
        "vertex_color_factor": payload["vertex_color_factor"],
        "vertex_alpha": payload["vertex_alpha"],
        "emissive_color": payload["emissive_color"],
        "scalar_hints": tuple(scalar_hints.items()),
        "pbr_workflow": str(profiled.get("pbr_workflow", "") or payload["pbr_workflow"]),
        "sections": sections,
        "section_count": len(sections),
        "material_inputs": texture_slots,
        "texture_facts": texture_facts,
        "channel_profile": channel_profile,
        "detected_channels": tuple(profiled.get("detected_channels", ()) or ()),
        "missing_channels": tuple(profiled.get("missing_channels", ()) or ()),
        "material_classification": classes,
        "diagnostics": tuple(profiled.get("channel_diagnostics", ()) or ()),
        "source": "external_model_audit",
    }


def _material_authority_external_texture_slot_row(slot: object) -> Mapping[str, object]:
    return {
        "slot_kind": str(_material_authority_external_value(slot, "slot_kind", "") or ""),
        "parameter_name": str(_material_authority_external_value(slot, "parameter_name", "") or ""),
        "texture_path": str(_material_authority_external_value(slot, "texture_path", "") or "").replace("\\", "/"),
        "texture_name": str(_material_authority_external_value(slot, "texture_name", "") or ""),
        "image_format": str(_material_authority_external_value(slot, "image_format", "") or ""),
        "resolution": tuple(_material_authority_external_value(slot, "resolution", ()) or ()),
        "channel_stats": tuple(_material_authority_external_value(slot, "channel_stats", ()) or ()),
        "semantic_type": str(_material_authority_external_value(slot, "semantic_type", "") or ""),
        "semantic_subtype": str(_material_authority_external_value(slot, "semantic_subtype", "") or ""),
        "packed_channels": tuple(_material_authority_external_value(slot, "packed_channels", ()) or ()),
        "color_space": str(_material_authority_external_value(slot, "color_space", "") or ""),
        "source": str(_material_authority_external_value(slot, "source", "") or ""),
        "confidence": str(_material_authority_external_value(slot, "confidence", "") or ""),
    }


def _material_authority_external_texture_fact_row(slot: object) -> Mapping[str, object]:
    row = dict(_material_authority_external_texture_slot_row(slot))
    row["resolution_status"] = "available" if len(tuple(row.get("resolution", ()) or ())) >= 2 else "missing_or_unreadable"
    row["channel_stats_status"] = "available" if tuple(row.get("channel_stats", ()) or ()) else "missing_or_unreadable"
    return row


def _material_authority_external_section_row(section: object) -> Mapping[str, object]:
    return {
        "section_index": _material_authority_safe_int(_material_authority_external_value(section, "section_index", -1), -1),
        "source_submesh_index": _material_authority_safe_int(_material_authority_external_value(section, "section_index", -1), -1),
        "section_name": str(_material_authority_external_value(section, "section_name", "") or ""),
        "material_name": str(_material_authority_external_value(section, "material_name", "") or ""),
        "runtime_material_name": "",
        "vertex_count": _material_authority_safe_int(_material_authority_external_value(section, "vertex_count", 0), 0),
        "face_count": _material_authority_safe_int(_material_authority_external_value(section, "face_count", 0), 0),
        "has_uvs": bool(_material_authority_external_value(section, "has_uvs", False)),
        "has_normals": bool(_material_authority_external_value(section, "has_normals", False)),
        "has_tangents": bool(_material_authority_external_value(section, "has_tangents", False)),
        "has_skinning": bool(_material_authority_external_value(section, "has_skinning", False)),
        "texture_texcoord_sets": tuple(_material_authority_external_value(section, "texture_texcoord_sets", ()) or ()),
        "bounds_min": tuple(_material_authority_external_value(section, "bounds_min", ()) or ()),
        "bounds_max": tuple(_material_authority_external_value(section, "bounds_max", ()) or ()),
    }


def _material_authority_external_class_row(row: object) -> Mapping[str, object]:
    material_class = str(_material_authority_external_value(row, "material_class", "") or "unknown")
    return {
        "class": material_class,
        "material_class": material_class,
        "confidence": _material_authority_float(_material_authority_external_value(row, "confidence", 0.0), 0.0),
        "evidence": tuple(_material_authority_external_value(row, "evidence", ()) or ()),
    }


def _material_authority_source_material_name_lookup(
    preview_result: MeshImportPreviewResult,
) -> Tuple[Dict[str, str], Dict[int, str]]:
    by_key: Dict[str, str] = {}
    by_index: Dict[int, str] = {}
    for section in tuple(getattr(preview_result, "source_owned_output_draw_sections", ()) or ()):
        source_name = str(getattr(section, "source_material_name", "") or "").strip()
        if not source_name:
            atlas_names = tuple(
                str(name or "").strip()
                for name in tuple(getattr(section, "atlas_source_material_names", ()) or ())
                if str(name or "").strip()
            )
            if len(atlas_names) == 1:
                source_name = atlas_names[0]
        if not source_name:
            continue
        for value in (
            getattr(section, "target_submesh_name", ""),
            getattr(section, "runtime_material_name", ""),
            getattr(section, "runtime_slot_name", ""),
            getattr(section, "donor_material_name", ""),
            getattr(section, "atlas_material_name", ""),
        ):
            key = _material_key(str(value or ""))
            if key:
                by_key.setdefault(key, source_name)
        for source_index in tuple(getattr(section, "source_submesh_indices", ()) or ()):
            try:
                by_index.setdefault(int(source_index), source_name)
            except (TypeError, ValueError, OverflowError):
                continue
        for atlas_rect in tuple(getattr(section, "atlas_rects", ()) or ()):
            rect_name = str(getattr(atlas_rect, "source_material_name", "") or "").strip()
            if not rect_name:
                continue
            for source_index in tuple(getattr(atlas_rect, "source_submesh_indices", ()) or ()):
                try:
                    by_index.setdefault(int(source_index), rect_name)
                except (TypeError, ValueError, OverflowError):
                    continue
    return by_key, by_index


def _material_authority_source_texture_fact_rows(
    mesh: object,
    texture_inputs: Sequence[object],
) -> Tuple[Mapping[str, object], ...]:
    rows: List[Mapping[str, object]] = []
    seen: set[Tuple[str, str]] = set()

    def add(slot_kind: str, path_text: object, *, parameter_name: str = "", source: str = "") -> None:
        path_value = str(path_text or "").replace("\\", "/").strip()
        slot = str(slot_kind or "").strip().lower()
        if not path_value:
            return
        key = (slot, path_value.lower())
        if key in seen:
            return
        seen.add(key)
        rows.append(
            _material_authority_source_texture_fact_row(
                slot,
                path_value,
                parameter_name=parameter_name,
                source=source,
            )
        )

    add("base", getattr(mesh, "preview_texture_path", ""), source="preview_texture_path")
    add("normal", getattr(mesh, "preview_normal_texture_path", ""), source="preview_normal_texture_path")
    add("material", getattr(mesh, "preview_material_texture_path", ""), source="preview_material_texture_path")
    add("height", getattr(mesh, "preview_height_texture_path", ""), source="preview_height_texture_path")
    for texture_input in tuple(texture_inputs or ()):
        if not isinstance(texture_input, PreviewMaterialTextureInput):
            continue
        slot = str(texture_input.slot_kind or texture_input.semantic_type or texture_input.semantic_subtype or "").strip().lower()
        source_path = texture_input.source_texture_path or texture_input.source_dds_path or texture_input.preview_texture_path
        add(
            slot or "texture",
            source_path,
            parameter_name=texture_input.parameter_name,
            source="material_input",
        )
    return tuple(rows)


def _material_authority_source_texture_fact_row(
    slot_kind: str,
    path_text: str,
    *,
    parameter_name: str = "",
    source: str = "",
) -> Mapping[str, object]:
    image_format = Path(path_text).suffix.lower().lstrip(".")
    resolution = _material_authority_source_texture_resolution(path_text)
    channel_stats = _material_authority_source_texture_channel_stats(path_text)
    return {
        "slot_kind": slot_kind,
        "parameter_name": str(parameter_name or ""),
        "texture_path": str(path_text or "").replace("\\", "/"),
        "texture_name": PurePosixPath(str(path_text or "").replace("\\", "/")).name,
        "image_format": image_format,
        "resolution": resolution,
        "channel_stats": channel_stats,
        "color_space": _material_authority_source_texture_color_space(slot_kind),
        "source": source,
        "resolution_status": "available" if len(resolution) >= 2 else "missing_or_unreadable",
        "channel_stats_status": "available" if channel_stats else "missing_or_unreadable",
    }


def _material_authority_source_texture_resolution(path_text: str) -> Tuple[int, int]:
    path_value = str(path_text or "").strip()
    if "::" in path_value:
        return _material_authority_source_zip_texture_resolution(path_value)
    path = Path(path_value).expanduser()
    if not path.is_file():
        return ()
    try:
        if path.suffix.lower() == ".dds":
            info = inspect_crimson_dds(path, vpath=path.as_posix())
            width = int(getattr(info, "width", 0) or 0)
            height = int(getattr(info, "height", 0) or 0)
            return (width, height) if width > 0 and height > 0 else ()
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
        return (int(width), int(height)) if width > 0 and height > 0 else ()
    except Exception:
        return ()


def _material_authority_source_zip_texture_resolution(path_text: str) -> Tuple[int, int]:
    archive_text, member_name = str(path_text or "").split("::", 1)
    archive_path = Path(archive_text).expanduser()
    member_name = member_name.replace("\\", "/").lstrip("/")
    if not archive_path.is_file() or not member_name or "../" in f"/{member_name}":
        return ()
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            info = _material_authority_zip_member_info(archive, member_name)
            if info is None or info.is_dir():
                return ()
            suffix = Path(info.filename).suffix.lower()
            with archive.open(info, "r") as stream:
                if suffix == ".dds":
                    return _material_authority_dds_byte_resolution(stream.read(128))
                if int(getattr(info, "file_size", 0) or 0) > SOURCE_TEXTURE_FACT_MAX_IMAGE_BYTES:
                    return ()
                from PIL import Image

                with Image.open(io.BytesIO(stream.read())) as image:
                    width, height = image.size
                return (int(width), int(height)) if width > 0 and height > 0 else ()
    except Exception:
        return ()


def _material_authority_source_texture_channel_stats(path_text: str) -> Tuple[Tuple[str, float], ...]:
    path_value = str(path_text or "").strip()
    if "::" in path_value:
        return _material_authority_source_zip_texture_channel_stats(path_value)
    path = Path(path_value).expanduser()
    if not path.is_file():
        return ()
    try:
        if path.stat().st_size > SOURCE_TEXTURE_FACT_MAX_IMAGE_BYTES:
            return ()
    except OSError:
        return ()
    if path.suffix.lower() == ".dds":
        try:
            stats = _material_authority_dds_channel_stats(path.read_bytes())
        except OSError:
            stats = ()
        if stats:
            return stats
    try:
        from PIL import Image

        with Image.open(path) as image:
            return _material_authority_image_channel_stats(image)
    except Exception:
        return ()


def _material_authority_source_zip_texture_channel_stats(path_text: str) -> Tuple[Tuple[str, float], ...]:
    archive_text, member_name = str(path_text or "").split("::", 1)
    archive_path = Path(archive_text).expanduser()
    member_name = member_name.replace("\\", "/").lstrip("/")
    if not archive_path.is_file() or not member_name or "../" in f"/{member_name}":
        return ()
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            info = _material_authority_zip_member_info(archive, member_name)
            if info is None or info.is_dir() or int(getattr(info, "file_size", 0) or 0) > SOURCE_TEXTURE_FACT_MAX_IMAGE_BYTES:
                return ()
            with archive.open(info, "r") as stream:
                payload = stream.read()
                if Path(info.filename).suffix.lower() == ".dds":
                    stats = _material_authority_dds_channel_stats(payload)
                    if stats:
                        return stats
                from PIL import Image

                with Image.open(io.BytesIO(payload)) as image:
                    return _material_authority_image_channel_stats(image)
    except Exception:
        return ()


def _material_authority_image_channel_stats(image: object) -> Tuple[Tuple[str, float], ...]:
    try:
        from PIL import ImageStat

        rgba = image.convert("RGBA")  # type: ignore[attr-defined]
        rgba.thumbnail((256, 256))
        stat = ImageStat.Stat(rgba)
        means = [float(value) / 255.0 for value in stat.mean[:4]]
        extrema = rgba.getextrema()
        alpha_min = float(extrema[3][0]) / 255.0 if len(extrema) >= 4 else 1.0
        alpha_max = float(extrema[3][1]) / 255.0 if len(extrema) >= 4 else 1.0
        luma = (0.2126 * means[0]) + (0.7152 * means[1]) + (0.0722 * means[2])
        return (
            ("r_mean", round(means[0], 4)),
            ("g_mean", round(means[1], 4)),
            ("b_mean", round(means[2], 4)),
            ("a_mean", round(means[3], 4)),
            ("a_min", round(alpha_min, 4)),
            ("a_max", round(alpha_max, 4)),
            ("luma_mean", round(luma, 4)),
        )
    except Exception:
        return ()


def _material_authority_payload_or_file_bytes(payload: _FinalPayload, payload_bytes: bytes) -> bytes:
    if payload_bytes:
        return bytes(payload_bytes)
    source_path = getattr(payload, "source_path", Path())
    if isinstance(source_path, Path) and source_path.is_file():
        try:
            if source_path.stat().st_size <= SOURCE_TEXTURE_FACT_MAX_IMAGE_BYTES:
                return source_path.read_bytes()
        except OSError:
            return b""
    return b""


def _material_authority_dds_channel_stats(blob: bytes) -> Tuple[Tuple[str, float], ...]:
    layout = _material_authority_uncompressed_dds_layout(blob)
    if layout is None:
        return ()
    width, height, pixel_offset, channel_order = layout
    pixel_count = min(int(width) * int(height), max(0, (len(blob) - pixel_offset) // 4))
    if pixel_count <= 0:
        return ()
    r_total = g_total = b_total = a_total = 0
    a_min = 255
    a_max = 0
    cursor = pixel_offset
    for _index in range(pixel_count):
        p0, p1, p2, p3 = blob[cursor : cursor + 4]
        cursor += 4
        if channel_order == "rgba":
            red, green, blue, alpha = p0, p1, p2, p3
        elif channel_order == "bgra":
            blue, green, red, alpha = p0, p1, p2, p3
        elif channel_order == "bgrx":
            blue, green, red, alpha = p0, p1, p2, 255
        else:
            return ()
        r_total += red
        g_total += green
        b_total += blue
        a_total += alpha
        a_min = min(a_min, alpha)
        a_max = max(a_max, alpha)
    scale = 255.0 * float(pixel_count)
    r_mean = float(r_total) / scale
    g_mean = float(g_total) / scale
    b_mean = float(b_total) / scale
    a_mean = float(a_total) / scale
    luma = (0.2126 * r_mean) + (0.7152 * g_mean) + (0.0722 * b_mean)
    return (
        ("r_mean", round(r_mean, 4)),
        ("g_mean", round(g_mean, 4)),
        ("b_mean", round(b_mean, 4)),
        ("a_mean", round(a_mean, 4)),
        ("a_min", round(float(a_min) / 255.0, 4)),
        ("a_max", round(float(a_max) / 255.0, 4)),
        ("luma_mean", round(luma, 4)),
    )


def _material_authority_uncompressed_dds_layout(blob: bytes) -> tuple[int, int, int, str] | None:
    if len(blob) < 128 or blob[:4] != b"DDS ":
        return None
    header_size = _material_authority_read_u32(blob, 4)
    if header_size != 124:
        return None
    height = _material_authority_read_u32(blob, 12)
    width = _material_authority_read_u32(blob, 16)
    if width <= 0 or height <= 0:
        return None
    pf_flags = _material_authority_read_u32(blob, 80)
    fourcc = blob[84:88]
    bit_count = _material_authority_read_u32(blob, 88)
    r_mask = _material_authority_read_u32(blob, 92)
    g_mask = _material_authority_read_u32(blob, 96)
    b_mask = _material_authority_read_u32(blob, 100)
    a_mask = _material_authority_read_u32(blob, 104)
    if (pf_flags & 0x4) and fourcc == b"DX10":
        if len(blob) < 148:
            return None
        dxgi_format = _material_authority_read_u32(blob, 128)
        if dxgi_format in {28, 29}:
            return width, height, 148, "rgba"
        if dxgi_format in {87, 91}:
            return width, height, 148, "bgra"
        if dxgi_format in {88, 93}:
            return width, height, 148, "bgrx"
        return None
    if not (pf_flags & 0x40) or bit_count != 32:
        return None
    if (r_mask, g_mask, b_mask, a_mask) == (0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000):
        return width, height, 128, "rgba"
    if (r_mask, g_mask, b_mask, a_mask) == (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000):
        return width, height, 128, "bgra"
    if (r_mask, g_mask, b_mask, a_mask) == (0x00FF0000, 0x0000FF00, 0x000000FF, 0x00000000):
        return width, height, 128, "bgrx"
    return None


def _material_authority_read_u32(blob: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(blob):
        return 0
    return int(struct.unpack_from("<I", blob, offset)[0])


def _material_authority_zip_member_info(archive: zipfile.ZipFile, member_name: str) -> Optional[zipfile.ZipInfo]:
    try:
        return archive.getinfo(member_name)
    except KeyError:
        wanted = member_name.casefold()
        for info in archive.infolist():
            if info.filename.replace("\\", "/").casefold() == wanted:
                return info
    return None


def _material_authority_dds_byte_resolution(header: bytes) -> Tuple[int, int]:
    if len(header) < 20 or header[:4] != b"DDS ":
        return ()
    height = int.from_bytes(header[12:16], "little", signed=False)
    width = int.from_bytes(header[16:20], "little", signed=False)
    return (width, height) if width > 0 and height > 0 else ()


def _material_authority_source_texture_color_space(slot_kind: str) -> str:
    slot = str(slot_kind or "").strip().lower()
    if slot in {"base", "base_color", "albedo", "diffuse", "emissive"}:
        return "srgb"
    if slot:
        return "linear"
    return ""


def _material_authority_source_section_rows(
    mesh_index: int,
    mesh: object,
    *,
    material_name: str = "",
) -> Tuple[Mapping[str, object], ...]:
    positions = list(getattr(mesh, "positions", ()) or ())
    indices = list(getattr(mesh, "indices", ()) or ())
    texture_coordinates = list(getattr(mesh, "texture_coordinates", ()) or ())
    normals = list(getattr(mesh, "normals", ()) or ())
    if not positions and not indices:
        return ()
    source_index = _material_authority_safe_int(getattr(mesh, "source_submesh_index", -1), -1)
    section_index = source_index if source_index >= 0 else int(mesh_index)
    source_name = str(material_name or getattr(mesh, "material_name", "") or getattr(mesh, "texture_name", "") or f"mesh_{mesh_index}")
    runtime_material_name = str(getattr(mesh, "material_name", "") or "")
    bounds_min, bounds_max = _material_authority_bounds(positions)
    return (
        {
            "section_index": section_index,
            "source_submesh_index": source_index,
            "section_name": source_name,
            "material_name": source_name,
            "runtime_material_name": runtime_material_name if runtime_material_name != source_name else "",
            "vertex_count": len(positions),
            "face_count": len(indices) // 3,
            "has_uvs": bool(texture_coordinates and len(texture_coordinates) == len(positions)),
            "has_normals": bool(normals and len(normals) == len(positions)),
            "source_vertex_indices_count": len(tuple(getattr(mesh, "source_vertex_indices", ()) or ())),
            "bounds_min": bounds_min,
            "bounds_max": bounds_max,
        },
    )


def _material_authority_bounds(positions: Sequence[object]) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    vertices = []
    for position in tuple(positions or ()):
        values = tuple(position or ()) if isinstance(position, (tuple, list)) else ()
        if len(values) < 3:
            continue
        try:
            vertices.append((float(values[0]), float(values[1]), float(values[2])))
        except (TypeError, ValueError, OverflowError):
            continue
    if not vertices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    xs, ys, zs = zip(*vertices)
    return (
        (round(min(xs), 6), round(min(ys), 6), round(min(zs), 6)),
        (round(max(xs), 6), round(max(ys), 6), round(max(zs), 6)),
    )


def _material_authority_safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _material_authority_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _material_authority_source_channel_profile(
    mesh: object,
    texture_inputs: Sequence[object],
    *,
    material_name: str = "",
) -> Mapping[str, object]:
    texture_channels: set[str] = set()
    scalar_channels: set[str] = set()
    diagnostics: List[Mapping[str, object]] = []
    material_texture_subtypes: set[str] = set()

    base_path = str(getattr(mesh, "preview_texture_path", "") or "").replace("\\", "/")
    material_path = str(getattr(mesh, "preview_material_texture_path", "") or "").replace("\\", "/")
    alpha_mode = str(getattr(mesh, "preview_alpha_mode", "") or "").strip().lower()
    vertex_color_factor = _material_authority_source_tuple3(mesh, "preview_vertex_color_mean")
    vertex_alpha = _material_authority_source_vertex_alpha(mesh)
    texture_fact_rows = _material_authority_source_texture_fact_rows(mesh, texture_inputs)

    def stats_for(*slot_names: str) -> Dict[str, float]:
        wanted = {str(slot or "").strip().lower() for slot in tuple(slot_names or ()) if str(slot or "").strip()}
        for row in texture_fact_rows:
            slot = str(row.get("slot_kind", "") or "").strip().lower()
            if slot not in wanted:
                continue
            stats = {
                str(key): _material_authority_float(value, 0.0)
                for key, value in tuple(row.get("channel_stats", ()) or ())
            }
            if stats:
                return stats
        return {}

    def stats_from_row(row: Mapping[str, object]) -> Dict[str, float]:
        return {
            str(key): _material_authority_float(value, 0.0)
            for key, value in tuple(row.get("channel_stats", ()) or ())
        }

    def row_has_nonopaque_alpha(stats: Mapping[str, float]) -> bool:
        return stats.get("a_min", 1.0) < 0.98 or stats.get("a_mean", 1.0) < 0.98

    def alpha_usage_for_row(row: Mapping[str, object], stats: Mapping[str, float]) -> str:
        if not row_has_nonopaque_alpha(stats):
            return ""
        slot = str(row.get("slot_kind", "") or "").strip().lower()
        parameter_name = str(row.get("parameter_name", "") or "").strip().lower()
        text = " ".join((slot, parameter_name))
        if any(token in text for token in ("opacity", "alpha", "transparent")):
            return "visible_alpha"
        if slot in {"base", "base_color", "albedo", "diffuse", "emissive"}:
            return "visible_alpha"
        return "technical_alpha"

    if base_path:
        texture_channels.add("base_color")
    if str(getattr(mesh, "preview_normal_texture_path", "") or "").strip():
        texture_channels.add("normal")
    if str(getattr(mesh, "preview_height_texture_path", "") or "").strip():
        texture_channels.add("height")
    subtype = str(getattr(mesh, "preview_material_texture_subtype", "") or "").strip().lower()
    if subtype:
        material_texture_subtypes.add(subtype)
        _material_authority_add_source_channel(texture_channels, subtype)
    for packed in tuple(getattr(mesh, "preview_material_texture_packed_channels", ()) or ()):
        _material_authority_add_source_channel(texture_channels, packed)

    for texture_input in tuple(texture_inputs or ()):
        slot_kind = str(getattr(texture_input, "slot_kind", "") or "").strip().lower()
        semantic_subtype = str(getattr(texture_input, "semantic_subtype", "") or "").strip().lower()
        _material_authority_add_source_channel(texture_channels, slot_kind)
        _material_authority_add_source_channel(texture_channels, semantic_subtype)
        if semantic_subtype:
            material_texture_subtypes.add(semantic_subtype)
        for packed in tuple(getattr(texture_input, "packed_channels", ()) or ()):
            _material_authority_add_source_channel(texture_channels, packed)
        parameter_name = str(getattr(texture_input, "parameter_name", "") or "").strip().lower()
        _material_authority_add_source_channel(texture_channels, parameter_name)

    native_overrides = getattr(mesh, "preview_native_material_overrides", {}) or {}
    if isinstance(native_overrides, Mapping):
        for key in tuple(native_overrides.keys()):
            normalized = str(key or "").strip().lower()
            if "roughness" in normalized:
                scalar_channels.add("roughness")
            elif "metal" in normalized:
                scalar_channels.add("metalness")
            elif "specular" in normalized:
                scalar_channels.add("specular")
            elif "gloss" in normalized:
                scalar_channels.add("glossiness")
            elif "emissive" in normalized:
                scalar_channels.add("emissive")
            elif "alpha" in normalized or "opacity" in normalized:
                scalar_channels.add("opacity")
    base_stats = stats_for("base", "base_color", "albedo")
    for row in texture_fact_rows:
        row_stats = stats_from_row(row)
        alpha_usage = alpha_usage_for_row(row, row_stats)
        if not alpha_usage:
            continue
        code = "source_alpha_from_texture_channel" if alpha_usage == "visible_alpha" else "source_packed_a_channel_technical"
        if alpha_usage == "visible_alpha":
            texture_channels.add("opacity")
        diagnostics.append(
            {
                "severity": "info",
                "code": code,
                "message": (
                    "Source texture alpha channel carries visible opacity evidence."
                    if alpha_usage == "visible_alpha"
                    else "Source packed material texture alpha channel carries technical data, not visible opacity."
                ),
                "slot_kind": str(row.get("slot_kind", "") or ""),
                "texture_name": str(row.get("texture_name", "") or ""),
                "texture_path": str(row.get("texture_path", "") or ""),
                "a_mean": round(row_stats.get("a_mean", 1.0), 4),
                "a_min": round(row_stats.get("a_min", 1.0), 4),
                "a_max": round(row_stats.get("a_max", 1.0), 4),
            }
        )
    if vertex_color_factor:
        scalar_channels.add("base_color")
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_vertex_color_present",
                "message": "Source material has vertex color data that can tint or replace base color.",
                "vertex_color_factor": vertex_color_factor,
            }
        )
    if vertex_alpha and (vertex_alpha[0] < 0.98 or vertex_alpha[1] < 0.98):
        scalar_channels.add("opacity")
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_vertex_alpha_opacity",
                "message": "Source material has vertex alpha opacity data.",
                "vertex_alpha": vertex_alpha,
            }
        )

    workflow = "specular_glossiness" if {"specular", "glossiness"}.intersection(texture_channels | scalar_channels) or "specular_glossiness" in material_texture_subtypes else "metallic_roughness"
    derived_channels: set[str] = set()
    effective_channels = texture_channels | scalar_channels
    if workflow == "specular_glossiness":
        if "glossiness" in effective_channels:
            derived_channels.add("roughness")
        if "specular" in effective_channels:
            derived_channels.add("metalness")
        if derived_channels:
            diagnostics.append(
                {
                    "severity": "info",
                    "code": "source_spec_gloss_derived_material_channels",
                    "message": "Specular/glossiness source channels will derive roughness/metalness for Crimson material masks.",
                    "derived_channels": tuple(sorted(derived_channels)),
                }
            )
    effective_channels = effective_channels | derived_channels
    if "base_color" not in texture_channels:
        diagnostics.append(
            {
                "severity": "warning",
                "code": "source_missing_base_color",
                "message": "Source material has no base-color texture in the package preview model.",
            }
        )
    if alpha_mode in {"blend", "mask", "alpha", "transparent", "coverage", "cutout"} and "opacity" not in texture_channels and "opacity" not in scalar_channels:
        diagnostics.append(
            {
                "severity": "warning",
                "code": "source_alpha_without_opacity_texture",
                "message": "Source material declares alpha but no opacity/alpha texture slot is present.",
                "alpha_mode": alpha_mode,
            }
        )
    if "emissive" in scalar_channels and "emissive" not in texture_channels:
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_emissive_scalar_no_texture",
                "message": "Source material has emissive scalar/color data but no emissive texture.",
            }
        )
    missing_channels = [
        channel
        for channel in ("emissive", "roughness", "metalness")
        if channel not in effective_channels
    ]
    if "roughness" in missing_channels:
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_missing_roughness",
                "message": "Source material has no roughness texture or scalar hint; preview/export must use defaults or target response.",
            }
        )
    if "metalness" in missing_channels:
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_missing_metalness",
                "message": "Source material has no metalness texture or scalar hint; preview/export must use defaults or target response.",
            }
        )
    if "emissive" in missing_channels:
        diagnostics.append(
            {
                "severity": "info",
                "code": "source_missing_emissive",
                "message": "Source material has no emissive texture or scalar hint.",
            }
        )
    if _material_authority_spec_gloss_base_conflict(base_path, material_path, material_texture_subtypes):
        diagnostics.append(
            {
                "severity": "warning",
                "code": "source_spec_gloss_texture_as_base_color",
                "message": "Specular/gloss texture appears to be used as base color; verify source workflow routing.",
            }
        )

    detected = tuple(sorted(texture_channels | derived_channels | {f"{channel}_scalar" for channel in scalar_channels}))
    return {
        "workflow": workflow,
        "detected_channels": detected,
        "texture_channels": tuple(sorted(texture_channels)),
        "scalar_channels": tuple(sorted(scalar_channels)),
        "derived_channels": tuple(sorted(derived_channels)),
        "vertex_color_factor": vertex_color_factor,
        "vertex_alpha": vertex_alpha,
        "missing_channels": tuple(missing_channels),
        "material_classification": _material_authority_source_classification(
            texture_channels=texture_channels,
            scalar_channels=scalar_channels,
            alpha_mode=alpha_mode,
            workflow=workflow,
            material_name=str(material_name or getattr(mesh, "material_name", "") or getattr(mesh, "texture_name", "") or ""),
            double_sided=bool(getattr(mesh, "preview_double_sided", False)),
            vertex_color_factor=vertex_color_factor,
            vertex_alpha=vertex_alpha,
            base_texture_stats=base_stats,
            material_texture_stats=stats_for("material", "metallic_roughness"),
            metalness_texture_stats=stats_for("metalness", "metallic"),
        ),
        "diagnostics": tuple(diagnostics),
        "double_sided": bool(getattr(mesh, "preview_double_sided", False)),
    }


def _material_authority_source_tuple3(mesh: object, attr_name: str) -> Tuple[float, float, float]:
    values = tuple(getattr(mesh, attr_name, ()) or ())
    if len(values) < 3:
        return ()
    try:
        return tuple(round(max(0.0, min(1.0, float(value))), 4) for value in values[:3])  # type: ignore[return-value]
    except (TypeError, ValueError, OverflowError):
        return ()


def _material_authority_source_vertex_alpha(mesh: object) -> Tuple[float, float]:
    mean_value = getattr(mesh, "preview_vertex_alpha_mean", None)
    min_value = getattr(mesh, "preview_vertex_alpha_min", None)
    if mean_value is None and min_value is None:
        return ()
    try:
        alpha_mean = round(max(0.0, min(1.0, float(1.0 if mean_value is None else mean_value))), 4)
        alpha_min = round(max(0.0, min(1.0, float(alpha_mean if min_value is None else min_value))), 4)
        return (alpha_mean, alpha_min)
    except (TypeError, ValueError, OverflowError):
        return ()


def _material_authority_add_source_channel(channels: set[str], value: object) -> None:
    text = re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())
    if not text:
        return
    if any(token in text for token in ("basecolor", "overlaycolor", "diffuse", "albedo", "base")):
        channels.add("base_color")
    if "normal" in text:
        channels.add("normal")
    if any(token in text for token in ("emissive", "emission", "glow", "illum")):
        channels.add("emissive")
    if any(token in text for token in ("opacity", "alpha", "transparent")):
        channels.add("opacity")
    if any(token in text for token in ("roughness", "rough")):
        channels.add("roughness")
    if any(token in text for token in ("metallic", "metalness", "metal")):
        channels.add("metalness")
    if text in {"ao", "aopbr"} or "occlusion" in text:
        channels.add("ao")
    if "specular" in text or text.endswith("spec"):
        channels.add("specular")
    if "glossiness" in text or "gloss" in text:
        channels.add("glossiness")
    if "height" in text or "displacement" in text or "bump" in text:
        channels.add("height")


def _material_authority_spec_gloss_base_conflict(
    base_path: str,
    material_path: str,
    material_texture_subtypes: set[str],
) -> bool:
    base_name = PurePosixPath(str(base_path or "")).name.lower()
    if not base_name:
        return False
    if any(token in base_name for token in ("speculargloss", "specular_gloss", "specular", "glossiness", "gloss")):
        return True
    if _normalize_final_path(base_path) == _normalize_final_path(material_path) and material_texture_subtypes.intersection({"specular", "glossiness", "specular_glossiness"}):
        return True
    return False


def _material_authority_source_classification(
    *,
    texture_channels: set[str],
    scalar_channels: set[str],
    alpha_mode: str,
    workflow: str,
    material_name: str,
    double_sided: bool = False,
    vertex_color_factor: Sequence[float] = (),
    vertex_alpha: Sequence[float] = (),
    base_texture_stats: Optional[Mapping[str, object]] = None,
    material_texture_stats: Optional[Mapping[str, object]] = None,
    metalness_texture_stats: Optional[Mapping[str, object]] = None,
) -> Tuple[Mapping[str, object], ...]:
    classes: List[Mapping[str, object]] = []
    raw_name = str(material_name or "")
    split_name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw_name)
    name = split_name.lower()
    tokens = set(re.findall(r"[a-z0-9]+", name))
    compact_tokens = {
        re.sub(r"[^a-z0-9]+", "", token)
        for token in re.split(r"[\s._/\-\\]+", raw_name.lower())
        if re.sub(r"[^a-z0-9]+", "", token)
    }
    tokens.update(compact_tokens)

    def add(material_class: str, confidence: float, evidence: str) -> None:
        for index, existing in enumerate(classes):
            if existing.get("class") != material_class:
                continue
            if confidence > float(existing.get("confidence", 0.0) or 0.0):
                classes[index] = {"class": material_class, "confidence": confidence, "evidence": evidence}
            return
        classes.append({"class": material_class, "confidence": confidence, "evidence": evidence})

    def has_any(*terms: str) -> bool:
        wanted = {str(term or "").strip().lower() for term in terms if str(term or "").strip()}
        if tokens & wanted:
            return True
        for token in tokens:
            for term in wanted:
                if len(term) >= 5 and (token.startswith(term) or token.endswith(term)):
                    return True
        return False

    if "emissive" in texture_channels or "emissive" in scalar_channels or any(token in name for token in ("emissive", "glow", "lamp", "light")):
        add("emissive", 0.82, "emissive channel or material name")
    if "opacity" in texture_channels or "opacity" in scalar_channels or alpha_mode in {"blend", "mask", "transparent", "cutout"}:
        add("transparent_or_cutout", 0.75, "alpha/opacity channel or alpha mode")
    metal_evidence = "metalness" in texture_channels or "metalness" in scalar_channels or has_any(
        "metal",
        "steel",
        "iron",
        "silver",
        "chrome",
        "blade",
        "sword",
        "armor",
        "armour",
        "gold",
        "bronze",
        "brass",
        "copper",
    )
    if metal_evidence:
        add("metal", 0.68, "metalness channel or metal material name")
    base_stats_map = dict(base_texture_stats or {})
    material_stats_map = dict(material_texture_stats or {})
    metalness_stats_map = dict(metalness_texture_stats or {})
    material_metalness_mean = _material_authority_float(material_stats_map.get("b_mean"), 0.0)
    if material_metalness_mean >= 0.45:
        metal_evidence = True
        add("metal", 0.70, f"metallic-roughness B channel mean {material_metalness_mean:.2f}")
    metalness_luma = _material_authority_float(metalness_stats_map.get("luma_mean"), 0.0)
    if metalness_luma >= 0.45:
        metal_evidence = True
        add("metal", 0.70, f"metalness texture mean {metalness_luma:.2f}")
    if metal_evidence and has_any("painted", "paint", "paintjob", "coated", "enamel"):
        add("painted_metal", 0.70, "painted/coated token with metal evidence")
    if has_any("gold", "gilded"):
        add("gold", 0.90, "gold material/name token")
    if has_any("bronze", "brass"):
        add("bronze", 0.88, "bronze/brass material/name token")
    if has_any("copper"):
        add("copper", 0.88, "copper material/name token")
    if has_any("cloth", "fabric", "linen", "cotton", "canvas", "textile", "garment"):
        add("cloth", 0.80, "cloth/fabric material/name token")
    if double_sided and has_any("cloth", "fabric", "linen", "cotton", "canvas", "textile", "garment", "cape", "flag"):
        add("cloth", 0.82, "double-sided fabric surface")
    if has_any("leather", "hide", "suede"):
        add("leather", 0.85, "leather material/name token")
    if has_any("wood", "wooden", "timber", "oak", "pine", "walnut", "bark"):
        add("wood", 0.85, "wood material/name token")
    if has_any("stone", "rock", "granite", "marble", "concrete", "slate", "ceramic"):
        add("stone", 0.85, "stone/rock material/name token")
    if has_any("skin", "organic", "flesh", "body", "face", "hand", "arm", "leg", "head"):
        add("skin_organic", 0.82, "skin/organic material/name token")
    if has_any("glass", "crystal", "gem", "lens", "transparent", "translucent", "transmission"):
        add("glass_crystal", 0.86, "glass/crystal material/name token")
    if (
        ("opacity" in texture_channels or "opacity" in scalar_channels or alpha_mode in {"blend", "mask", "transparent", "cutout"})
        and has_any("glass", "crystal", "gem", "lens", "pane", "window")
    ):
        add("glass_crystal", 0.88, "alpha/transparency evidence with glass/crystal token")
    base_rgb = ()
    if {"r_mean", "g_mean", "b_mean"} <= set(base_stats_map.keys()):
        base_rgb = (
            _material_authority_float(base_stats_map.get("r_mean"), 0.0),
            _material_authority_float(base_stats_map.get("g_mean"), 0.0),
            _material_authority_float(base_stats_map.get("b_mean"), 0.0),
        )
    if base_rgb and metal_evidence:
        r, g, b = base_rgb
        if r >= 0.65 and g >= 0.45 and b <= 0.38:
            add("gold", 0.62, f"metal source with yellow base texture mean {r:.2f},{g:.2f},{b:.2f}")
        elif r >= 0.55 and 0.20 <= g <= 0.55 and b <= 0.35:
            add("copper", 0.54, f"metal source with warm base texture mean {r:.2f},{g:.2f},{b:.2f}")
        elif r >= 0.45 and g >= 0.25 and b <= 0.30:
            add("bronze", 0.48, f"metal source with bronze-like base texture mean {r:.2f},{g:.2f},{b:.2f}")
    alpha_min = _material_authority_float(base_stats_map.get("a_min"), 1.0)
    alpha_mean = _material_authority_float(base_stats_map.get("a_mean"), 1.0)
    if (
        (alpha_min < 0.98 or alpha_mean < 0.98)
        and not any(row.get("class") == "transparent_or_cutout" for row in classes)
    ):
        add("transparent_or_cutout", 0.68, "source base texture alpha channel")
        if has_any("glass", "crystal", "gem", "lens", "transparent", "translucent"):
            add("glass_crystal", 0.72, "source base alpha with glass/crystal token")
    vertex_rgb = tuple(float(value) for value in tuple(vertex_color_factor or ())[:3]) if len(tuple(vertex_color_factor or ())) >= 3 else ()
    if vertex_rgb and metal_evidence:
        r, g, b = vertex_rgb
        if r >= 0.65 and g >= 0.45 and b <= 0.38:
            add("gold", 0.60, "metal source with yellow vertex color")
        elif r >= 0.55 and 0.20 <= g <= 0.55 and b <= 0.35:
            add("copper", 0.50, "metal source with warm vertex color")
        elif r >= 0.45 and g >= 0.25 and b <= 0.30:
            add("bronze", 0.45, "metal source with bronze-like vertex color")
    vertex_alpha_values = tuple(float(value) for value in tuple(vertex_alpha or ())[:2]) if len(tuple(vertex_alpha or ())) >= 2 else ()
    if (
        vertex_alpha_values
        and (vertex_alpha_values[0] < 0.98 or vertex_alpha_values[1] < 0.98)
        and not any(row.get("class") == "transparent_or_cutout" for row in classes)
    ):
        add("transparent_or_cutout", 0.68, "vertex alpha opacity")
        if has_any("glass", "crystal", "gem", "lens", "transparent", "translucent"):
            add("glass_crystal", 0.72, "vertex alpha with glass/crystal token")
    if workflow == "specular_glossiness":
        add("specular_glossiness_source", 0.78, "specular/glossiness workflow")
    if not classes:
        add("generic_surface", 0.35, "no specific source PBR class evidence")
    return tuple(classes)


def _material_authority_risk_flags(
    *,
    binding_rows: Sequence[FinalPackageBindingRow],
    texture_outputs: Sequence[Mapping[str, object]],
    sidecar_reports: Sequence[Mapping[str, object]],
    source_materials: Sequence[Mapping[str, object]],
    unknowns: Sequence[Mapping[str, object]],
    inherited_count: int,
    warnings: Sequence[str],
    preflight_errors: Sequence[str],
    require_source_owned_colors: bool,
) -> Tuple[str, ...]:
    flags: List[str] = []
    if preflight_errors:
        flags.append("preflight_blockers")
    if any(row.status == FINAL_PREVIEW_MISSING_DDS for row in tuple(binding_rows or ())):
        flags.append("missing_final_dds")
    if any(row.binding_source == FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC for row in tuple(binding_rows or ())):
        flags.append("path_mismatch_basename_only")
    if any(bool(row.get("stock_or_shared")) for row in tuple(texture_outputs or ())):
        flags.append("stock_shared_texture_override")
    for row in tuple(texture_outputs or ()):
        validation = row.get("dds_validation")
        if isinstance(validation, Mapping):
            validation_status = str(validation.get("status", "") or "").strip().lower()
            texconv_format = str(validation.get("texconv_format", "") or "").strip()
            try:
                width = int(validation.get("width", 0) or 0)
                height = int(validation.get("height", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                width = 0
                height = 0
            if validation_status in {"invalid", "error", "missing_payload"}:
                flags.append("invalid_dds_payload")
            if width <= 0 or height <= 0:
                flags.append("missing_dds_dimensions")
            if not texconv_format:
                flags.append("missing_dds_format")
            if bool(validation.get("requires_pathc")):
                flags.append("dds_requires_pathc")
            finding_codes = {
                str(finding.get("code", "") or "")
                for finding in tuple(validation.get("findings", ()) or ())
                if isinstance(finding, Mapping)
            }
            if "missing_mips" in finding_codes:
                flags.append("missing_dds_mips")
            if "payload_truncated" in finding_codes:
                flags.append("truncated_dds_payload")
        role_codes = {
            str(diagnostic.get("code", "") or "")
            for diagnostic in tuple(row.get("role_diagnostics", ()) or ())
            if isinstance(diagnostic, Mapping)
        }
        if "normal_format_not_bc5" in role_codes or "normal_srgb_format" in role_codes:
            flags.append("normal_format_mismatch")
        if "normal_y_policy_unconfirmed" in role_codes:
            flags.append("normal_y_policy_unconfirmed")
        if "base_texture_used_as_emissive" in role_codes:
            flags.append("base_texture_used_as_emissive")
        if "texture_bound_to_visible_and_technical_roles" in role_codes:
            flags.append("visible_technical_role_conflict")
        if "multi_role_texture_binding" in role_codes:
            flags.append("ambiguous_texture_role_binding")
        if "visible_color_technical_format" in role_codes:
            flags.append("visible_color_format_mismatch")
        if "technical_slot_srgb_format" in role_codes:
            flags.append("technical_slot_srgb_format")
        conversion_policy = row.get("conversion_policy")
        role_classes = {
            str(value or "").strip().lower()
            for value in tuple(conversion_policy.get("bound_role_classes", ()) if isinstance(conversion_policy, Mapping) else ())
            if str(value or "").strip()
        }
        luma_mean = _material_authority_float(row.get("visible_luma_mean"), -1.0)
        if "base_color" in role_classes and 0.0 <= luma_mean < 45.0:
            flags.append("dark_visible_color_output")
    for material in tuple(source_materials or ()):
        section_rows = tuple(row for row in tuple(material.get("sections", ()) or ()) if isinstance(row, Mapping))
        if not section_rows:
            flags.append("missing_source_material_sections")
        for section in section_rows:
            try:
                vertex_count = int(section.get("vertex_count", 0) or 0)
                face_count = int(section.get("face_count", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                vertex_count = 0
                face_count = 0
            if vertex_count <= 0 or face_count <= 0:
                flags.append("source_material_section_missing_geometry")
        diagnostic_codes = {
            str(diagnostic.get("code", "") or "")
            for diagnostic in tuple(material.get("diagnostics", ()) or ())
            if isinstance(diagnostic, Mapping)
        }
        missing_channels = {
            str(channel)
            for channel in tuple(material.get("missing_channels", ()) or ())
            if str(channel).strip()
        }
        if "source_missing_base_color" in diagnostic_codes:
            flags.append("source_missing_base_color")
        if "source_alpha_without_opacity_texture" in diagnostic_codes:
            flags.append("source_alpha_missing_opacity")
        if "source_spec_gloss_texture_as_base_color" in diagnostic_codes:
            flags.append("source_spec_gloss_base_conflict")
        if {"roughness", "metalness"}.issubset(missing_channels):
            flags.append("source_missing_roughness_metalness")
        if "source_emissive_scalar_no_texture" in diagnostic_codes:
            flags.append("source_emissive_scalar_no_texture")
    if inherited_count:
        flags.append("inherited_target_influence")
    if unknowns:
        flags.append("unknown_material_response")
    if require_source_owned_colors and not sidecar_reports:
        flags.append("missing_material_sidecar")
    warning_text = "\n".join(str(warning) for warning in tuple(warnings or ())).lower()
    for token, flag in (
        ("orphan dds", "orphan_dds"),
        ("draw-order fallback", "preview_draw_order_fallback"),
        ("fewer visible texture", "preview_export_mismatch"),
        ("not referenced by parsed material sidecar", "orphan_dds"),
        ("normal-looking", "normal_slot_suspicious"),
    ):
        if token in warning_text:
            flags.append(flag)
    return tuple(_dedupe(flags))


def _slot_role(parameter_name: str, texture_path: str) -> Tuple[str, str, bool]:
    parameter_normalized = re.sub(r"[^a-z0-9]+", "", str(parameter_name or "").lower())
    normalized = re.sub(r"[^a-z0-9]+", "", f"{parameter_name} {PurePosixPath(texture_path).name}".lower())
    if any(token in normalized for token in ("emissive", "glow", "illum")):
        return "emissive", "Emissive", True
    classification = classify_texture_binding(parameter_name, texture_path)
    slot_kind = str(getattr(classification, "slot_kind", "") or "").strip().lower() or "material"
    semantic_type = str(getattr(classification, "semantic_type", "") or "").strip().lower()
    combined = f"{parameter_name} {texture_path}".lower()
    if "detailmasktexture" in parameter_normalized:
        visualized = bool(getattr(classification, "visualized", False)) or slot_kind in {
            "detail_mask",
            "material_mask",
        }
        return "material", "Detail Mask", visualized
    if any(token in parameter_normalized for token in ("normaltexture", "normalmap", "detailnormal", "wrinklenormal", "grimenormal", "damagenormal")):
        return "normal", "Normal", True
    if any(token in parameter_normalized for token in ("heighttexture", "displacement", "parallax", "bump")):
        return "height", "Height", True
    if any(token in parameter_normalized for token in ("roughness", "metallic", "metalness", "occlusion", "materialtexture", "materialmask", "colorblendingmask")):
        return "material", "Material / Mask", True
    if any(token in parameter_normalized for token in ("basecolortexture", "overlaycolortexture", "diffusetexture", "albedotexture")):
        return "base", "Base / Color", True
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


def _binding_row_parameter_key(row: FinalPackageBindingRow) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(row.parameter_name or "").strip().lower())


def _binding_row_is_exact_generated_ready(row: FinalPackageBindingRow) -> bool:
    return (
        row.status == FINAL_PREVIEW_READY
        and row.binding_source == FINAL_PREVIEW_BINDING_GENERATED
        and row.confidence == "exact"
    )


def _binding_row_is_source_visible_authority(row: FinalPackageBindingRow) -> bool:
    if not _binding_row_is_exact_generated_ready(row):
        return False
    parameter_key = _binding_row_parameter_key(row)
    if row.role in {"Base / Color", "Emissive"}:
        return True
    if any(
        token in parameter_key
        for token in (
            "overlaycolor",
            "basecolor",
            "diffuse",
            "albedo",
            "colortexture",
            "emissive",
        )
    ):
        return True
    return row.role == "Material / Mask" and "colorblendingmask" in parameter_key


def _binding_row_is_preserved_layer_color(row: FinalPackageBindingRow) -> bool:
    if row.role not in {"Base / Color", "Emissive"}:
        return False
    parameter_key = _binding_row_parameter_key(row)
    if not any(token in parameter_key for token in ("grimediffuse", "detaildiffuse")):
        return False
    return _is_stock_or_shared_texture_path(row.texture_path)


def _binding_row_is_relief_support_only(row: FinalPackageBindingRow) -> bool:
    if row.role not in {"Height", "Detail Mask"}:
        return False
    parameter_key = _binding_row_parameter_key(row)
    if any(token in parameter_key for token in ("diffuse", "albedo", "basecolor", "colorblending", "materialtexture", "grime")):
        return False
    return any(token in parameter_key for token in SOURCE_OWNED_ALLOWED_RELIEF_SUPPORT_PARAMETER_TOKENS)


def _source_owned_material_binding_contract(
    material_key: str,
    display_name: str,
    rows: Sequence[FinalPackageBindingRow],
    *,
    strict: bool = False,
    allow_inherited_layer_color_bindings: bool = False,
    allow_relief_support: bool = False,
    allow_detail_mask_material: bool = False,
) -> CDMaterialBindingContract:
    fatal_errors: List[str] = []
    contract_warnings: List[str] = []
    source_visible_rows = [row for row in rows if _binding_row_is_source_visible_authority(row)]
    generated_rows = [row for row in rows if _binding_row_is_exact_generated_ready(row)]
    original_visible_rows = [
        row
        for row in rows
        if row.role in {"Base / Color", "Emissive"}
        and row.binding_source == FINAL_PREVIEW_BINDING_ORIGINAL
        and row.status == FINAL_PREVIEW_READY
        and not (
            allow_inherited_layer_color_bindings
            and _binding_row_is_preserved_layer_color(row)
        )
    ]
    original_support_rows = [
        row
        for row in rows
        if row.role in {"Normal", "Height", "Material / Mask", "Detail Mask"}
        and row.binding_source == FINAL_PREVIEW_BINDING_ORIGINAL
        and not (allow_relief_support and _binding_row_is_relief_support_only(row))
    ]
    missing_support_roles = [
        role
        for role in ("Normal", "Height", "Material / Mask", "Detail Mask")
        if not any(
            row.role == role and _binding_row_is_exact_generated_ready(row)
            for row in rows
        )
    ]
    if (
        allow_detail_mask_material
        and "Material / Mask" in missing_support_roles
        and any(row.role == "Detail Mask" and _binding_row_is_exact_generated_ready(row) for row in rows)
    ):
        missing_support_roles = [role for role in missing_support_roles if role != "Material / Mask"]

    if original_visible_rows:
        detail = ", ".join(
            f"{row.parameter_name or row.role}->{row.texture_path or '(empty)'}"
            for row in original_visible_rows[:3]
        )
        message = f"Complete source-owned swap still inherits visible color from the game archive: {display_name} ({detail})."
        if strict:
            fatal_errors.append(message)
        else:
            contract_warnings.append(message)
    if not source_visible_rows:
        message = (
            "Complete source-owned draw slot has no exact generated source-visible color authority binding: "
            f"{display_name}. CD may render through original tint/mask response until the wrapper/profile exposes "
            "_overlayColorTexture or a calibrated _colorBlendingMaskTexture path."
        )
        if strict:
            fatal_errors.append(message)
        else:
            contract_warnings.append(message)
    elif not any(row.role in {"Base / Color", "Emissive"} for row in source_visible_rows):
        contract_warnings.append(
            "Complete source-owned draw slot uses generated CD mask/color-blend data as color authority, "
            f"not a native base/overlay texture: {display_name}."
        )

    if missing_support_roles:
        fatal_missing_support_roles = [
            role
            for role in missing_support_roles
            if not (allow_relief_support and role in {"Height", "Detail Mask"})
        ]
        message = (
            f"Complete source-owned draw slot is missing generated optional support binding(s): {display_name} "
            f"({', '.join(missing_support_roles)})."
        )
        if strict and fatal_missing_support_roles:
            fatal_errors.append(message)
        else:
            contract_warnings.append(message)
    if original_support_rows:
        detail = ", ".join(
            f"{row.parameter_name or row.role}->{row.texture_path or '(empty)'}"
            for row in original_support_rows[:4]
        )
        message = f"Complete source-owned draw slot keeps original support texture binding(s): {display_name} ({detail})."
        if strict:
            fatal_errors.append(message)
        else:
            contract_warnings.append(message)
    if not rows:
        message = (
            f"Complete source-owned draw slot has no parsed texture parameters in the patched sidecar wrapper: {display_name}."
        )
        if strict:
            fatal_errors.append(message)
        else:
            contract_warnings.append(message)
    elif not generated_rows:
        contract_warnings.append(
            f"Complete source-owned draw slot has no exact generated DDS binding in parsed sidecar rows: {display_name}."
        )
    return CDMaterialBindingContract(
        material_key=material_key,
        display_name=display_name,
        fatal_errors=tuple(_dedupe(fatal_errors)),
        warnings=tuple(_dedupe(contract_warnings)),
        source_visible_binding_count=len(source_visible_rows),
    )


def _rows_for_source_owned_contract(
    material_key: str,
    rows_by_material: Mapping[str, Sequence[FinalPackageBindingRow]],
    binding_rows: Sequence[FinalPackageBindingRow],
) -> List[FinalPackageBindingRow]:
    rows = list(rows_by_material.get(material_key, ()) or ())
    if rows:
        return rows
    return [
        row
        for row in binding_rows
        if material_key
        and material_key
        in {
            _material_key(getattr(row, "material_name", "")),
            _material_key(getattr(row, "part_name", "")),
        }
    ]


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
        if role_key == "base" or (role_key == "emissive" and not str(getattr(mesh, "preview_texture_path", "") or "").strip()):
            mesh.preview_texture_path = preview_texture_path
            mesh.preview_base_texture_default_name = texture_name
            mesh.preview_texture_flip_vertical = False
        elif role_key == "normal":
            mesh.preview_normal_texture_path = preview_texture_path
            mesh.preview_normal_texture_name = texture_name
            mesh.preview_normal_texture_strength = 0.75
        elif role_key == "height":
            mesh.preview_height_texture_path = preview_texture_path
            mesh.preview_height_texture_name = texture_name
        elif role_key == "material":
            parameter_key = re.sub(r"[^a-z0-9]+", "", str(parameter_name or "").lower())
            if (
                "detailmasktexture" in parameter_key
                and str(getattr(mesh, "preview_material_texture_path", "") or "").strip()
            ):
                continue
            semantic_type, semantic_subtype, packed_channels = _material_semantics_for_binding(parameter_name, texture_path or texture_name)
            mesh.preview_material_texture_path = preview_texture_path
            mesh.preview_material_texture_name = texture_name
            mesh.preview_material_texture_type = semantic_type
            mesh.preview_material_texture_subtype = semantic_subtype
            mesh.preview_material_texture_packed_channels = tuple(packed_channels)


def _assign_unmatched_visible_textures_by_order(
    preview_model: ModelPreviewData,
    binding_rows: Sequence[FinalPackageBindingRow],
) -> Tuple[int, Tuple[str, ...]]:
    ready_visible_rows = [
        row
        for row in binding_rows
        if row.role in {"Base / Color", "Emissive"}
        and row.status == FINAL_PREVIEW_READY
        and row.confidence == "exact"
        and str(row.preview_texture_path or "").strip()
    ]
    if not ready_visible_rows:
        return 0, ()
    unmatched_meshes = [
        (index, mesh)
        for index, mesh in enumerate(getattr(preview_model, "meshes", []) or [])
        if not str(getattr(mesh, "preview_texture_path", "") or "").strip()
    ]
    assigned_count = 0
    assignment_details: List[str] = []
    for (mesh_index, _mesh), row in zip(unmatched_meshes, ready_visible_rows):
        target_name = _material_label_for_mesh(_mesh, mesh_index)
        source_name = str(row.material_name or row.part_name or row.parameter_name or "source material").strip()
        if source_name or target_name:
            assignment_details.append(f"{source_name or 'source material'} -> {target_name or f'mesh {mesh_index}'}")
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
    return assigned_count, tuple(assignment_details)


def _fallback_assignment_detail(details: Sequence[str]) -> str:
    clean = _dedupe(str(detail) for detail in details if str(detail or "").strip())
    if not clean:
        return ""
    return " Examples: " + ", ".join(clean[:4]) + (" ..." if len(clean) > 4 else "")


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
        "cdmw_material_authority_report.json",
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
    source_path: str | Path = "",
    export_options: object = None,
    texconv_path: Optional[Path] = None,
    original_dds_resolver: Optional[Callable[[str], Optional[Path]]] = None,
    original_dds_basename_resolver: Optional[Callable[[str], Sequence[Path]]] = None,
    package_root: Optional[Path] = None,
    require_source_owned_colors: bool = False,
    strict_source_owned_material_contract: bool = False,
    allow_inherited_layer_color_bindings: bool = False,
    material_authority_contract: str = "",
    render_settings: object = None,
) -> FinalPackagePreviewResult:
    """Build the texture-authoritative mesh preview for the package payloads that would be exported."""

    warnings: List[str] = []
    authority_contract = re.sub(r"[^a-z0-9_]+", "_", str(material_authority_contract or "").strip().lower()).strip("_")
    runtime_xml_preserve_contract = authority_contract == "runtime_xml_preserve" or bool(
        allow_inherited_layer_color_bindings
    )
    true_source_authority_contract = authority_contract.startswith("true_source_authority") or bool(
        strict_source_owned_material_contract
    )
    relief_support_allowed = "relief_support" in authority_contract
    detail_mask_material_allowed = "detail_mask" in authority_contract
    allow_inherited_layer_color_bindings = bool(runtime_xml_preserve_contract)
    strict_source_owned_material_contract = bool(true_source_authority_contract)
    source_owned_binding_contract_enabled = bool(require_source_owned_colors)
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
    source_path_text = str(source_path or "").replace("\\", "/").strip()
    if not source_path_text:
        source_path_text = str(getattr(getattr(preview_result, "preview_model", None), "path", "") or getattr(getattr(preview_result, "parsed_mesh", None), "path", "") or "").replace("\\", "/")

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
                note=str(getattr(spec, "note", "") or ""),
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
    sidecar_structure_errors: List[str] = []
    sidecar_submesh_resource_names: List[str] = []
    for sidecar_path, spec in sidecars.values():
        sidecar_text = _spec_payload_text(spec)
        if require_source_owned_colors:
            sidecar_structure_errors.extend(_pac_xml_material_wrapper_structure_errors(sidecar_text, sidecar_path))
            sidecar_structure_errors.extend(_pac_xml_material_shader_name_errors(sidecar_text, sidecar_path))
            sidecar_structure_errors.extend(_pac_xml_submesh_resource_idbase_errors(sidecar_text, sidecar_path))
            sidecar_submesh_resource_names.extend(_pac_xml_submesh_resource_wrapper_names(sidecar_text, sidecar_path))
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
                if status == FINAL_PREVIEW_READY and confidence == "exact" and visualized:
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

    fallback_assignment_count, fallback_assignment_details = _assign_unmatched_visible_textures_by_order(preview_model, binding_rows)
    if fallback_assignment_count:
        warnings.append(
            "Final preview assigned visible textures by draw-order fallback for "
            f"{fallback_assignment_count:,} unmatched mesh batch(es). This is preview-only; material names did not match final sidecar bindings exactly."
            + _fallback_assignment_detail(fallback_assignment_details)
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
        if _binding_row_is_source_visible_authority(row)
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
    planned_placeholder_material_keys: set[str] = set()
    planned_source_owned_material_keys: set[str] = set()
    planned_source_owned_material_display: Dict[str, str] = {}
    if require_source_owned_colors:
        available_source_owned_contract_keys = set(rows_by_material) | {
            _material_key(name)
            for name in tuple(sidecar_submesh_resource_names or ())
            if _material_key(name)
        }

        def select_source_owned_contract_name(section: object) -> str:
            candidates = _dedupe(
                str(name or "").strip()
                for name in (
                    getattr(section, "target_submesh_name", ""),
                    getattr(section, "runtime_material_name", ""),
                    getattr(section, "runtime_slot_name", ""),
                    getattr(section, "atlas_material_name", ""),
                    getattr(section, "source_material_name", ""),
                )
                if str(name or "").strip()
            )
            for candidate in candidates:
                key = _material_key(candidate)
                if key and key in available_source_owned_contract_keys:
                    return candidate
            return candidates[0] if candidates else ""

        for section in getattr(preview_result, "source_owned_output_draw_sections", ()) or ():
            if tuple(getattr(section, "source_submesh_indices", ()) or ()):
                name = select_source_owned_contract_name(section)
                key = _material_key(name)
                if key:
                    planned_source_owned_material_keys.add(key)
                    planned_source_owned_material_display.setdefault(key, str(name or "").strip() or key)
                continue
            for name in (
                getattr(section, "target_submesh_name", ""),
                getattr(section, "donor_material_name", ""),
            ):
                key = _material_key(name)
                if key:
                    planned_placeholder_material_keys.add(key)
    preflight_errors: List[str] = []
    for row in binding_rows:
        row_material_key = _material_key(getattr(row, "material_name", ""))
        row_is_planned_placeholder = bool(row_material_key and row_material_key in planned_placeholder_material_keys)
        row_is_planned_source_owned = bool(row_material_key and row_material_key in planned_source_owned_material_keys)
        basename = PurePosixPath(str(row.texture_path or "").replace("\\", "/")).name.lower()
        stem = PurePosixPath(basename).stem.lower()
        parameter_key = re.sub(r"[^a-z0-9]+", "", str(row.parameter_name or "").lower())
        if row.binding_source == FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC:
            preflight_errors.append(
                f"Exact texture path mismatch: {row.sidecar_path} -> {row.texture_path}. A same-basename DDS exists, but the packaged path does not match."
            )
        if (
            not row_is_planned_placeholder
            and row.role in {"Base / Color", "Emissive"}
            and row.status in {FINAL_PREVIEW_MISSING_DDS, FINAL_PREVIEW_DECODE_FAILED}
        ):
            message = (
                f"Visible color texture is not package-resolved: "
                f"{row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
            )
            if (
                require_source_owned_colors
                and row_is_planned_source_owned
                and any(token in parameter_key for token in SOURCE_OWNED_FORBIDDEN_ORIGINAL_PARAMETER_TOKENS)
                and not strict_source_owned_material_contract
            ):
                warnings.append(message)
            else:
                preflight_errors.append(message)
        if (
            not row_is_planned_placeholder
            and row.role == "Base / Color"
            and stem.endswith(("_mg", "_sp", "_n", "_normal", "_disp", "_height"))
        ):
            preflight_errors.append(
                f"Support map is bound as visible base color: {row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
            )
        if (
            not row_is_planned_placeholder
            and
            any(token in parameter_key for token in ("basecolor", "overlaycolor", "diffuse", "albedo", "colortexture"))
            and stem.endswith(("_mg", "_sp", "_n", "_normal", "_disp", "_height"))
        ):
            preflight_errors.append(
                f"Support map path is assigned to a visible color parameter: {row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
            )
        if (
            source_owned_binding_contract_enabled
            and row.role in {"Base / Color", "Emissive"}
            and row.status == FINAL_PREVIEW_READY
            and row.binding_source != FINAL_PREVIEW_BINDING_GENERATED
            and row_is_planned_source_owned
            and not row_is_planned_placeholder
            and not (
                allow_inherited_layer_color_bindings
                and _binding_row_is_preserved_layer_color(row)
            )
        ):
            message = (
                f"Complete source-owned swap still inherits visible color from the game archive: "
                f"{row.material_name} -> {row.texture_path}."
            )
            if true_source_authority_contract:
                preflight_errors.append(message)
            else:
                warnings.append(message)
        if (
            source_owned_binding_contract_enabled
            and row_is_planned_source_owned
            and not row_is_planned_placeholder
            and row.role in {"Base / Color", "Emissive", "Normal", "Height", "Material / Mask", "Detail Mask"}
            and row.binding_source == FINAL_PREVIEW_BINDING_ORIGINAL
        ):
            message = (
                f"Complete source-owned slot still inherits original {row.role} binding: "
                f"{row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
            )
            if (
                allow_inherited_layer_color_bindings
                and _binding_row_is_preserved_layer_color(row)
                and not strict_source_owned_material_contract
            ):
                warnings.append(message)
            elif runtime_xml_preserve_contract:
                warnings.append(message)
            elif relief_support_allowed and _binding_row_is_relief_support_only(row):
                warnings.append(message)
            elif strict_source_owned_material_contract:
                preflight_errors.append(message)
            else:
                warnings.append(message)
        if (
            source_owned_binding_contract_enabled
            and row_is_planned_source_owned
            and not row_is_planned_placeholder
            and row.binding_source != FINAL_PREVIEW_BINDING_GENERATED
            and any(token in parameter_key for token in SOURCE_OWNED_FORBIDDEN_ORIGINAL_PARAMETER_TOKENS)
        ):
            message = (
                f"Complete source-owned wrapper still has non-generated original/support material parameter: "
                f"{row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
            )
            if relief_support_allowed and _binding_row_is_relief_support_only(row):
                warnings.append(message)
            elif strict_source_owned_material_contract:
                preflight_errors.append(message)
            else:
                warnings.append(message)
    if source_owned_binding_contract_enabled and planned_source_owned_material_keys:
        for material_key in sorted(planned_source_owned_material_keys):
            if material_key in planned_placeholder_material_keys:
                continue
            rows = _rows_for_source_owned_contract(material_key, rows_by_material, binding_rows)
            display_name = planned_source_owned_material_display.get(material_key) or material_display_by_key.get(material_key) or material_key
            contract = _source_owned_material_binding_contract(
                material_key,
                display_name,
                rows,
                strict=bool(strict_source_owned_material_contract),
                allow_inherited_layer_color_bindings=bool(allow_inherited_layer_color_bindings),
                allow_relief_support=bool(relief_support_allowed),
                allow_detail_mask_material=bool(detail_mask_material_allowed),
            )
            preflight_errors.extend(contract.fatal_errors)
            warnings.extend(contract.warnings)
    if orphan_payload_paths:
        preflight_errors.append(
            "Generated/copied DDS payloads are not referenced by parsed material sidecars: "
            + ", ".join(orphan_payload_paths[:8])
            + (" ..." if len(orphan_payload_paths) > 8 else "")
        )
    if source_owned_binding_contract_enabled and not sidecars:
        message = "Complete source-owned swap has no packaged material sidecar payload to control visible color."
        if true_source_authority_contract:
            preflight_errors.append(message)
        else:
            warnings.append(message)
    if source_owned_binding_contract_enabled and source_visible_texture_count > final_visible_texture_count:
        message = (
            "Complete source-owned swap lost visible texture coverage in the final package contract "
            f"({final_visible_texture_count:,}/{source_visible_texture_count:,})."
        )
        if strict_source_owned_material_contract:
            preflight_errors.append(message)
        else:
            warnings.append(message)
    if source_owned_binding_contract_enabled and fallback_assignment_count:
        message = (
            "Complete source-owned swap final preview used draw-order fallback for "
            f"{fallback_assignment_count:,} mesh batch(es); generated material names did not match patched sidecar bindings."
            + _fallback_assignment_detail(fallback_assignment_details)
        )
        if strict_source_owned_material_contract:
            preflight_errors.append(message)
        else:
            warnings.append(message)
    if require_source_owned_colors:
        preflight_errors.extend(_pac_runtime_abi_preflight_errors(bytes(getattr(effective_preview_result, "rebuilt_data", b"") or b""), preview_result))
        source_meshes = list(getattr(getattr(preview_result, "preview_model", None), "meshes", []) or [])
        visible_material_names = [_material_label_for_mesh(mesh, index) for index, mesh in enumerate(getattr(preview_model, "meshes", []) or [])]
        preflight_errors.extend(
            _pac_xml_submesh_resource_order_errors(sidecar_submesh_resource_names, visible_material_names)
        )
        visible_material_keys = {_material_key(name) for name in visible_material_names if _material_key(name)}
        parsed_material_keys: set[str] = set()
        parsed_mesh = getattr(preview_result, "parsed_mesh", None)
        for submesh in getattr(parsed_mesh, "submeshes", ()) or ():
            parsed_material_keys.update(
                _material_key(name)
                for name in (
                    getattr(submesh, "material", ""),
                    getattr(submesh, "name", ""),
                    getattr(submesh, "texture", ""),
                )
                if _material_key(name)
            )
        planned_material_keys: set[str] = set()
        for section in getattr(preview_result, "source_owned_output_draw_sections", ()) or ():
            planned_material_keys.update(
                _material_key(name)
                for name in (
                    getattr(section, "target_submesh_name", ""),
                    getattr(section, "donor_material_name", ""),
                )
                if _material_key(name)
            )
        valid_sidecar_material_keys = visible_material_keys | parsed_material_keys | planned_material_keys
        stale_sidecar_names = [
            name
            for name in sidecar_submesh_resource_names
            if _material_key(name) and _material_key(name) not in valid_sidecar_material_keys
        ]
        if source_owned_binding_contract_enabled and true_source_authority_contract and stale_sidecar_names:
            stale_names = _dedupe(stale_sidecar_names)
            preflight_errors.append(
                "Complete source-owned swap PAC XML still contains stale original _subMeshResources wrapper(s) "
                "that are not rebuilt PAC draw sections: "
                + ", ".join(stale_names[:8])
                + (" ..." if len(stale_names) > 8 else "")
            )
        missing_source_owned_materials: List[str] = []
        for index, mesh in enumerate(getattr(preview_model, "meshes", []) or []):
            source_mesh = source_meshes[index] if index < len(source_meshes) else None
            if source_mesh is not None and not str(getattr(source_mesh, "preview_texture_path", "") or "").strip():
                continue
            if str(getattr(mesh, "preview_texture_path", "") or "").strip():
                continue
            material_name = _material_label_for_mesh(mesh, index)
            if material_name:
                missing_source_owned_materials.append(material_name)
        if source_owned_binding_contract_enabled and missing_source_owned_materials:
            missing_names = _dedupe(missing_source_owned_materials)
            message = (
                "Complete source-owned swap has no exact generated visible sidecar/DDS binding for: "
                + ", ".join(missing_names[:8])
                + (" ..." if len(missing_names) > 8 else "")
            )
            if strict_source_owned_material_contract:
                preflight_errors.append(message)
            else:
                warnings.append(message)
    if require_source_owned_colors and sidecar_structure_errors:
        preflight_errors.extend(sidecar_structure_errors)
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
    if require_source_owned_colors:
        if runtime_xml_preserve_contract:
            summary_lines.append(
                "Material Authority: Runtime XML preserve; stock layer/support bindings are allowed and may affect the final in-game look."
            )
        elif true_source_authority_contract:
            summary_lines.append(
                "Material Authority: True Source Authority; original visible/support influence is blocked for active source-owned wrappers."
            )
            if not preflight_errors:
                summary_lines.append(
                    "Source authority complete: active source-owned wrappers resolved to source/generated/neutral material bindings."
                )
    if preflight_errors:
        summary_lines.append(f"Preflight blocker(s): {len(preflight_errors):,}")
    if likely_grey_materials:
        summary_lines.append(f"Likely grey material(s): {', '.join(likely_grey_materials[:8])}" + (" ..." if len(likely_grey_materials) > 8 else ""))
    if missing_paths:
        summary_lines.append(f"Missing final DDS payload path(s): {len(_dedupe(missing_paths)):,}")
    texture_resolution_manifest = _build_texture_resolution_manifest(binding_rows, _dedupe(warnings))
    material_authority_report = _build_material_authority_report(
        preview_result,
        source_path=source_path_text,
        final_preview_model=preview_model,
        package_root=package_root_text,
        authority_contract=authority_contract,
        sidecars=sidecars,
        dds_by_path=dds_by_path,
        binding_rows=binding_rows,
        material_statuses=material_statuses,
        texture_resolution_manifest=texture_resolution_manifest,
        warnings=_dedupe(warnings),
        preflight_errors=preflight_errors,
        require_source_owned_colors=require_source_owned_colors,
        strict_source_owned_material_contract=strict_source_owned_material_contract,
        allow_inherited_layer_color_bindings=allow_inherited_layer_color_bindings,
        render_settings=render_settings,
    )
    if texture_resolution_manifest.rows:
        summary_lines.append(f"Texture resolution manifest rows: {len(texture_resolution_manifest.rows):,}")
    if material_authority_report.risk_flags:
        summary_lines.append("Material authority risk flags: " + ", ".join(material_authority_report.risk_flags[:8]))

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
        material_authority_report=material_authority_report,
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
