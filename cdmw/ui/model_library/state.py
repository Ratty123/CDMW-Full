"""Pure helpers for Model Library UI rows and status."""

from __future__ import annotations

from pathlib import Path


TEXTURE_STATUS_HAS_PREFIXES = ("Found (", "In ZIP (", "Resolved (")
TEXTURE_STATUS_MISSING = "None found"


def external_audit_material_class_rows(audit: object) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for item in tuple(getattr(audit, "material_classes", ()) or ()):
        material_class = str(getattr(item, "material_class", "") or "").strip()
        if not material_class:
            continue
        rows.append(
            {
                "class": material_class,
                "confidence": float(getattr(item, "confidence", 0.0) or 0.0),
                "evidence": tuple(getattr(item, "evidence", ()) or ()),
            }
        )
    return tuple(rows)


def external_audit_value(item: object, key: str, default: object = "") -> object:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def external_audit_resolution(value: object) -> tuple[int, int]:
    resolution = tuple(value or ()) if not isinstance(value, str) else ()
    if len(resolution) < 2:
        return ()
    try:
        width = int(resolution[0])
        height = int(resolution[1])
    except (TypeError, ValueError):
        return ()
    if width <= 0 or height <= 0:
        return ()
    return (width, height)


def external_audit_texture_slot_rows(raw_slots: object) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for slot in tuple(raw_slots or ()):
        slot_kind = str(external_audit_value(slot, "slot_kind", "") or "").strip()
        texture_name = str(external_audit_value(slot, "texture_name", "") or "").strip()
        texture_path = str(external_audit_value(slot, "texture_path", "") or "").strip()
        if not slot_kind and not texture_name and not texture_path:
            continue
        rows.append(
            {
                "slot_kind": slot_kind,
                "parameter_name": str(external_audit_value(slot, "parameter_name", "") or "").strip(),
                "texture_name": texture_name,
                "texture_path": texture_path,
                "image_format": str(external_audit_value(slot, "image_format", "") or "").strip().lower(),
                "resolution": external_audit_resolution(external_audit_value(slot, "resolution", ())),
                "semantic_type": str(external_audit_value(slot, "semantic_type", "") or "").strip(),
                "semantic_subtype": str(external_audit_value(slot, "semantic_subtype", "") or "").strip(),
                "packed_channels": tuple(
                    str(value or "").strip()
                    for value in tuple(external_audit_value(slot, "packed_channels", ()) or ())
                    if str(value or "").strip()
                ),
                "color_space": str(external_audit_value(slot, "color_space", "") or "").strip().lower(),
                "source": str(external_audit_value(slot, "source", "") or "").strip(),
                "confidence": str(external_audit_value(slot, "confidence", "") or "").strip(),
                "evidence": tuple(external_audit_value(slot, "evidence", ()) or ()),
            }
        )
    return tuple(rows)


def external_audit_texture_slot_text(slot: dict[str, object]) -> str:
    slot_kind = str(slot.get("slot_kind", "") or "texture").strip()
    texture_name = str(slot.get("texture_name", "") or slot.get("texture_path", "") or "").strip()
    image_format = str(slot.get("image_format", "") or "").strip().lower()
    color_space = str(slot.get("color_space", "") or "").strip().lower()
    semantic = str(slot.get("semantic_subtype", "") or "").strip()
    resolution = external_audit_resolution(slot.get("resolution", ()))
    pieces = [slot_kind]
    if texture_name:
        pieces.append(Path(texture_name).name)
    if image_format:
        pieces.append(image_format)
    if resolution:
        pieces.append(f"{resolution[0]}x{resolution[1]}")
    if color_space:
        pieces.append(color_space)
    if semantic and semantic != slot_kind:
        pieces.append(semantic)
    packed = tuple(str(value or "").strip() for value in tuple(slot.get("packed_channels", ()) or ()) if str(value or "").strip())
    if packed:
        pieces.append("channels=" + "/".join(packed))
    return " ".join(pieces)


def external_audit_material_inventory_rows(audit: object) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for material in tuple(getattr(audit, "material_inventory", ()) or ()):
        raw_slots = tuple(getattr(material, "texture_slots", ()) or ())
        texture_slot_rows = external_audit_texture_slot_rows(raw_slots)
        texture_slots = tuple(
            str(getattr(slot, "slot_kind", "") or "").strip()
            for slot in raw_slots
            if str(getattr(slot, "slot_kind", "") or "").strip()
        )
        texture_stats: list[str] = []
        for slot in raw_slots:
            stats = {str(key): float(value) for key, value in tuple(getattr(slot, "channel_stats", ()) or ())}
            if not stats:
                continue
            slot_kind = str(getattr(slot, "slot_kind", "") or "").strip() or "texture"
            texture_name = str(getattr(slot, "texture_name", "") or "").strip()
            label = f"{slot_kind}:{texture_name}" if texture_name else slot_kind
            texture_stats.append(
                f"{label} rgb={stats.get('r_mean', 0.0):.2f}/{stats.get('g_mean', 0.0):.2f}/{stats.get('b_mean', 0.0):.2f} "
                f"a={stats.get('a_mean', 0.0):.2f}"
            )
        material_classes = tuple(
            {
                "class": str(getattr(item, "material_class", "") or ""),
                "confidence": float(getattr(item, "confidence", 0.0) or 0.0),
            }
            for item in tuple(getattr(material, "material_classes", ()) or ())
            if str(getattr(item, "material_class", "") or "").strip()
        )
        rows.append(
            {
                "material_name": str(getattr(material, "material_name", "") or ""),
                "submesh_names": tuple(getattr(material, "submesh_names", ()) or ()),
                "pbr_workflow": str(getattr(material, "pbr_workflow", "") or ""),
                "alpha_mode": str(getattr(material, "alpha_mode", "") or ""),
                "double_sided": bool(getattr(material, "double_sided", False)),
                "vertex_color_factor": tuple(getattr(material, "vertex_color_factor", ()) or ()),
                "vertex_alpha": tuple(getattr(material, "vertex_alpha", ()) or ()),
                "texture_slots": texture_slots,
                "texture_slot_rows": texture_slot_rows,
                "texture_stats": tuple(texture_stats),
                "material_classes": material_classes,
                "warnings": tuple(getattr(material, "warnings", ()) or ()),
            }
        )
    return tuple(rows)


def model_library_texture_status_kind(status: str) -> str:
    text = str(status or "").strip()
    if text == TEXTURE_STATUS_MISSING:
        return "missing"
    if any(text.startswith(prefix) for prefix in TEXTURE_STATUS_HAS_PREFIXES):
        return "present"
    return "unknown"


__all__ = [
    "TEXTURE_STATUS_HAS_PREFIXES",
    "TEXTURE_STATUS_MISSING",
    "external_audit_material_class_rows",
    "external_audit_material_inventory_rows",
    "external_audit_resolution",
    "external_audit_texture_slot_rows",
    "external_audit_texture_slot_text",
    "external_audit_value",
    "model_library_texture_status_kind",
]
