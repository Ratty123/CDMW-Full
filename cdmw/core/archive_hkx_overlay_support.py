from __future__ import annotations

import re
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.models import HkxPhysicsOverlayBone


def _hkx_overlay_vector(
    value: object,
    *,
    normalization_center: Sequence[object],
    normalization_scale: float,
) -> Tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return ()
    try:
        center = tuple(float(component) for component in tuple(normalization_center)[:3])
        if len(center) < 3:
            center = (0.0, 0.0, 0.0)
        scale = float(normalization_scale or 1.0)
        return (
            (float(value[0]) - center[0]) * scale,
            (float(value[1]) - center[1]) * scale,
            (float(value[2]) - center[2]) * scale,
        )
    except (TypeError, ValueError, OverflowError):
        return ()


def _hkx_overlay_descriptor_vector(
    numeric_hints: object,
    hint_name: str,
    *,
    normalization_center: Sequence[object],
    normalization_scale: float,
) -> Tuple[float, float, float]:
    from cdmw.core import archive_hkx as hkx

    value = hkx._hkx_descriptor_numeric_hint_lookup(numeric_hints, hint_name)
    if value is None:
        return ()
    components: List[float] = []
    for token in re.split(r"[\s,;]+", value.strip()):
        if not token:
            continue
        try:
            components.append(float(token))
        except (TypeError, ValueError, OverflowError):
            return ()
        if len(components) >= 3:
            break
    if len(components) < 3:
        return ()
    return _hkx_overlay_vector(
        components,
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
    )


def _hkx_overlay_tuning_hint_text(numeric_hints: object, names: set[str], *, limit: int = 6) -> Tuple[str, ...]:
    if not isinstance(numeric_hints, list):
        return ()
    rows: List[str] = []
    for hint in numeric_hints:
        if not isinstance(hint, Mapping):
            continue
        name = str(hint.get("name") or "").strip()
        if name not in names:
            continue
        value = str(hint.get("value") or " ".join(str(item) for item in hint.get("values", []) if item is not None)).strip()
        rows.append(f"{name}={value}" if value else name)
        if len(rows) >= limit:
            break
    return tuple(rows)


def _hkx_overlay_anchor_match_key(*values: object) -> str:
    for value in values:
        text = str(value or "").strip().casefold()
        if text:
            return text
    return ""


def _hkx_overlay_name_aliases(name: object) -> Tuple[str, ...]:
    text = str(name or "").strip()
    if not text:
        return ()
    lowered = text.casefold()
    compact = re.sub(r"[^a-z0-9]+", "", lowered)
    underscore = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    aliases = [lowered]
    for alias in (compact, underscore):
        if alias and alias not in aliases:
            aliases.append(alias)
    return tuple(aliases)


