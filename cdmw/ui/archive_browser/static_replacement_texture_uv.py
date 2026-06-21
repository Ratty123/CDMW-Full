"""Pure UV transform payload helpers for static replacement textures."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence

from cdmw.modding.static_mesh_replacer import StaticTextureUvTransform


def global_flip_v_fast_preview_value(
    *,
    d3d11_preview_active: bool,
    texture_uv_transform_state: Mapping[str, Mapping[str, object]],
    texture_uv_global_transform_state: Mapping[str, object],
    state_has_edits: Callable[[Mapping[str, object]], bool],
) -> bool | None:
    if not d3d11_preview_active:
        return None
    if any(state_has_edits(state) for state in texture_uv_transform_state.values()):
        return None
    try:
        rotate_degrees = int(texture_uv_global_transform_state.get("rotate_degrees") or 0) % 360
        offset_u = float(texture_uv_global_transform_state.get("offset_u") or 0.0)
        offset_v = float(texture_uv_global_transform_state.get("offset_v") or 0.0)
        scale_u = float(texture_uv_global_transform_state.get("scale_u") or 1.0)
        scale_v = float(texture_uv_global_transform_state.get("scale_v") or 1.0)
    except (TypeError, ValueError, OverflowError):
        return None
    if rotate_degrees or bool(texture_uv_global_transform_state.get("flip_u")):
        return None
    if abs(offset_u) > 1.0e-6 or abs(offset_v) > 1.0e-6:
        return None
    if abs(scale_u - 1.0) > 1.0e-6 or abs(scale_v - 1.0) > 1.0e-6:
        return None
    return bool(texture_uv_global_transform_state.get("flip_v"))


def texture_uv_fast_preview_initial_state() -> dict[str, bool]:
    return {"global_flip_v": False}


def texture_transform_controls_loading_initial_state() -> dict[str, object]:
    return {"active": False, "key": ""}


def texture_transform_controls_set_loading(
    loading_state: MutableMapping[str, object],
    *,
    active: bool,
    key: str | None = None,
) -> dict[str, object]:
    loading_state["active"] = bool(active)
    if key is not None:
        loading_state["key"] = str(key or "")
    return dict(loading_state)


def texture_uv_fast_preview_record_global_flip_v(
    state: MutableMapping[str, object],
    flip_v: bool,
) -> bool:
    value = bool(flip_v)
    state["global_flip_v"] = value
    return value


def texture_uv_control_text() -> dict[str, str]:
    help_text = (
        "Adjust the selected source material's UVs without rotating the model. "
        "The correction applies to base, normal, mask, and height maps together in preview and export."
    )
    return {
        "transform_group": "Texture Orientation / UV Transform",
        "note": "UV transform for the selected source material.",
        "help": help_text,
        "material_label": "Material",
        "rotate_label": "Rotate",
        "flip_u_label": "Flip U",
        "flip_v_label": "Flip V",
        "offset_u_label": "Offset U",
        "offset_v_label": "Offset V",
        "scale_u_label": "Scale U",
        "scale_v_label": "Scale V",
        "reset_button": "Reset UV",
        "material_tooltip": "Choose the replacement source material whose UVs should be corrected.",
        "rotate_tooltip": "Rotate UVs around the 0.5/0.5 texture center.",
        "flip_u_tooltip": "Mirror the selected material horizontally in UV space.",
        "flip_v_tooltip": "Mirror the selected material vertically in UV space.",
        "offset_u_tooltip": "Move UVs horizontally after flip/rotation.",
        "offset_v_tooltip": "Move UVs vertically after flip/rotation.",
        "scale_u_tooltip": "Scale U around the 0.5/0.5 texture center.",
        "scale_v_tooltip": "Scale V around the 0.5/0.5 texture center.",
        "reset_tooltip": "Reset UV orientation for the selected source material.",
        "setup_rotate_tooltip": (
            "Default UV rotation for replacement source materials. "
            "Per-material settings in Materials & Textures override this."
        ),
        "setup_flip_u_tooltip": "Default horizontal UV mirror for replacement textures.",
        "setup_flip_v_tooltip": (
            "Default vertical UV mirror for replacement textures. "
            "Use this when imported textures appear upside down."
        ),
        "setup_output_size_tooltip": (
            "Choose the dimensions for generated DDS textures. Source image size preserves imported 4K textures; "
            "Original DDS size keeps the old template dimensions."
        ),
        "setup_reset_button": "Reset",
        "setup_reset_tooltip": "Reset global texture orientation defaults.",
    }


def texture_uv_global_transform_control_state(
    *,
    rotate_degrees: int,
    flip_u: bool,
    flip_v: bool,
) -> dict[str, object]:
    return {
        "source_material_name": "__global__",
        "rotate_degrees": int(rotate_degrees or 0),
        "flip_u": bool(flip_u),
        "flip_v": bool(flip_v),
        "offset_u": 0.0,
        "offset_v": 0.0,
        "scale_u": 1.0,
        "scale_v": 1.0,
    }


def texture_uv_global_transform_initial_state() -> dict[str, object]:
    return texture_uv_global_transform_control_state(
        rotate_degrees=0,
        flip_u=False,
        flip_v=False,
    )


def texture_uv_transform_control_state(
    material_name: str,
    *,
    rotate_degrees: object,
    flip_u: object,
    flip_v: object,
    offset_u: object,
    offset_v: object,
    scale_u: object,
    scale_v: object,
) -> dict[str, object]:
    return {
        "source_material_name": str(material_name or "").strip(),
        "rotate_degrees": int(rotate_degrees or 0),
        "flip_u": bool(flip_u),
        "flip_v": bool(flip_v),
        "offset_u": float(offset_u or 0.0),
        "offset_v": float(offset_v or 0.0),
        "scale_u": float(scale_u or 1.0),
        "scale_v": float(scale_v or 1.0),
    }


def texture_uv_transform_control_values(state: Mapping[str, object]) -> dict[str, object]:
    return {
        "rotate_degrees": int(state.get("rotate_degrees") or 0) % 360,
        "flip_u": bool(state.get("flip_u")),
        "flip_v": bool(state.get("flip_v")),
        "offset_u": float(state.get("offset_u") or 0.0),
        "offset_v": float(state.get("offset_v") or 0.0),
        "scale_u": float(state.get("scale_u") or 1.0),
        "scale_v": float(state.get("scale_v") or 1.0),
    }


def texture_uv_transform_control_load_state(
    texture_uv_transform_state: MutableMapping[str, object],
    material_name: str,
    default_state: Mapping[str, object],
    *,
    transform_key: Callable[[str], str],
) -> dict[str, object]:
    normalized_material_name = str(material_name or "").strip()
    key = transform_key(normalized_material_name)
    state = ensure_texture_uv_transform_state(texture_uv_transform_state, key, default_state)
    return {
        "key": key,
        "material_name": normalized_material_name,
        "values": texture_uv_transform_control_values(state),
    }


def texture_uv_transform_control_save_state(
    texture_uv_transform_state: MutableMapping[str, object],
    loading_state: Mapping[str, object],
    *,
    material_name: str,
    rotate_degrees: object,
    flip_u: object,
    flip_v: object,
    offset_u: object,
    offset_v: object,
    scale_u: object,
    scale_v: object,
    queue_preview: bool,
) -> dict[str, object]:
    if loading_state.get("active"):
        return {"saved": False, "queue_preview": False, "mark_dirty": False}
    key = str(loading_state.get("key") or "")
    if not key:
        return {"saved": False, "queue_preview": False, "mark_dirty": False}
    normalized_material_name = str(material_name or "").strip()
    if not normalized_material_name:
        return {"saved": False, "queue_preview": False, "mark_dirty": False}
    state = texture_uv_transform_control_state(
        normalized_material_name,
        rotate_degrees=rotate_degrees,
        flip_u=flip_u,
        flip_v=flip_v,
        offset_u=offset_u,
        offset_v=offset_v,
        scale_u=scale_u,
        scale_v=scale_v,
    )
    changed = record_texture_uv_transform_state(texture_uv_transform_state, key, state)
    return {
        "saved": changed,
        "queue_preview": bool(changed and queue_preview),
        "mark_dirty": bool(changed and not queue_preview),
    }


def texture_uv_transform_materials_state(
    texture_sets: Mapping[str, object],
    texture_uv_transform_state: MutableMapping[str, object],
    previous_key: str,
    *,
    transform_key: Callable[[str], str],
    default_state_for_material: Callable[[str], Mapping[str, object]],
) -> dict[str, object]:
    choices: list[tuple[str, str]] = []
    for material_name in texture_uv_material_names(texture_sets):
        key = transform_key(material_name)
        ensure_texture_uv_transform_state(
            texture_uv_transform_state,
            key,
            default_state_for_material(material_name),
        )
        choices.append((material_name, key))
    choice_keys = tuple(key for _material_name, key in choices)
    selected_key = str(previous_key or "")
    if selected_key not in choice_keys:
        selected_key = choice_keys[0] if choice_keys else ""
    return {
        "choices": tuple(choices),
        "selected_key": selected_key,
        "has_materials": bool(choices),
    }


def texture_uv_transform_reset_state(
    texture_uv_transform_state: MutableMapping[str, object],
    material_name: str,
    default_state: Mapping[str, object],
    *,
    transform_key: Callable[[str], str],
) -> dict[str, object]:
    normalized_material_name = str(material_name or "").strip()
    if not normalized_material_name:
        return {"reset": False, "key": "", "material_name": ""}
    key = transform_key(normalized_material_name)
    reset_texture_uv_transform_state(texture_uv_transform_state, key, default_state)
    return {"reset": True, "key": key, "material_name": normalized_material_name}


def texture_uv_material_names(texture_sets: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        str(getattr(texture_set, "material_name", "") or "").strip()
        for texture_set in texture_sets.values()
        if str(getattr(texture_set, "material_name", "") or "").strip()
    )


def record_texture_uv_global_transform_state(
    texture_uv_global_transform_state: MutableMapping[str, object],
    state: Mapping[str, object],
) -> None:
    texture_uv_global_transform_state.clear()
    texture_uv_global_transform_state.update(dict(state))


def _texture_uv_transform_from_state(material_name: str, state: Mapping[str, object]) -> StaticTextureUvTransform:
    return StaticTextureUvTransform(
        source_material_name=material_name,
        rotate_degrees=int(state.get("rotate_degrees") or 0),
        flip_u=bool(state.get("flip_u")),
        flip_v=bool(state.get("flip_v")),
        offset_uv=(
            float(state.get("offset_u") or 0.0),
            float(state.get("offset_v") or 0.0),
        ),
        scale_uv=(
            float(state.get("scale_u") or 1.0),
            float(state.get("scale_v") or 1.0),
        ),
    )


def ensure_texture_uv_transform_state(
    texture_uv_transform_state: MutableMapping[str, object],
    key: str,
    default_state: Mapping[str, object],
) -> Mapping[str, object]:
    normalized_key = str(key or "")
    state = texture_uv_transform_state.get(normalized_key)
    if not isinstance(state, Mapping):
        state = dict(default_state)
        texture_uv_transform_state[normalized_key] = state
    return state


def record_texture_uv_transform_state(
    texture_uv_transform_state: MutableMapping[str, object],
    key: str,
    state: Mapping[str, object],
) -> bool:
    normalized_key = str(key or "")
    payload = dict(state)
    if texture_uv_transform_state.get(normalized_key) == payload:
        return False
    texture_uv_transform_state[normalized_key] = payload
    return True


def reset_texture_uv_transform_state(
    texture_uv_transform_state: MutableMapping[str, object],
    key: str,
    default_state: Mapping[str, object],
) -> None:
    texture_uv_transform_state[str(key or "")] = dict(default_state)


def current_texture_uv_transforms(
    texture_sets: Mapping[str, object],
    texture_uv_transform_state: Mapping[str, Mapping[str, object]],
    texture_uv_global_transform_state: Mapping[str, object],
    *,
    state_has_edits: Callable[[Mapping[str, object]], bool],
    transform_key: Callable[[str], str],
) -> list[StaticTextureUvTransform]:
    transforms: list[StaticTextureUvTransform] = []
    global_has_edits = state_has_edits(texture_uv_global_transform_state)
    per_material_override_keys = {
        transform_key(str(state.get("source_material_name") or ""))
        for state in texture_uv_transform_state.values()
        if state_has_edits(state)
    }
    if global_has_edits:
        material_names = [
            str(getattr(texture_set, "material_name", "") or "").strip()
            for texture_set in texture_sets.values()
            if str(getattr(texture_set, "material_name", "") or "").strip()
        ]
        for material_name in material_names:
            if transform_key(material_name) in per_material_override_keys:
                continue
            transforms.append(_texture_uv_transform_from_state(material_name, texture_uv_global_transform_state))
    for state in texture_uv_transform_state.values():
        if not state_has_edits(state):
            continue
        material_name = str(state.get("source_material_name") or "").strip()
        if not material_name:
            continue
        transforms.append(_texture_uv_transform_from_state(material_name, state))
    return transforms


def texture_uv_transform_payload(transforms: Sequence[StaticTextureUvTransform]) -> list[tuple[object, ...]]:
    payload: list[tuple[object, ...]] = []
    for transform in transforms:
        payload.append(
            (
                transform.source_material_name,
                int(transform.rotate_degrees or 0),
                bool(transform.flip_u),
                bool(transform.flip_v),
                round(float(transform.offset_uv[0]), 6),
                round(float(transform.offset_uv[1]), 6),
                round(float(transform.scale_uv[0]), 6),
                round(float(transform.scale_uv[1]), 6),
            )
        )
    return sorted(payload)


__all__ = [
    "current_texture_uv_transforms",
    "ensure_texture_uv_transform_state",
    "global_flip_v_fast_preview_value",
    "record_texture_uv_global_transform_state",
    "record_texture_uv_transform_state",
    "reset_texture_uv_transform_state",
    "texture_uv_control_text",
    "texture_uv_fast_preview_initial_state",
    "texture_uv_fast_preview_record_global_flip_v",
    "texture_uv_global_transform_control_state",
    "texture_uv_global_transform_initial_state",
    "texture_uv_material_names",
    "texture_uv_transform_control_load_state",
    "texture_uv_transform_control_save_state",
    "texture_uv_transform_control_state",
    "texture_uv_transform_control_values",
    "texture_uv_transform_materials_state",
    "texture_uv_transform_payload",
    "texture_uv_transform_reset_state",
    "texture_transform_controls_loading_initial_state",
    "texture_transform_controls_set_loading",
]
