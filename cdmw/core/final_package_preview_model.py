from __future__ import annotations

import dataclasses
import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from cdmw.core.archive_loose_export import _mesh_loose_export_payload_path
from cdmw.core.archive_mesh_import_preview import parsed_mesh_to_preview_model
from cdmw.core.archive_mesh_types import MeshImportPreviewResult, MeshImportSupplementalFileSpec
from cdmw.core.archive_modding_constants import MESH_IMPORT_SIDECAR_EXTENSIONS
from cdmw.core.temp_cache import app_temp_cache_path, request_app_temp_cache_prune
from cdmw.models import ModelPreviewData, ModelPreviewMesh
from cdmw.modding.mesh_parser import parse_mesh

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
) -> Tuple[str, str]:
    dds_path = _payload_preview_file(payload)
    try:
        from cdmw.core.texture_pipeline.inspection import parse_dds
        from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png

        dds_info = None
        try:
            dds_info = parse_dds(dds_path)
        except Exception:
            dds_info = None
        preview_path = ensure_dds_display_preview_png(dds_path, dds_info=dds_info)
        return Path(preview_path).as_posix(), ""
    except Exception as exc:
        return "", str(exc)


def _preview_texture_path_for_original(
    dds_path: Path,
) -> Tuple[str, str]:
    if not isinstance(dds_path, Path):
        return "", "Original DDS resolver did not return a file path."
    source = dds_path.expanduser()
    if not source.is_file():
        return "", f"Original DDS file is unavailable: {source}"
    try:
        from cdmw.core.texture_pipeline.inspection import parse_dds
        from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png

        dds_info = None
        try:
            dds_info = parse_dds(source)
        except Exception:
            dds_info = None
        preview_path = ensure_dds_display_preview_png(source, dds_info=dds_info)
        return Path(preview_path).as_posix(), ""
    except Exception as exc:
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