def _hkx_overlay_skeleton_bone_match(
    skeleton_bone_positions: Optional[Mapping[str, object]],
    *names: object,
    normalization_center: Sequence[object],
    normalization_scale: float,
) -> Tuple[Tuple[float, float, float], str, int, str]:
    if not isinstance(skeleton_bone_positions, Mapping) or not skeleton_bone_positions:
        return (), "", -1, ""
    lookup: Dict[str, Tuple[str, object]] = {}
    for bone_name, raw_value in skeleton_bone_positions.items():
        for alias in _hkx_overlay_name_aliases(bone_name):
            lookup.setdefault(alias, (str(bone_name), raw_value))

    def _matched_position(matched_name: str, raw_value: object) -> Tuple[Tuple[float, float, float], str, int, str]:
        metadata: Mapping[str, object] = {}
        raw_position: object = raw_value
        if isinstance(raw_value, Mapping):
            metadata = raw_value
            raw_position = raw_value.get("position")
        position = _hkx_overlay_vector(
            raw_position,
            normalization_center=normalization_center,
            normalization_scale=normalization_scale,
        )
        if position:
            bone_index = metadata.get("index")
            return (
                position,
                str(metadata.get("name") or matched_name),
                int(bone_index) if isinstance(bone_index, int) else -1,
                str(metadata.get("source_path") or ""),
            )
        return (), "", -1, ""

    for name in names:
        for alias in _hkx_overlay_name_aliases(name):
            match = lookup.get(alias)
            if match is None:
                continue
            matched_name, raw_value = match
            result = _matched_position(matched_name, raw_value)
            if result[0]:
                return result
    bone_aliases = sorted(
        ((alias, matched_name, raw_value) for alias, (matched_name, raw_value) in lookup.items() if len(alias) >= 5),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for name in names:
        for requested_alias in _hkx_overlay_name_aliases(name):
            if len(requested_alias) < 5:
                continue
            for bone_alias, matched_name, raw_value in bone_aliases:
                if requested_alias == bone_alias or requested_alias.endswith(bone_alias) or bone_alias in requested_alias:
                    result = _matched_position(matched_name, raw_value)
                    if result[0]:
                        return result
    return (), "", -1, ""


def _hkx_overlay_body_shape_targets(
    document: Mapping[str, object],
    skeleton_bone_positions: Optional[Mapping[str, object]],
    *,
    normalization_center: Sequence[object],
    normalization_scale: float,
) -> Dict[int, Dict[str, object]]:
    targets: Dict[int, Dict[str, object]] = {}
    physics_body_context = document.get("physics_body_context")
    if not isinstance(physics_body_context, Mapping):
        return targets
    body_contexts = physics_body_context.get("body_contexts")
    if not isinstance(body_contexts, list):
        return targets
    for body_context in body_contexts:
        if not isinstance(body_context, Mapping):
            continue
        socket_name = str(body_context.get("socket_name") or "")
        fixed_socket_name = str(body_context.get("fixed_socket_name") or "")
        body_name = str(body_context.get("body_name") or "")
        skeleton_position, skeleton_bone_name, skeleton_bone_index, skeleton_source_path = _hkx_overlay_skeleton_bone_match(
            skeleton_bone_positions,
            socket_name,
            fixed_socket_name,
            body_name,
            normalization_center=normalization_center,
            normalization_scale=normalization_scale,
        )
        if not skeleton_position:
            continue
        shape_matches = body_context.get("shape_matches")
        if not isinstance(shape_matches, list):
            continue
        for match in shape_matches:
            if not isinstance(match, Mapping) or not isinstance(match.get("decoded_shape_index"), int):
                continue
            shape_index = int(match["decoded_shape_index"])
            targets.setdefault(
                shape_index,
                {
                    "position": skeleton_position,
                    "source": "skeleton_socket",
                    "target": skeleton_bone_name or socket_name or fixed_socket_name or body_name,
                    "bone_index": skeleton_bone_index,
                    "source_path": skeleton_source_path,
                    "confidence": "skeleton_context",
                },
            )
    return targets


def _hkx_overlay_average_position(points: Sequence[Sequence[object]]) -> Tuple[float, float, float]:
    parsed: List[Tuple[float, float, float]] = []
    for point in points:
        if len(point) < 3:
            continue
        try:
            parsed.append((float(point[0]), float(point[1]), float(point[2])))
        except (TypeError, ValueError, OverflowError):
            continue
    if not parsed:
        return ()
    count = float(len(parsed))
    return (
        sum(point[0] for point in parsed) / count,
        sum(point[1] for point in parsed) / count,
        sum(point[2] for point in parsed) / count,
    )


def _hkx_overlay_shape_visual_center(
    *,
    center: Sequence[object] = (),
    bounds_min: Sequence[object] = (),
    bounds_max: Sequence[object] = (),
    capsule_start: Sequence[object] = (),
    capsule_end: Sequence[object] = (),
    vertices: Sequence[Sequence[object]] = (),
) -> Tuple[float, float, float]:
    for point in (center,):
        parsed = _hkx_overlay_average_position((point,))
        if parsed:
            return parsed
    if len(bounds_min) >= 3 and len(bounds_max) >= 3:
        parsed = _hkx_overlay_average_position((bounds_min, bounds_max))
        if parsed:
            return parsed
    if len(capsule_start) >= 3 and len(capsule_end) >= 3:
        parsed = _hkx_overlay_average_position((capsule_start, capsule_end))
        if parsed:
            return parsed
    return _hkx_overlay_average_position(vertices)


def _hkx_overlay_translate_point(
    point: Sequence[object],
    delta: Sequence[object],
) -> Tuple[float, float, float]:
    if len(point) < 3 or len(delta) < 3:
        return ()
    try:
        return (
            float(point[0]) + float(delta[0]),
            float(point[1]) + float(delta[1]),
            float(point[2]) + float(delta[2]),
        )
    except (TypeError, ValueError, OverflowError):
        return ()


def _hkx_overlay_bones_from_skeleton_positions(
    skeleton_bone_positions: Optional[Mapping[str, object]],
    *,
    normalization_center: Sequence[object],
    normalization_scale: float,
    limit: int = 384,
) -> Tuple[HkxPhysicsOverlayBone, ...]:
    if not isinstance(skeleton_bone_positions, Mapping) or not skeleton_bone_positions:
        return ()
    raw_rows: List[Tuple[str, Mapping[str, object]]] = [
        (str(name), value)
        for name, value in skeleton_bone_positions.items()
        if str(name or "").strip() and isinstance(value, Mapping)
    ]
    raw_rows.sort(key=lambda item: int(item[1].get("index")) if isinstance(item[1].get("index"), int) else 1_000_000)
    rows_by_index: Dict[int, Mapping[str, object]] = {}
    rows_by_name: Dict[str, Mapping[str, object]] = {}
    for name, row in raw_rows:
        bone_index = row.get("index")
        if isinstance(bone_index, int):
            rows_by_index[bone_index] = row
        rows_by_name[str(row.get("name") or name)] = row
    bones: List[HkxPhysicsOverlayBone] = []
    for fallback_name, row in raw_rows[:limit]:
        name = str(row.get("name") or fallback_name)
        position = _hkx_overlay_vector(
            row.get("position"),
            normalization_center=normalization_center,
            normalization_scale=normalization_scale,
        )
        if not position:
            continue
        parent_index = row.get("parent_index")
        parent_name = str(row.get("parent_name") or "")
        parent_row = rows_by_index.get(parent_index) if isinstance(parent_index, int) else None
        if parent_row is None and parent_name:
            parent_row = rows_by_name.get(parent_name)
        parent_position = (
            _hkx_overlay_vector(
                parent_row.get("position"),
                normalization_center=normalization_center,
                normalization_scale=normalization_scale,
            )
            if isinstance(parent_row, Mapping)
            else ()
        )
        index_value = row.get("index")
        bones.append(
            HkxPhysicsOverlayBone(
                name=name,
                source_path=str(row.get("source_path") or ""),
                index=int(index_value) if isinstance(index_value, int) else -1,
                parent_index=int(parent_index) if isinstance(parent_index, int) else -1,
                parent_name=parent_name or (str(parent_row.get("name") or "") if isinstance(parent_row, Mapping) else ""),
                position=position,
                parent_position=parent_position,
            )
        )
    return tuple(bones)
