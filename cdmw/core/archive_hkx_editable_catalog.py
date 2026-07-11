from __future__ import annotations

from collections import Counter
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


def _append_shape_fields(fields: List[Dict[str, object]], shapes: Sequence[Mapping[str, object]]) -> None:
    from cdmw.core import archive_hkx as hkx

    for shape in shapes:
        if not isinstance(shape, Mapping):
            continue
        records = shape.get("records")
        editable_fields = shape.get("editable_fields")
        if not isinstance(editable_fields, list):
            continue
        subject = hkx._hkx_editable_shape_subject(shape)
        for field_name_value in editable_fields:
            field_name = str(field_name_value or "").strip()
            if not field_name:
                continue
            record_index = records.get(field_name) if isinstance(records, Mapping) else None
            if record_index is None and isinstance(records, Mapping):
                record_alias = {
                    "capsule_radius": "capsule_radius_shape",
                    "sphere_radius": "sphere_radius_shape",
                    "shape_payload": "shape_payload",
                }.get(field_name)
                if record_alias is not None:
                    record_index = records.get(record_alias)
            hkx._hkx_append_editable_catalog_field(
                fields,
                {
                    "category": "collision_shape",
                    "editor_tab": "Collision Editor",
                    "importable": True,
                    "edit_rule": "fixed_size_value_only",
                    "shape_index": shape.get("index"),
                    "shape_type": str(shape.get("shape_type") or "hknpShape"),
                    "subject": subject,
                    "record_index": record_index,
                    "name": field_name,
                    "value_summary": hkx._hkx_editable_shape_field_value_summary(shape, field_name),
                    "confidence": "strong inference"
                    if field_name in {"vertices", "planes", "capsule_radius", "capsule_endpoints", "sphere_radius", "sphere_center"}
                    else "experimental",
                    "description": hkx._hkx_editable_shape_field_description(shape, field_name),
                },
            )


def _append_constraint_fields(
    fields: List[Dict[str, object]],
    summary: Optional[Mapping[str, object]],
) -> set[Tuple[int, int, int]]:
    from cdmw.core import archive_hkx as hkx

    keys: set[Tuple[int, int, int]] = set()
    constraints = summary.get("constraints") if isinstance(summary, Mapping) else None
    if not isinstance(constraints, list):
        return keys
    for constraint in constraints:
        if not isinstance(constraint, Mapping):
            continue
        constraint_name = str(constraint.get("name") or "")
        constraint_type = str(constraint.get("type_name") or "")
        for slot_group_name, slot_source, record_key in (
            ("constraint_slots", "constraint", "constraint_record_index"),
            ("motor_slots", "motor", "motor_record_index"),
        ):
            slots = constraint.get(slot_group_name)
            if not isinstance(slots, list):
                continue
            for slot in slots:
                if not isinstance(slot, Mapping):
                    continue
                try:
                    record_index = int(constraint.get(record_key))
                    item_index = int(slot.get("item_index"))
                    offset = int(slot.get("offset"))
                except (TypeError, ValueError):
                    continue
                keys.add((record_index, item_index, offset))
                category = "constraint_motor"
                if slot_source == "motor" and constraint.get("constraint_record_index") is None:
                    category = hkx._hkx_physics_tuning_category("hknpPositionConstraintMotor")
                hkx._hkx_append_editable_catalog_field(
                    fields,
                    {
                        "category": category,
                        "editor_tab": "Structured Editor",
                        "importable": True,
                        "edit_rule": "fixed_float_slot_value_only",
                        "record_index": record_index,
                        "item_index": item_index,
                        "offset": offset,
                        "hex_offset": f"0x{offset:X}",
                        "subject": constraint_name or constraint_type,
                        "source_type_name": str(slot.get("source_type_name") or constraint_type),
                        "name": str(slot.get("name") or ""),
                        "value_summary": hkx._hkx_xml_scalar(slot.get("value")),
                        "confidence": str(slot.get("confidence") or "experimental"),
                        "description": (
                            f"{slot_source.title()} slot for {constraint_name or constraint_type}. "
                            f"{slot.get('description') or 'Edit through Structured Editor only.'}"
                        ),
                    },
                )
    return keys


def _append_tuning_fields(
    fields: List[Dict[str, object]],
    physics_tuning: Optional[Mapping[str, object]],
    constraint_slot_keys: set[Tuple[int, int, int]],
) -> None:
    from cdmw.core import archive_hkx as hkx

    groups = physics_tuning.get("groups") if isinstance(physics_tuning, Mapping) else None
    if not isinstance(groups, list):
        return
    for group in groups:
        slots = group.get("slots") if isinstance(group, Mapping) else None
        if not isinstance(slots, list):
            continue
        for slot in slots:
            if not isinstance(slot, Mapping):
                continue
            try:
                record_index = int(group.get("record_index"))
                item_index = int(slot.get("item_index"))
                offset = int(slot.get("offset"))
            except (TypeError, ValueError):
                continue
            if (record_index, item_index, offset) in constraint_slot_keys:
                continue
            hkx._hkx_append_editable_catalog_field(
                fields,
                {
                    "category": str(group.get("category") or "physics_tuning"),
                    "editor_tab": "Structured Editor",
                    "importable": True,
                    "edit_rule": "fixed_float_slot_value_only",
                    "record_index": record_index,
                    "item_index": item_index,
                    "offset": offset,
                    "hex_offset": f"0x{offset:X}",
                    "subject": str(group.get("label") or group.get("type_name") or ""),
                    "source_type_name": str(slot.get("source_type_name") or group.get("type_name") or ""),
                    "name": str(slot.get("name") or ""),
                    "value_summary": hkx._hkx_xml_scalar(slot.get("value")),
                    "confidence": str(slot.get("confidence") or "experimental"),
                    "description": str(slot.get("description") or group.get("description") or ""),
                },
            )


def _hkx_editable_field_catalog_document(
    shapes: Sequence[Mapping[str, object]],
    physics_tuning: Optional[Mapping[str, object]],
    physics_constraint_summary: Optional[Mapping[str, object]],
) -> Optional[Dict[str, object]]:
    fields: List[Dict[str, object]] = []
    _append_shape_fields(fields, shapes)
    constraint_slot_keys = _append_constraint_fields(fields, physics_constraint_summary)
    _append_tuning_fields(fields, physics_tuning, constraint_slot_keys)
    if not fields:
        return None
    category_counts = Counter(str(field.get("category") or "unknown") for field in fields)
    effect_counts = Counter(str(field.get("effect") or "unknown") for field in fields)
    return {
        "status": "generated_from_current_decoder",
        "imported": False,
        "field_count": len(fields),
        "category_counts": dict(sorted(category_counts.items())),
        "effect_counts": dict(sorted(effect_counts.items())),
        "description": (
            "Human-facing index of values the converter currently knows how to explain and route to an editor. "
            "This catalog is ignored on import; actual writes are still validated against fixed-size HKX records."
        ),
        "workflow": {
            "edit_surface": "Structured Editor for known values; XML / Raw for documented fallback editing.",
            "safe_editing": "Change one value at a time, keep counts and offsets unchanged, then write a loose mod package.",
            "game_file_policy": "Edited HKX output is written as a mod-ready loose replacement. Installed game archives are not modified.",
        },
        "fields": fields,
    }
