from __future__ import annotations

import math
import re
from pathlib import PurePosixPath
from typing import (
    Mapping,
    Optional,
    Tuple,
)

from cdmw.models import (
    ArchiveEntry,
    ModelPreviewMesh,
    PreviewMaterialTextureInput,
)
from cdmw.core.archive_model_references import (
    _ArchiveModelSidecarTextureBinding,
    _normalize_model_texture_reference,
)

from cdmw.core.archive_model_texture_semantics import (
    _append_model_preview_material_input,
    _is_placeholder_model_texture,
    _iter_model_submesh_reference_candidates,
)


_AUTHORITATIVE_BASE_SOURCE_KINDS = {
    "crimson_albedo",
    "crimson_base_color",
    "crimson_color",
    "crimson_diffuse",
    "crimson_overlay_color",
}


def _sidecar_parameter_field(parameter: object, name: str, fallback: object = "") -> object:
    if isinstance(parameter, Mapping):
        return parameter.get(name, fallback)
    return getattr(parameter, name, fallback)


def _normalized_sidecar_parameter_name(parameter: object) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "",
        str(_sidecar_parameter_field(parameter, "parameter_name", "") or "").casefold(),
    )


def _sidecar_parameter_number(parameter: object) -> Optional[float]:
    value = _sidecar_parameter_field(parameter, "numeric_value", None)
    if value is None:
        value = _sidecar_parameter_field(parameter, "value", "")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _sidecar_parameter_enabled(parameter: object) -> bool:
    number = _sidecar_parameter_number(parameter)
    if number is not None:
        return abs(number) > 1.0e-9
    value = str(_sidecar_parameter_field(parameter, "value", "") or "").strip().casefold()
    return value in {"enabled", "on", "true", "yes"}


def _model_sidecar_binding_alpha_mode(binding: _ArchiveModelSidecarTextureBinding) -> str:
    """Return only explicit transparency contracts from material sidecar flags.

    Crimson sidecars contain many unrelated fields with ``blend`` or ``opacity``
    in their names (dye layers, grime blending, and skin detail opacity).  Those
    are not surface transparency, so the match is intentionally exact.
    """

    cutout = False
    for parameter in tuple(getattr(binding, "material_parameters", ()) or ()):
        key = _normalized_sidecar_parameter_name(parameter)
        if key in {
            "alphablend",
            "enablealphablend",
            "usealphablend",
            "transparent",
            "transparencyenabled",
        } and _sidecar_parameter_enabled(parameter):
            return "blend"
        if key in {
            "alphaclip",
            "alphacutout",
            "alphatest",
            "enablealphatest",
            "usealphatest",
        } and _sidecar_parameter_enabled(parameter):
            cutout = True
    return "cutout" if cutout else ""


def _model_sidecar_binding_alpha_cutoff(binding: _ArchiveModelSidecarTextureBinding) -> Optional[float]:
    for parameter in tuple(getattr(binding, "material_parameters", ()) or ()):
        if _normalized_sidecar_parameter_name(parameter) not in {
            "alphaclipthreshold",
            "alphacutoff",
            "alpharef",
            "alphathreshold",
        }:
            continue
        number = _sidecar_parameter_number(parameter)
        if number is None:
            continue
        if number > 1.0:
            number /= 255.0
        return max(0.0, min(0.95, number))
    return None


def _model_sidecar_binding_double_sided(binding: _ArchiveModelSidecarTextureBinding) -> bool:
    for parameter in tuple(getattr(binding, "material_parameters", ()) or ()):
        if _normalized_sidecar_parameter_name(parameter) in {
            "doublesided",
            "enabledoublesided",
            "twosided",
            "usetwosided",
        } and _sidecar_parameter_enabled(parameter):
            return True
    return False

def _model_preview_sidecar_tint(binding: _ArchiveModelSidecarTextureBinding) -> Tuple[float, float, float]:
    tint = tuple(getattr(binding, "tint_color", ()) or ())
    if len(tint) < 3:
        tint = tuple(getattr(binding, "represent_color", ()) or ())
    if len(tint) >= 3:
        return (
            max(0.0, min(2.0, float(tint[0]))),
            max(0.0, min(2.0, float(tint[1]))),
            max(0.0, min(2.0, float(tint[2]))),
        )
    return ()

def _model_preview_sidecar_uv_scale(binding: _ArchiveModelSidecarTextureBinding) -> Tuple[float, float]:
    try:
        uv_scale = float(getattr(binding, "uv_scale", 1.0) or 1.0)
    except (TypeError, ValueError):
        uv_scale = 1.0
    uv_scale = max(0.05, min(64.0, uv_scale))
    if abs(uv_scale - 1.0) <= 1e-6:
        return ()
    return (uv_scale, uv_scale)

