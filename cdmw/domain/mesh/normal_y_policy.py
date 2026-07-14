"""Pure normal-map orientation policy shared by preview renderers."""

from __future__ import annotations

from collections.abc import Mapping


def _source_value(source: object, name: str) -> object:
    if isinstance(source, Mapping):
        return source.get(name, "")
    return getattr(source, name, "")


def resolve_preview_normal_y_policy(source: object | None) -> str:
    """Translate source normal-space evidence into one explicit shader policy."""

    if source is None:
        return "preserve"
    explicit_policy = str(_source_value(source, "preview_normal_y_policy") or "").strip().casefold()
    if explicit_policy in {"invert_green_for_directx", "shader_invert_legacy_compat"}:
        return "invert_green_for_directx"
    if explicit_policy in {"preserve", "directx", "legacy_no_flip"}:
        return "preserve"
    explicit_space = str(
        _source_value(source, "preview_normal_texture_space")
        or _source_value(source, "normal_space")
        or ""
    ).strip().casefold()
    if explicit_space in {"green_up", "ogl"}:
        return "invert_green_for_directx"
    if explicit_space in {"directx", "green_down", "dx"}:
        return "preserve"
    for item in tuple(_source_value(source, "preview_material_texture_inputs") or ()):
        semantic = str(
            _source_value(item, "semantic_type")
            or _source_value(item, "slot_kind")
            or ""
        ).strip().casefold()
        if semantic != "normal":
            continue
        normal_space = str(_source_value(item, "normal_space") or "").strip().casefold()
        confidence = str(_source_value(item, "confidence") or "").strip().casefold()
        path = str(
            _source_value(item, "preview_texture_path")
            or _source_value(item, "source_path")
            or _source_value(item, "source_texture_path")
            or ""
        ).strip().casefold()
        if normal_space in {"green_up", "ogl"} or confidence == "gltf" or "green_up" in path:
            return "invert_green_for_directx"
        if normal_space in {"directx", "green_down", "dx"} or "directx" in path or "_dx." in path:
            return "preserve"
    return "preserve"


__all__ = ["resolve_preview_normal_y_policy"]
