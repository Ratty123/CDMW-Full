"""Resident .NET material-parameter bridge for static replacement UI."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from types import SimpleNamespace

from cdmw.domain.textures.material_parameters import (
    evaluate_material_parameters,
    material_parameter_renderer_overrides,
    profile_source_emissive_enabled,
    source_emissive_strength,
)
from cdmw.services.material_authority_resource_service import (
    material_authority_resource_backend_available,
)


_PARAMETER_KEYS = (
    "texture_brightness",
    "contrast",
    "post_contrast_brightness",
    "saturation",
    "gamma",
    "tint_color",
    "base_color_lift",
    "value_max",
    "auto_balance",
    "shadow_lift",
    "roughness",
    "roughness_inverted",
    "roughness_scale",
    "roughness_min",
    "roughness_max",
    "roughness_blend_target",
    "roughness_blend_strength",
    "metalness",
    "metalness_inverted",
    "metalness_scale",
    "metalness_min",
    "metalness_max",
    "metalness_blend_target",
    "metalness_blend_strength",
    "specular",
    "height_scale",
    "emissive_intensity",
    "emissive_color",
    "material_role",
    "visible",
)


def resident_material_parameter_group(
    values: Mapping[str, object],
    *,
    source_submesh_indices: Sequence[int] = (),
    editor_role: str = "replacement_preview",
) -> dict[str, object]:
    """Flatten evaluated values into the resident renderer's group shape."""
    flattened: dict[str, object] = {}
    for nested_key in ("renderer_parameters", "native_material_hints"):
        nested = values.get(nested_key)
        if isinstance(nested, Mapping):
            flattened.update(nested)
    flattened.update(values)
    return {
        "source_submesh_indices": sorted({int(index) for index in source_submesh_indices if int(index) >= 0}),
        "editor_role": str(editor_role or "replacement_preview"),
        **{key: flattened[key] for key in _PARAMETER_KEYS if key in flattened},
    }


def send_resident_material_parameters(dialog: object, groups: Sequence[Mapping[str, object]]) -> bool:
    """Send only through the active production .NET session."""
    if not resident_material_parameters_available(dialog):
        return False
    sender = getattr(dialog, "_mesh_editor_embedded_apply_material_parameters", None)
    if not callable(sender):
        return False
    normalized = tuple(dict(group) for group in groups if isinstance(group, Mapping))
    return bool(normalized and sender(normalized))


def resident_material_parameters_available(dialog: object) -> bool:
    if not (
        getattr(dialog, "_mesh_editor_embedded_dotnet_active", False)
        and callable(getattr(dialog, "_mesh_editor_embedded_apply_material_parameters", None))
    ):
        return False
    capability = getattr(dialog, "_mesh_editor_embedded_resident_material_parameters_supported", True)
    try:
        return bool(capability()) if callable(capability) else bool(capability)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def resident_material_resources_available(dialog: object) -> bool:
    if not (
        getattr(dialog, "_mesh_editor_embedded_dotnet_active", False)
        and callable(getattr(dialog, "_mesh_editor_embedded_apply_material_resources", None))
    ):
        return False
    if not material_authority_resource_backend_available():
        return False
    capability = getattr(dialog, "_mesh_editor_embedded_resident_material_resources_supported", True)
    try:
        return bool(capability()) if callable(capability) else bool(capability)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def resident_material_preview_blocks_package_fallback(dialog: object, editor_active: object) -> bool:
    if resident_material_parameters_available(dialog) or resident_material_resources_available(dialog):
        return True
    try:
        return bool(editor_active()) if callable(editor_active) else False
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def resident_material_parameter_groups_for_model(
    values: Mapping[str, object],
    preview_model: object,
    *,
    profile: object | None,
    part_adjustments: Mapping[int, object] | None = None,
) -> tuple[dict[str, object], ...]:
    buckets: dict[str, tuple[dict[str, object], list[int]]] = {}
    adjustments = part_adjustments or {}
    emissive_enabled = not hasattr(profile, "emissive_mode") or profile_source_emissive_enabled(profile)
    for index, mesh in enumerate(tuple(getattr(preview_model, "meshes", ()) or ())):
        adjustment = adjustments.get(index)
        role = str(getattr(adjustment, "material_role", "") or "").strip().lower()
        imported = source_emissive_strength(mesh)
        group = {
            **{key: None for key in _PARAMETER_KEYS if key != "visible"},
            **resident_material_parameter_group(values, source_submesh_indices=(index,)),
        }
        if (role in {"glow", "emissive"} or imported is not None) and emissive_enabled:
            evaluated = evaluate_material_parameters(
                profile,
                source_slot=mesh,
                part_adjustment=adjustment,
                emissive_role=True,
            )
            overrides = material_parameter_renderer_overrides(evaluated)
            for key in ("emissive_intensity", "emissive_color"):
                group[key] = overrides.get(key)
            group["material_role"] = role or "emissive"
        else:
            for key in ("emissive_intensity", "emissive_color", "material_role"):
                group[key] = None
        signature = repr(sorted((key, value) for key, value in group.items() if key != "source_submesh_indices"))
        if signature not in buckets:
            buckets[signature] = (group, [])
        buckets[signature][1].append(index)
    result: list[dict[str, object]] = []
    for group, indices in buckets.values():
        group["source_submesh_indices"] = indices
        result.append(group)
    return tuple(result)