def _model_preview_sidecar_material_color(binding: _ArchiveModelSidecarTextureBinding) -> Tuple[float, float, float]:
    color = _model_preview_sidecar_tint(binding)
    if len(color) < 3:
        return ()
    try:
        red = max(0.0, min(1.0, float(color[0])))
        green = max(0.0, min(1.0, float(color[1])))
        blue = max(0.0, min(1.0, float(color[2])))
    except (TypeError, ValueError):
        return ()
    luma = (red * 0.2126) + (green * 0.7152) + (blue * 0.0722)
    saturation = max(red, green, blue) - min(red, green, blue)
    if luma <= 0.018 and saturation <= 0.035:
        return ()
    return (red, green, blue)

def _is_low_authority_model_base_texture(texture_path: str) -> bool:
    normalized = _normalize_model_texture_reference(texture_path)
    if not normalized:
        return False
    if _is_placeholder_model_texture(normalized):
        return True
    basename = PurePosixPath(normalized).name.lower()
    stem = PurePosixPath(normalized).stem.lower()
    if "common_default" in stem and "overlay" in stem:
        return True
    if stem in {"cd_common_default_overlay", "cd_common_default_overlay_old"}:
        return True
    if stem.endswith("_o") or "_overlay" in stem:
        return True
    return False

def _model_preview_base_texture_quality(texture_path: str, *, fallback_only: bool = False) -> str:
    if fallback_only:
        return "material_color_fallback"
    if _is_low_authority_model_base_texture(texture_path):
        return "low_authority_overlay"
    normalized = _normalize_model_texture_reference(texture_path)
    return "resolved_base" if normalized else ""

def _mesh_preview_base_is_low_authority(mesh: ModelPreviewMesh) -> bool:
    quality = str(getattr(mesh, "preview_base_texture_quality", "") or "").strip().lower()
    if quality == "low_authority_overlay":
        return True
    texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
    return _is_low_authority_model_base_texture(texture_name)

def _mesh_existing_base_is_sidecar_identity(
    mesh: ModelPreviewMesh,
    parsed_submesh: Optional[object],
    binding: _ArchiveModelSidecarTextureBinding,
) -> bool:
    sidecar_candidates = _iter_model_submesh_reference_candidates(
        str(getattr(binding, "submesh_name", "") or ""),
        str(getattr(binding, "part_name", "") or ""),
        str(getattr(binding, "material_name", "") or ""),
    )
    if not sidecar_candidates:
        return False
    sidecar_candidate_set = set(sidecar_candidates)
    mesh_candidates = _iter_model_submesh_reference_candidates(
        str(getattr(parsed_submesh, "name", "") or ""),
        str(getattr(parsed_submesh, "material", "") or ""),
        str(getattr(parsed_submesh, "texture", "") or ""),
        str(getattr(mesh, "material_name", "") or ""),
        str(getattr(mesh, "texture_name", "") or ""),
    )
    return any(candidate in sidecar_candidate_set for candidate in mesh_candidates)


def _model_sidecar_binding_can_supply_full_base(
    binding: _ArchiveModelSidecarTextureBinding,
) -> bool:
    """Reject PAC layer/control inputs before visible-base candidate scoring.

    Older sidecars do not carry the PAC authority fields, so they retain the
    historical preview path.  A PAC/PAMI binding with an owner contract must
    prove that it is an exact, promoted color parameter owned by a concrete
    wrapper.  This makes detail, grime, dye, mask, and suffix-only textures
    structurally unable to replace the complete albedo.
    """

    owner_slot_index = int(getattr(binding, "owner_slot_index", -1))
    binding_disposition = str(
        getattr(binding, "binding_disposition", "") or ""
    ).strip().casefold()
    binding_authority = str(
        getattr(binding, "binding_authority", "") or ""
    ).strip().casefold()
    source_kind = str(getattr(binding, "source_kind", "") or "").strip().casefold()
    has_pac_contract = bool(
        owner_slot_index >= 0
        or str(getattr(binding, "owner_wrapper_item_id", "") or "").strip()
        or binding_authority
        or binding_disposition
        or source_kind
    )
    if not has_pac_contract:
        return True
    return bool(
        owner_slot_index >= 0
        and str(getattr(binding, "owner_wrapper_item_id", "") or "").strip()
        and str(getattr(binding, "shader_family", "") or "").strip()
        and binding_authority == "authoritative"
        and binding_disposition == "promoted"
        and source_kind in _AUTHORITATIVE_BASE_SOURCE_KINDS
    )

