from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_mesh_types import MeshImportPreviewResult
from cdmw.domain.textures.semantics import is_stock_or_shared_texture_path
from cdmw.models import ModelPreviewData
from cdmw.modding.asset_replacement import classify_texture_binding

FINAL_PREVIEW_READY = "ready"
FINAL_PREVIEW_BINDING_GENERATED = "generated"
FINAL_PREVIEW_BINDING_ORIGINAL = "original"

SOURCE_OWNED_ALLOWED_RELIEF_SUPPORT_PARAMETER_TOKENS = (
    "heighttexture",
    "detailmask",
    "detailnormal",
    "detailheight",
)

TEXTURE_PLAN_STATUS_READY = "Ready"

TEXTURE_PLAN_STATUS_REVIEW = "Review"

TEXTURE_PLAN_STATUS_SUPPORT_ONLY = "Support only"

TEXTURE_PLAN_STATUS_LIKELY_GREY = "Likely grey"

TEXTURE_PLAN_STATUS_IGNORED_ADVANCED = "Ignored / advanced"


@dataclass(slots=True, frozen=True)
class CDMaterialBindingContract:
    material_key: str
    display_name: str
    fatal_errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    source_visible_binding_count: int = 0


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

def _preview_helper(name: str):
    from . import final_package_preview

    return getattr(final_package_preview, name)


def simplified_part_label(label: object, *, fallback_index: int | None = None) -> str:
    return _preview_helper("simplified_part_label")(label, fallback_index=fallback_index)


def _display_path(path: object) -> str:
    return _preview_helper("_display_path")(path)


def _material_key(value: object) -> str:
    return _preview_helper("_material_key")(value)


def _material_semantics_for_binding(parameter_name: str, texture_path: str):
    return _preview_helper("_material_semantics_for_binding")(parameter_name, texture_path)


def _material_label_for_mesh(mesh: object, index: int) -> str:
    return _preview_helper("_material_label_for_mesh")(mesh, index)


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
    expected_support_roles: Optional[Sequence[str]] = None,
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
    expected_support_role_set = (
        {
            str(role or "").strip()
            for role in tuple(expected_support_roles or ())
            if str(role or "").strip()
        }
        if expected_support_roles is not None
        else None
    )
    missing_support_roles = [
        role
        for role in ("Normal", "Height", "Material / Mask", "Detail Mask")
        if expected_support_role_set is None or role in expected_support_role_set
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


def _source_owned_section_source_material_names(section: object) -> Tuple[str, ...]:
    names: List[str] = []
    for value in (
        getattr(section, "source_material_name", ""),
        *tuple(getattr(section, "atlas_source_material_names", ()) or ()),
    ):
        text = str(value or "").strip()
        if text:
            names.append(text)
    for atlas_rect in tuple(getattr(section, "atlas_rects", ()) or ()):
        text = str(getattr(atlas_rect, "source_material_name", "") or "").strip()
        if text:
            names.append(text)
    return tuple(_dedupe(names))


def _source_material_rows_by_key(source_materials: Sequence[Mapping[str, object]]) -> Dict[str, List[Mapping[str, object]]]:
    rows_by_key: Dict[str, List[Mapping[str, object]]] = {}
    for row in tuple(source_materials or ()):
        if not isinstance(row, Mapping):
            continue
        for value in (
            row.get("material_name", ""),
            row.get("runtime_material_name", ""),
        ):
            key = _material_key(str(value or ""))
            if key:
                rows_by_key.setdefault(key, []).append(row)
    return rows_by_key


def _source_expected_support_roles_for_contract(
    material_key: str,
    source_names_by_contract_key: Mapping[str, Sequence[str]],
    source_materials_by_key: Mapping[str, Sequence[Mapping[str, object]]],
) -> Optional[Tuple[str, ...]]:
    source_names = tuple(source_names_by_contract_key.get(material_key, ()) or ())
    if not source_names:
        return None
    roles: List[str] = []
    found_source_row = False
    for name in source_names:
        for row in tuple(source_materials_by_key.get(_material_key(name), ()) or ()):
            found_source_row = True
            roles.extend(_source_material_expected_support_roles(row))
    if not found_source_row:
        return None
    return tuple(_dedupe(roles))


def _source_material_expected_support_roles(row: Mapping[str, object]) -> Tuple[str, ...]:
    channels = {
        str(channel or "").strip().lower()
        for channel in tuple(row.get("detected_channels", ()) or ())
        if str(channel or "").strip()
    }
    explicit_texture_channels: set[str] = set()
    for slot in tuple(row.get("material_inputs", ()) or ()) + tuple(row.get("texture_slots", ()) or ()):
        if not isinstance(slot, Mapping):
            continue
        for value in (
            slot.get("slot_kind", ""),
            slot.get("semantic_type", ""),
            slot.get("semantic_subtype", ""),
            *tuple(slot.get("packed_channels", ()) or ()),
        ):
            _add_expected_support_channel(channels, value)
            _add_expected_support_channel(explicit_texture_channels, value)
    roles: List[str] = []
    if "normal" in explicit_texture_channels:
        roles.append("Normal")
    if "height" in explicit_texture_channels:
        roles.append("Height")
    material_channels = {
        "roughness",
        "roughness_scalar",
        "metalness",
        "metalness_scalar",
        "ao",
        "specular",
        "specular_scalar",
        "glossiness",
        "glossiness_scalar",
        "material",
        "material_mask",
    }
    if material_channels & channels:
        roles.append("Material / Mask")
    if "detail" in channels or "detail_mask" in channels:
        roles.append("Detail Mask")
    return tuple(_dedupe(roles))


def _add_expected_support_channel(channels: set[str], value: object) -> None:
    text = str(value or "").strip().lower()
    if not text:
        return
    if "normal" in text:
        channels.add("normal")
    if any(token in text for token in ("height", "displacement", "bump", "parallax")):
        channels.add("height")
    if any(token in text for token in ("roughness", "rough", "smoothness")):
        channels.add("roughness")
    if any(token in text for token in ("metallic", "metalness", "metal")):
        channels.add("metalness")
    if any(token in text for token in ("ao", "occlusion", "ambientocclusion")):
        channels.add("ao")
    if any(token in text for token in ("specular", "gloss", "specgloss")):
        channels.add("specular")
        channels.add("glossiness")
    if "detail" in text:
        channels.add("detail")


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
    *,
    exclude_kept_original_sidecar: bool = False,
) -> Tuple[int, Tuple[str, ...]]:
    ready_visible_rows = [
        row
        for row in binding_rows
        if row.role in {"Base / Color", "Emissive"}
        and row.status == FINAL_PREVIEW_READY
        and row.confidence == "exact"
        and str(row.preview_texture_path or "").strip()
        and not (
            exclude_kept_original_sidecar
            and str(row.sidecar_path or "").strip().lower() == "kept original sidecar bindings"
        )
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


_is_stock_or_shared_texture_path = is_stock_or_shared_texture_path


def _looks_like_normal_texture_path(texture_path: str) -> bool:
    stem = PurePosixPath(str(texture_path or "").replace("\\", "/")).stem.lower()
    if "normal" in stem or stem.endswith(("_n", "_wn", "_nm", "_nrm", "_nor", "_no")):
        return True
    return bool(re.search(r"(?:^|[_\-.])n(?:$|[_\-.])", stem))


def _looks_like_normal_source_path(source_path: object) -> bool:
    if not isinstance(source_path, Path):
        return False
    return _looks_like_normal_texture_path(source_path.name)


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