def apply_material_parameter_preview(
    dialog: object,
    values: Mapping[str, object],
    *,
    legacy_active: bool,
    legacy_host: object,
    dirty_state: MutableMapping[str, object] | None = None,
    source_submesh_indices: Sequence[int] = (),
    preview_model: object | None = None,
    profile: object | None = None,
    part_adjustments: Mapping[int, object] | None = None,
) -> bool:
    group = resident_material_parameter_group(values, source_submesh_indices=source_submesh_indices)
    groups = resident_material_parameter_groups_for_model(
        values, preview_model, profile=profile, part_adjustments=part_adjustments
    ) if preview_model is not None else ()
    groups = groups or (group,)
    if send_resident_material_parameters(dialog, groups):
        if dirty_state is not None:
            dirty_state["dirty"] = True
        return True
    sender = getattr(legacy_host, "set_material_overrides", None)
    if not legacy_active or not callable(sender):
        return False
    sent = sender(
        source_submesh_indices=tuple(source_submesh_indices),
        editor_role="replacement_preview",
        **{
            key: value
            for key, value in group.items()
            if key not in {"source_submesh_indices", "editor_role", "material_role"} and value is not None
        },
    )
    if sent and dirty_state is not None:
        dirty_state["dirty"] = True
    return bool(sent)


def source_role_material_parameter_values(
    source_index: int,
    material_role: object,
    emissive_color_rgb: object,
    *,
    emissive_strength: object | None = None,
    source: object | None = None,
    profile: object | None = None,
) -> dict[str, object]:
    role = str(material_role or "").strip().lower()
    color = tuple(emissive_color_rgb or ())
    imported_strength = source_emissive_strength(source)
    emissive_enabled = role in {"glow", "emissive"} or (not role and imported_strength is not None)
    evaluation = evaluate_material_parameters(
        profile,
        source_slot=source,
        part_adjustment=SimpleNamespace(
            material_role=role,
            emissive_color_rgb=color,
            emissive_strength=emissive_strength,
        ),
        emissive_role=emissive_enabled,
    )
    evaluated = material_parameter_renderer_overrides(evaluation)
    values = {key: evaluated[key] for key in ("emissive_intensity", "emissive_color") if key in evaluated}
    values["material_role"] = role or ("emissive" if emissive_enabled else None)
    values["emissive_color"] = tuple(values["emissive_color"]) if "emissive_color" in values else None
    if not emissive_enabled or (hasattr(profile, "emissive_mode") and not profile_source_emissive_enabled(profile)):
        values.update(emissive_intensity=None, emissive_color=None)
    else:
        values.setdefault("emissive_color", None)
    return resident_material_parameter_group(
        values,
        source_submesh_indices=(source_index,),
    )


def send_source_role_material_parameters(
    dialog: object,
    source_index: int,
    material_role: object,
    emissive_color_rgb: object,
    *,
    emissive_strength: object | None = None,
    source: object | None = None,
    profile: object | None = None,
) -> bool:
    return send_resident_material_parameters(
        dialog,
        (source_role_material_parameter_values(
            source_index,
            material_role,
            emissive_color_rgb,
            emissive_strength=emissive_strength,
            source=source,
            profile=profile,
        ),),
    )


def source_part_material_parameter_values(material_state: object) -> dict[str, object]:
    is_adjustment = hasattr(material_state, "material_brightness")
    tint_attr = "material_tint_rgb" if is_adjustment else "tint_rgb"
    tint = tuple(getattr(material_state, tint_attr, ()) or ())
    role = str(getattr(material_state, "material_role", "") or "").strip().lower()
    evaluation = evaluate_material_parameters(
        part_adjustment=SimpleNamespace(
            material_brightness=getattr(material_state, "material_brightness" if is_adjustment else "brightness", 0.0),
            material_contrast=getattr(material_state, "material_contrast" if is_adjustment else "contrast", 0.0),
            material_saturation=getattr(material_state, "material_saturation" if is_adjustment else "saturation", 0.0),
            material_gamma=getattr(material_state, "material_gamma" if is_adjustment else "gamma", 1.0),
            material_tint_rgb=tint,
            material_role=role,
            emissive_color_rgb=getattr(material_state, "emissive_color_rgb", ()),
            emissive_strength=getattr(material_state, "emissive_strength", None),
        )
    )
    values = material_parameter_renderer_overrides(evaluation)
    if is_adjustment and role:
        values["material_role"] = role
        if role not in {"glow", "emissive"}:
            values.update(emissive_intensity=None, emissive_color=None)
        else:
            values.setdefault("emissive_color", None)
    return values


def source_part_material_parameter_groups_for_mesh(
    mesh: object,
    adjustments: Mapping[int, object],
    default_adjustment: object,
    *,
    source_indices: Sequence[int] | None = None,
) -> tuple[dict[str, object], ...]:
    if not callable(default_adjustment):
        return ()
    groups = []
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    indices = range(len(submeshes)) if source_indices is None else sorted({int(index) for index in source_indices})
    for source_index in indices:
        if not 0 <= source_index < len(submeshes):
            continue
        source = submeshes[source_index]
        adjustment = adjustments.get(source_index, default_adjustment(source_index))
        values = source_part_material_parameter_values(adjustment)
        values.update(source_role_material_parameter_values(
            source_index,
            getattr(adjustment, "material_role", ""),
            getattr(adjustment, "emissive_color_rgb", ()),
            emissive_strength=getattr(adjustment, "emissive_strength", None),
            source=source,
        ))
        values["visible"] = bool(getattr(adjustment, "enabled", True))
        groups.append(resident_material_parameter_group(values, source_submesh_indices=(source_index,)))
    return tuple(groups)


__all__ = [
    "apply_material_parameter_preview",
    "resident_material_parameter_group",
    "resident_material_parameter_groups_for_model",
    "resident_material_parameters_available",
    "resident_material_resources_available",
    "resident_material_preview_blocks_package_fallback",
    "send_resident_material_parameters",
    "send_source_role_material_parameters",
    "source_part_material_parameter_groups_for_mesh",
    "source_part_material_parameter_values",
    "source_role_material_parameter_values",
]