def _apply_model_sidecar_base_preview(
    mesh: ModelPreviewMesh,
    *,
    texture_entry: ArchiveEntry,
    preview_path_text: str,
    binding: _ArchiveModelSidecarTextureBinding,
    force_unflipped_preview: bool,
    set_texture_name: bool,
) -> None:
    if str(getattr(mesh, "preview_texture_path", "") or "").strip() != preview_path_text:
        mesh.preview_texture_path = preview_path_text
        mesh.preview_texture_image = None
    if force_unflipped_preview:
        mesh.preview_texture_flip_vertical = False
    current_texture_name = str(getattr(mesh, "texture_name", "") or "").strip()
    if set_texture_name or not current_texture_name or not current_texture_name.lower().endswith(".dds"):
        mesh.texture_name = texture_entry.path
    _append_model_preview_material_input(
        mesh,
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name=str(getattr(binding, "parameter_name", "") or "").strip(),
            source_texture_path=texture_entry.path,
            source_dds_path=texture_entry.path,
            texture_name=PurePosixPath(texture_entry.path.replace("\\", "/")).name,
            preview_texture_path=preview_path_text,
            semantic_type="color",
            semantic_subtype="albedo",
            material_name=(
                str(getattr(binding, "material_name", "") or "").strip()
                or str(getattr(binding, "submesh_name", "") or "").strip()
                or str(getattr(mesh, "material_name", "") or "").strip()
            ),
            part_name=str(getattr(binding, "part_name", "") or "").strip(),
            shader_family=str(getattr(binding, "shader_family", "") or "").strip(),
            confidence="sidecar",
            visualized=True,
            sidecar_kind=str(getattr(binding, "sidecar_kind", "") or "").strip(),
            sidecar_path=str(getattr(binding, "sidecar_path", "") or "").strip(),
            linked_mesh_path=str(getattr(binding, "linked_mesh_path", "") or "").strip(),
            srgb_mode=str(getattr(binding, "srgb_mode", "") or "").strip(),
            parameter_declared_by=str(getattr(binding, "parameter_declared_by", "") or "").strip(),
            material_output_quality=str(getattr(binding, "material_output_quality", "") or "").strip(),
            layer_role=str(getattr(binding, "layer_role", "") or "").strip(),
            layer_channel=str(getattr(binding, "layer_channel", "") or "").strip(),
            blend_flags=tuple(str(value) for value in tuple(getattr(binding, "blend_flags", ()) or ()) if str(value)),
            owner_slot_index=int(getattr(binding, "owner_slot_index", -1)),
            owner_wrapper_item_id=str(getattr(binding, "owner_wrapper_item_id", "") or ""),
            binding_authority=str(getattr(binding, "binding_authority", "") or ""),
            binding_disposition=str(getattr(binding, "binding_disposition", "") or ""),
            source_kind=str(getattr(binding, "source_kind", "") or ""),
            material_parameters=tuple(getattr(binding, "material_parameters", ()) or ()),
        ),
    )
    current_material_name = str(getattr(mesh, "material_name", "") or "").strip()
    sidecar_material_name = str(getattr(binding, "submesh_name", "") or "").strip()
    if sidecar_material_name and not current_material_name:
        mesh.material_name = sidecar_material_name
    mesh.preview_base_texture_source = str(getattr(binding, "sidecar_kind", "") or "sidecar").strip() or "sidecar"
    mesh.preview_sidecar_material_primitive = (
        str(getattr(binding, "material_name", "") or "").strip()
        or str(getattr(binding, "part_name", "") or "").strip()
        or sidecar_material_name
    )
    mesh.preview_sidecar_shader_family = str(getattr(binding, "shader_family", "") or "").strip()
    try:
        mesh.preview_texture_brightness = max(0.1, min(3.0, float(getattr(binding, "brightness", 1.0) or 1.0)))
    except (TypeError, ValueError):
        mesh.preview_texture_brightness = 1.0
    mesh.preview_texture_tint = _model_preview_sidecar_tint(binding)
    mesh.preview_texture_uv_scale = _model_preview_sidecar_uv_scale(binding)
    material_color = _model_preview_sidecar_material_color(binding)
    low_authority_base = _is_low_authority_model_base_texture(texture_entry.path)
    mesh.preview_base_texture_quality = _model_preview_base_texture_quality(texture_entry.path)
    if material_color:
        mesh.preview_color = material_color
    if (
        mesh.preview_texture_tint
        or mesh.preview_texture_uv_scale
        or abs(float(mesh.preview_texture_brightness or 1.0) - 1.0) > 1e-6
    ):
        mesh.preview_texture_approximation_note = "Sidecar tint, brightness, and UV scale are preview approximations."
    if low_authority_base and material_color:
        mesh.preview_texture_approximation_note = (
            "Sidecar material color drives visible preview color; the resolved DDS is a low-detail overlay/default layer."
        )
