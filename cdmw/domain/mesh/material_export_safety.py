"""Pure material-representation safety checks for full-import export."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _mapping(value: object) -> Mapping[object, object]:
    if isinstance(value, Mapping):
        return value
    try:
        return dict(value or ())  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return {}


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    try:
        return float(value) > 0.0
    except (TypeError, ValueError):
        return str(value or "").strip().casefold() not in {"", "0", "0.0", "false", "none", "null"}


def _source_requirements(row: Mapping[str, object]) -> tuple[str, ...]:
    required: list[str] = []
    alpha_mode = str(row.get("alpha_mode", "") or "").strip().upper()
    if alpha_mode == "MASK":
        required.append("MASK")
    elif alpha_mode == "BLEND":
        required.append("BLEND")

    scalar_hints = _mapping(row.get("scalar_hints"))
    if any("transmission" in _key(name) and _truthy(value) for name, value in scalar_hints.items()):
        required.append("transmission")
    for texture in tuple(row.get("material_inputs", ()) or ()) + tuple(row.get("texture_slots", ()) or ()):
        if not isinstance(texture, Mapping):
            continue
        evidence = " ".join(
            str(texture.get(name, "") or "")
            for name in ("slot_kind", "parameter_name", "semantic_type", "semantic_subtype")
        )
        if "transmission" in _key(evidence):
            required.append("transmission")
    return tuple(dict.fromkeys(required))


def _wrapper_support(row: Mapping[str, object]) -> frozenset[str]:
    if not bool(row.get("corpus_proven", False)):
        return frozenset()
    support: set[str] = set()
    shader_key = _key(row.get("shader_name"))
    opacity_texture = False
    for parameter in tuple(row.get("parameters", ()) or ()):
        if not isinstance(parameter, Mapping):
            continue
        name_key = _key(parameter.get("name") or parameter.get("parameter_name"))
        value = parameter.get("value")
        parameter_type = _key(parameter.get("type") or parameter.get("parameter_type"))
        if "alphatest" in name_key and _truthy(value):
            support.add("MASK")
        if "alphacutoff" in name_key or "alphacutout" in name_key or "cutout" in name_key:
            support.add("MASK")
        if "alphablend" in name_key and _truthy(value):
            support.add("BLEND")
        if "opacity" in name_key or name_key == "alphatexture":
            opacity_texture = opacity_texture or ("texture" in parameter_type and _truthy(value))
        if any(token in name_key for token in ("transmission", "refraction", "attenuation", "thickness")) and _truthy(value):
            support.add("transmission")
    if opacity_texture and any(token in shader_key for token in ("hair", "fur", "eye")):
        support.add("MASK")
    if opacity_texture and any(token in shader_key for token in ("glass", "transparent", "translucent", "water")):
        support.add("BLEND")
    if "transmission" in support and any(token in shader_key for token in ("glass", "transparent", "translucent", "refraction")):
        support.add("BLEND")
    return frozenset(support)


def _source_target_keys(
    source: Mapping[str, object],
    routes: Sequence[Mapping[str, object]],
    wrapper_keys: frozenset[str],
) -> tuple[str, ...]:
    source_key = _key(source.get("material_name"))
    try:
        source_index = int(source.get("mesh_index", -1) or -1)
    except (TypeError, ValueError, OverflowError):
        source_index = -1
    targets: list[str] = []
    for route in routes:
        names = {_key(name) for name in tuple(route.get("source_material_names", ()) or ()) if _key(name)}
        indices = {int(index) for index in tuple(route.get("source_indices", ()) or ()) if str(index).lstrip("-").isdigit()}
        if source_key not in names and source_index not in indices:
            continue
        candidates = tuple(_key(name) for name in tuple(route.get("target_wrapper_names", ()) or ()) if _key(name))
        targets.append(next((name for name in candidates if name in wrapper_keys), candidates[0] if candidates else ""))
    return tuple(dict.fromkeys(target for target in targets if target))


def material_export_safety_blockers(
    source_materials: Sequence[Mapping[str, object]],
    target_wrappers: Sequence[Mapping[str, object]],
    routes: Sequence[Mapping[str, object]] = (),
) -> tuple[str, ...]:
    """Block source alpha/transmission that the emitted proven wrapper cannot represent."""

    support_by_key: dict[str, set[str]] = {}
    display_by_key: dict[str, str] = {}
    for wrapper in tuple(target_wrappers or ()):
        key = _key(wrapper.get("wrapper_name"))
        if not key:
            continue
        support_by_key.setdefault(key, set()).update(_wrapper_support(wrapper))
        display_by_key.setdefault(key, str(wrapper.get("wrapper_name", "") or key))
    wrapper_keys = frozenset(support_by_key)
    blockers: list[str] = []
    for source in tuple(source_materials or ()):
        required = _source_requirements(source)
        if not required:
            continue
        targets = _source_target_keys(source, routes, wrapper_keys)
        if not targets and routes:
            continue
        if not targets and len(wrapper_keys) == 1:
            targets = tuple(wrapper_keys)
        if not targets:
            targets = ("",)
        for target_key in targets:
            missing = [feature for feature in required if feature not in support_by_key.get(target_key, set())]
            if not missing:
                continue
            source_name = str(source.get("material_name", "") or "<unnamed source material>")
            target_name = display_by_key.get(target_key, "<unresolved target wrapper>")
            blockers.append(
                "Corpus-proven target wrapper support missing: "
                f"source material {source_name} requires {', '.join(missing)}, but generated wrapper {target_name} does not prove it."
            )
    return tuple(dict.fromkeys(blockers))


__all__ = ["material_export_safety_blockers"]
