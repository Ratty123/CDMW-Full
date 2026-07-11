"""Small pure helpers for the static replacement dialog."""

from __future__ import annotations

import hashlib
import re
from html import escape
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Sequence

from cdmw.services.preview_workflow_service import (
    TEXTURE_PLAN_STATUS_IGNORED_ADVANCED,
    TEXTURE_PLAN_STATUS_LIKELY_GREY,
    TEXTURE_PLAN_STATUS_READY,
    TEXTURE_PLAN_STATUS_REVIEW,
    TEXTURE_PLAN_STATUS_SUPPORT_ONLY,
    build_dds_override_table_row,
)

from cdmw.services.mesh_workflow_service import _semantic_tokens
from cdmw.models import ModelPreviewData, PreviewMaterialParameterInput, PreviewMaterialTextureInput
from cdmw.ui.archive_browser.static_replacement_texture_rows import (
    TextureRowTableDisplay,
    material_routing_conflict_messages,
    source_indices_for_target_contract,
    set_texture_row_assignment,
    source_slot_for_texture_row,
    source_texture_reference_keys,
    source_material_group_label,
    source_material_names_for_mapping,
    routing_source_material_labels,
    source_texture_slot_count,
    sync_texture_row_assignment_state,
    target_texture_status_details,
    target_texture_status_text,
    texture_row_can_apply_suggested_for_target,
    texture_row_can_auto_apply,
    texture_row_contract_status_color,
    texture_row_current_source_indices,
    texture_row_effective_source,
    texture_row_is_assigned,
    texture_row_is_shared,
    texture_row_override_key,
    texture_row_source_summary,
    texture_row_source_color,
    texture_row_table_role_color,
    texture_row_table_display,
    texture_row_visible,
    texture_set_for_source_index,
    texture_source_choices_for_row,
    texture_slot_contract_key,
    texture_summary_label_html,
    texture_summary_metrics,
)
from cdmw.ui.archive_browser.static_replacement_texture_matching import (
    best_source_for_slot,
    binding_matches_target,
    part_specific_tokens,
    source_texture_evidence_by_local_path,
    texture_file_lookup_maps,
)
from cdmw.ui.archive_browser.static_replacement_source_part_defaults import is_default_source_part_adjustment


_IMPORTANT_STATIC_TEXTURE_TOKENS = {
    "acc",
    "accessory",
    "blade",
    "body",
    "cape",
    "cloth",
    "edge",
    "guard",
    "handle",
    "hand",
    "arm",
    "forearm",
    "head",
    "face",
    "hair",
    "foot",
    "feet",
    "leg",
    "boot",
    "nude",
    "helmet",
    "hilt",
    "plate",
    "spike",
    "trim",
}

_TEXTURE_ROLE_SORT_ORDER = {"base": 0, "normal": 1, "height": 2, "material": 3}


def alignment_sample_sequence(values: object, *, limit: int = 4) -> tuple:
    seq = tuple(values or ())
    if len(seq) <= limit * 2:
        return seq
    return seq[:limit] + seq[-limit:]


def alignment_file_signature(path_value: object) -> tuple[str, int, int]:
    path_text = str(path_value or "").strip()
    if not path_text:
        return ("", 0, 0)
    try:
        path = Path(path_text).expanduser()
        stat = path.stat()
        return (str(path), int(stat.st_size), int(stat.st_mtime_ns))
    except (OSError, TypeError, ValueError):
        return (path_text, 0, 0)


def alignment_sequence_digest(values: object) -> tuple[int, str]:
    digest = hashlib.sha1()
    count = 0
    for value in tuple(values or ()):
        digest.update(repr(value).encode("utf-8", errors="replace"))
        digest.update(b"\0")
        count += 1
    return count, digest.hexdigest()


def important_static_texture_tokens(value: str) -> set[str]:
    return _semantic_tokens(value) & _IMPORTANT_STATIC_TEXTURE_TOKENS


def is_marker_source(submesh: object) -> bool:
    label = f"{getattr(submesh, 'name', '')} {getattr(submesh, 'material', '')}".lower()
    return any(
        marker in label
        for marker in (
            "cdmw_anchor",
            "cdmw_grip_anchor",
            "cdmw_tip_anchor",
            "cft_anchor",
            "cft_grip_anchor",
            "cft_tip_anchor",
        )
    )


def mapping_source_cell_text(summary: str, ok: bool) -> str:
    if not ok:
        return "Invalid"
    normalized = str(summary or "").strip()
    if normalized.startswith("Selected: "):
        return normalized.replace("Selected: ", "", 1)
    if normalized.startswith("Empty target"):
        return "-"
    return normalized or "-"


def texture_context_path_html(path_text: object) -> str:
    text = str(path_text or "").strip()
    if not text:
        return "<span style='color:#8b949e;'>none</span>"
    normalized = text.replace("\\", "/")
    compact = Path(normalized).name or normalized
    return f"<span title='{escape(text)}' style='color:#a5d6ff; word-break:break-all;'>{escape(compact)}</span>"


def texture_slot_role_color(row_state: dict[str, object]) -> str:
    slot_kind = str(row_state.get("slot_kind", "") or row_state.get("original_slot_kind", "") or "").strip().lower()
    return {
        "base": "#3fb950",
        "normal": "#58a6ff",
        "height": "#fb923c",
        "material": "#a371f7",
    }.get(slot_kind, "#8b949e")


def texture_context_chip_cell(label: object, background: str, *, foreground: str = "#0d1117") -> str:
    text = str(label or "").strip() or "Unknown"
    return (
        "<td style='padding:1px 5px; border-radius:2px; font-size:0.9em; font-weight:700; "
        f"background:{background}; color:{foreground}; white-space:nowrap;'>{escape(text)}</td>"
    )


def texture_context_kv_row(label: str, value_html: str) -> str:
    return (
        "<tr>"
        f"<td width='84' style='padding:1px 7px 1px 0; color:#8b949e; vertical-align:top; white-space:nowrap;'>{escape(label)}</td>"
        f"<td style='padding:1px 0; color:#e6edf3; vertical-align:top; word-break:break-word;'>{value_html}</td>"
        "</tr>"
    )


def compact_context_value(value: object, *, limit: int = 46) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def source_material_output_path(source_path: Path, entry_path: object) -> str:
    source_stem = re.sub(r"[^a-z0-9_]+", "_", source_path.stem.lower()).strip("_") or "texture"
    target_stem = re.sub(
        r"[^a-z0-9_]+",
        "_",
        PurePosixPath(str(entry_path or "").replace("\\", "/")).stem.lower(),
    ).strip("_") or "static_replacement"
    return f"character/texture/{target_stem}_{source_stem}.dds"


def texture_source_key(source_path: object) -> str:
    return str(source_path or "").replace("\\", "/").strip().lower()


def texture_uv_transform_key(material_name: str) -> str:
    return str(material_name or "").strip().lower()


def default_texture_uv_transform_state(material_name: str) -> dict[str, object]:
    return {
        "source_material_name": str(material_name or "").strip(),
        "rotate_degrees": 0,
        "flip_u": False,
        "flip_v": False,
        "offset_u": 0.0,
        "offset_v": 0.0,
        "scale_u": 1.0,
        "scale_v": 1.0,
    }


def texture_uv_state_has_edits(state: Mapping[str, object]) -> bool:
    try:
        return (
            int(state.get("rotate_degrees") or 0) % 360 != 0
            or bool(state.get("flip_u"))
            or bool(state.get("flip_v"))
            or abs(float(state.get("offset_u") or 0.0)) > 1e-8
            or abs(float(state.get("offset_v") or 0.0)) > 1e-8
            or abs(float(state.get("scale_u") or 1.0) - 1.0) > 1e-8
            or abs(float(state.get("scale_v") or 1.0) - 1.0) > 1e-8
        )
    except Exception:
        return False


def texture_plan_status_color(status_label: str) -> str:
    if status_label == TEXTURE_PLAN_STATUS_READY:
        return "#3fb950"
    if status_label == TEXTURE_PLAN_STATUS_REVIEW:
        return "#d29922"
    if status_label == TEXTURE_PLAN_STATUS_SUPPORT_ONLY:
        return "#fb923c"
    if status_label == TEXTURE_PLAN_STATUS_LIKELY_GREY:
        return "#f85149"
    if status_label == TEXTURE_PLAN_STATUS_IGNORED_ADVANCED:
        return "#8b949e"
    return "#8b949e"


def material_route_status_color(status_label: str) -> str:
    normalized = str(status_label or "").strip().lower()
    if normalized == "ready":
        return "#3fb950"
    if normalized == "review":
        return "#d29922"
    if normalized == "blocked":
        return "#f85149"
    if normalized == "ignored":
        return "#8b949e"
    return "#8b949e"


def material_contract_block(
    *,
    route_count: int,
    blocker_count: int,
    base_count: int,
    normal_count: int,
    pbr_count: int,
) -> str:
    status_text = "blocked" if blocker_count else "ready"
    status_color = "#f85149" if blocker_count else "#3fb950"
    return (
        "<div style='font-size:0.8em; line-height:1.08; padding:2px 5px; border-left:3px solid "
        f"{status_color}; background:#161b22;'>"
        f"<span style='color:{status_color}; font-weight:700;'>DDS {escape(status_text)}</span>"
        f"<span style='color:#c9d1d9;'> | routes {route_count:,}"
        f" | base {base_count:,} | normal {normal_count:,}"
        f" | review {pbr_count:,}</span>"
        "</div>"
    )


def material_plan_summary_block(
    *,
    detected_sets: int,
    detected_slots: int,
    conflicts: Sequence[str],
    profile_material_count: int = 0,
    profile_shader_count: int = 0,
    profile_emissive_count: int = 0,
    empty: bool = False,
) -> str:
    if empty:
        return (
            "<div style='font-size:0.8em; line-height:1.08; padding:2px 5px; border-left:3px solid #d29922; background:#2b2416;'>"
            "<span style='color:#f2cc60; font-weight:700;'>Textures 0</span>"
            "<span style='color:#c9d1d9;'> | original/none</span>"
            "</div>"
        )
    profile_count = profile_material_count + profile_shader_count + profile_emissive_count
    color = "#f2cc60" if conflicts else "#79c0ff"
    return (
        "<div style='font-size:0.8em; line-height:1.08; padding:2px 5px; border-left:3px solid "
        f"{color}; background:#10233a;'>"
        f"<span style='color:{color}; font-weight:700;'>Textures</span>"
        f"<span style='color:#c9d1d9;'> {detected_sets:,} sets | {detected_slots:,} maps"
        f" | warnings {len(conflicts):,} | profiles {profile_count:,}</span>"
        "</div>"
    )


def final_preview_material_status_color(status_label: str) -> str:
    normalized = str(status_label or "").strip().lower()
    if normalized == "ready":
        return "#3fb950"
    if normalized in {"missing_base", "missing_dds", "decode_failed"}:
        return "#f85149"
    if normalized in {"support_maps_only", "advanced_shader_only"}:
        return "#d29922"
    return "#8b949e"


def final_preview_binding_preview_status(row: object) -> str:
    status = str(getattr(row, "status", "") or "").strip().lower()
    preview_path = str(getattr(row, "preview_texture_path", "") or "").strip()
    if status == "ready" and preview_path:
        return "visible thumbnail"
    if status == "ready":
        return "resolved"
    if status == "decode_failed":
        return "decode failed"
    if status == "missing_dds":
        return "not previewable"
    if status == "advanced_shader_only":
        return "advanced only"
    return status or "unknown"


def slot_kind_for_final_preview_row(row: object) -> str:
    role_text = str(getattr(row, "role", "") or "").strip().lower()
    parameter_text = str(getattr(row, "parameter_name", "") or "").strip().lower()
    texture_text = str(getattr(row, "texture_path", "") or "").strip().lower()
    combined = f"{role_text} {parameter_text} {texture_text}"
    if "normal" in combined:
        return "normal"
    if any(token in combined for token in ("height", "displacement", "parallax", "bump")):
        return "height"
    if any(token in combined for token in ("base", "color", "diffuse", "albedo", "overlay")):
        return "base"
    return "material"


def texture_role_label_for_slot(slot_kind: str) -> str:
    return {
        "base": "Base / Color",
        "normal": "Normal",
        "height": "Height / Displacement",
        "material": "Material / Mask",
    }.get(str(slot_kind or "").strip().lower(), str(slot_kind or "Texture").title())


def texture_status_text(row_state: Mapping[str, object], *, assigned: bool) -> str:
    if assigned:
        return f"Assigned ({str(row_state.get('confidence', 'manual')).title()})"
    return str(row_state.get("state_label", "") or "Keep original")


def source_texture_path_for_plan_row(
    plan_row: object,
    material_name: str,
    texture_sets: Mapping[str, object],
) -> str:
    normalized_material = str(material_name or "").strip().lower()
    normalized_slot = str(getattr(plan_row, "slot_kind", "") or "").strip().lower()
    if not normalized_material or not normalized_slot:
        return ""
    texture_set = texture_sets.get(normalized_material) or texture_sets.get(str(material_name or "").strip())
    if texture_set is None:
        for candidate in texture_sets.values():
            candidate_name = str(getattr(candidate, "material_name", "") or "").strip().lower()
            if candidate_name == normalized_material:
                texture_set = candidate
                break
    slot = None
    if texture_set is not None:
        slots = getattr(texture_set, "slots", {}) or {}
        slot = slots.get(normalized_slot)
        if slot is None and normalized_slot == "material_mask":
            slot = slots.get("material")
    source_path = getattr(slot, "source_path", None)
    return str(source_path) if isinstance(source_path, Path) else ""


def texture_target_sort_key(
    target_name: str,
    texture_rows_by_target: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    assigned_predicate: Callable[[Mapping[str, object]], bool],
) -> tuple[int, str]:
    rows = texture_rows_by_target.get(target_name, [])
    unassigned = sum(1 for row_state in rows if not assigned_predicate(row_state))
    return (-unassigned, target_name.lower())


def texture_override_row_sort_key(
    row_state: Mapping[str, object],
    texture_rows_by_target: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    assigned_predicate: Callable[[Mapping[str, object]], bool],
) -> tuple[int, int, str, str, str]:
    target_name = str(row_state.get("target_name", "") or "")
    return (
        texture_target_sort_key(target_name, texture_rows_by_target, assigned_predicate=assigned_predicate)[0],
        _TEXTURE_ROLE_SORT_ORDER.get(str(row_state.get("slot_kind", "") or ""), 9),
        target_name.lower(),
        str(row_state.get("parameter_name", "") or "").lower(),
        str(row_state.get("target_path", "") or "").lower(),
    )


def alignment_contract_preview_path(source_path_text: str) -> str:
    source_text = str(source_path_text or "").strip()
    if not source_text:
        return ""
    source = Path(source_text).expanduser()
    return str(source) if str(source) else ""


def looks_like_standalone_pbr_source(texture_file: Path) -> bool:
    stem_tokens = _semantic_tokens(texture_file.stem)
    compact = re.sub(r"[^a-z0-9]+", "", texture_file.stem.lower())
    if {"orm", "rma", "mra", "arm", "material", "mask"} & stem_tokens:
        return False
    if compact.endswith(
        (
            "ma",
            "mg",
            "sp",
            "orm",
            "rma",
            "mra",
            "arm",
        )
    ):
        return False
    if compact.endswith(("metallicroughness", "metalrough", "metallicrough", "roughnessmetallic", "roughmetal")):
        return True
    return bool(stem_tokens & {"metallic", "metalness", "roughness", "smoothness", "gloss", "ao", "occlusion"})


def is_gltf_metallic_roughness_path(texture_file: Path) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", str(texture_file.stem or "").lower())
    return any(
        token in normalized
        for token in ("metallicroughness", "metalrough", "metallicrough", "roughnessmetallic")
    )


def texture_assignment_summary_html(
    title: str,
    planned_rows: Sequence[tuple[Mapping[str, object], str, str]],
    *,
    reason: str,
) -> str:
    row_html: list[str] = []
    for row_state, source_path, decision in planned_rows[:18]:
        table_row = build_dds_override_table_row(
            {
                **row_state,
                "source_path": source_path,
                "checked": decision == "Apply",
            }
        )
        status_label = table_row.status.label
        status_color = texture_plan_status_color(status_label)
        status_foreground = "#ffffff" if status_label in {TEXTURE_PLAN_STATUS_LIKELY_GREY, TEXTURE_PLAN_STATUS_IGNORED_ADVANCED} else "#0d1117"
        role_color = {
            "base": "#3fb950",
            "normal": "#58a6ff",
            "height": "#fb923c",
            "material": "#a371f7",
        }.get(table_row.slot_kind, "#8b949e")
        row_html.append(
            "<tr style='background:#161b22;'>"
            f"<td style='padding:6px 7px; color:#f0f6fc; white-space:nowrap;'>{escape(table_row.part_label or table_row.part_material)}</td>"
            f"<td style='padding:6px 7px;'>{html_chip_span(table_row.role, role_color)}</td>"
            f"<td style='padding:6px 7px; color:#a5d6ff; word-break:break-all;'>{escape(table_row.original_slot)}</td>"
            f"<td style='padding:6px 7px; color:#e6edf3; word-break:break-all;'>{escape(Path(source_path).name if source_path else 'Keep original')}</td>"
            f"<td style='padding:6px 7px;'>{html_chip_span(status_label, status_color, status_foreground)}</td>"
            f"<td style='padding:6px 7px;'>{html_chip_span(decision, '#238636', '#ffffff')}</td>"
            "</tr>"
        )
    if len(planned_rows) > 18:
        row_html.append(
            f"<tr><td colspan='6' style='padding:7px; color:#8b949e;'>... {len(planned_rows) - 18:,} more row(s)</td></tr>"
        )
    return (
        "<html><body style='background:#1f1f1f; color:#e6edf3; font-size:1.2em; margin:0;'>"
        "<div style='padding:10px 12px; line-height:1.35;'>"
        f"<div style='font-size:1.7em; font-weight:700; color:#f0f6fc;'>{escape(title)}</div>"
        f"<div style='margin-top:7px; color:#c9d1d9;'>{escape(reason)}</div>"
        "<table width='100%' cellspacing='0' cellpadding='0' style='margin-top:10px; background:#2b2416; border:1px solid #3d2f12;'>"
        "<tr><td width='8' style='background:#d29922;'></td>"
        "<td style='padding:8px 10px; color:#f2cc60;'>"
        "Suggested rows become manual overrides; unchanged rows keep original DDS slots."
        "</td></tr></table>"
        "<table width='100%' cellspacing='0' cellpadding='0' style='margin-top:12px; border:1px solid #30363d;'>"
        "<tr style='background:#24292f; color:#8b949e;'>"
        "<th align='left' style='padding:6px 7px;'>Part</th>"
        "<th align='left' style='padding:6px 7px;'>Role</th>"
        "<th align='left' style='padding:6px 7px;'>DDS</th>"
        "<th align='left' style='padding:6px 7px;'>Source</th>"
        "<th align='left' style='padding:6px 7px;'>Status</th>"
        "<th align='left' style='padding:6px 7px;'>Action</th></tr>"
        + "".join(row_html)
        + "</table></div></body></html>"
    )


def native_manifest_input_from_descriptor(
    descriptor: Mapping[str, object],
    *,
    fallback_slot: str = "",
    part_name: str = "",
) -> PreviewMaterialTextureInput | None:
    source_path = str(descriptor.get("source_path", "") or "").strip()
    archive_path = str(descriptor.get("archive_path", "") or "").strip()
    if not source_path and not archive_path:
        return None
    slot_kind = str(descriptor.get("slot", "") or fallback_slot or "").strip().lower()
    packed_raw = descriptor.get("packed_channels", ())
    if isinstance(packed_raw, str):
        packed_channels = tuple(part for part in re.split(r"[,;\s]+", packed_raw) if part)
    elif isinstance(packed_raw, Sequence):
        packed_channels = tuple(str(part) for part in packed_raw if str(part).strip())
    else:
        packed_channels = ()
    texture_name = (
        str(descriptor.get("texture_name", "") or "").strip()
        or PurePosixPath(archive_path.replace("\\", "/")).name
        or Path(source_path).name
    )
    return PreviewMaterialTextureInput(
        slot_kind=slot_kind,
        parameter_name=str(descriptor.get("parameter_name", "") or ""),
        source_texture_path=archive_path or source_path,
        source_dds_path=source_path,
        texture_name=texture_name,
        preview_texture_path=source_path or archive_path,
        semantic_type=str(descriptor.get("semantic_type", "") or ""),
        semantic_subtype=str(descriptor.get("semantic_subtype", "") or ""),
        packed_channels=packed_channels,
        material_name=str(descriptor.get("material_name", "") or ""),
        part_name=part_name,
        shader_family=str(descriptor.get("shader_family", "") or ""),
        confidence=str(descriptor.get("relation_confidence", "") or descriptor.get("evidence_grade", "") or "native-core"),
        visualized=bool(descriptor.get("available", True)),
        sidecar_kind=str(descriptor.get("sidecar_kind", "") or ""),
        sidecar_path=str(descriptor.get("sidecar_path", "") or ""),
        linked_mesh_path=str(descriptor.get("linked_mesh_path", "") or ""),
        srgb_mode=str(descriptor.get("srgb_mode", "") or ""),
        parameter_declared_by=str(descriptor.get("parameter_declared_by", "") or ""),
        material_output_quality=str(descriptor.get("material_output_quality", "") or "native-core"),
        layer_role=str(descriptor.get("layer_role", "") or ""),
        layer_channel=str(descriptor.get("layer_channel", "") or descriptor.get("mask_channel", "") or ""),
        blend_flags=tuple(
            part for part in re.split(r"[,;\s]+", str(descriptor.get("blend_flags", "") or "")) if part
        ),
    )


def texture_set_factor_parameters(texture_set_obj: object) -> tuple[PreviewMaterialParameterInput, ...]:
    parameters: list[PreviewMaterialParameterInput] = []
    for attr_name, parameter_name in (
        ("roughness_factor", "_roughnessFactor"),
        ("metallic_factor", "_metallicFactor"),
        ("specular_factor", "_specularFactor"),
        ("glossiness_factor", "_glossinessFactor"),
        ("occlusion_strength", "_occlusionStrength"),
    ):
        value = getattr(texture_set_obj, attr_name, None)
        if value is None:
            continue
        try:
            numeric_value = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError, OverflowError):
            continue
        parameters.append(
            PreviewMaterialParameterInput(
                parameter_kind="float",
                parameter_name=parameter_name,
                value=f"{numeric_value:.6f}",
                numeric_value=numeric_value,
            )
        )
    return tuple(parameters)


def html_chip_span(label: object, background: str, foreground: str = "#0d1117") -> str:
    return (
        "<span style='padding:2px 7px; font-weight:700; "
        f"background:{background}; color:{foreground}; white-space:nowrap;'>"
        f"{escape(str(label or '').strip() or 'Unknown')}</span>"
    )


def mapping_status_summary_badge(label: str, value: str, color: str) -> str:
    return (
        "<span style='display:inline-block; margin:1px 3px 1px 0; padding:2px 6px; "
        f"border:1px solid {color}; border-radius:3px; background:#161b22;'>"
        f"<span style='color:{color}; font-weight:700;'>{escape(label)}</span>"
        f"<span style='color:#f0f6fc;'> {escape(value or '-')}</span>"
        "</span>"
    )


def coerce_float_triple(values: Sequence[float], fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    try:
        raw = tuple(float(value) for value in tuple(values)[:3])
    except (TypeError, ValueError):
        return fallback
    return raw if len(raw) == 3 else fallback


def mesh_center_for_ui(mesh: object) -> tuple[float, float, float]:
    vertices: list[tuple[float, float, float]] = []
    for submesh in getattr(mesh, "submeshes", ()) or ():
        vertices.extend(list(getattr(submesh, "vertices", ()) or ()))
    if not vertices:
        return (0.0, 0.0, 0.0)
    xs, ys, zs = zip(*vertices)
    return (
        (min(xs) + max(xs)) * 0.5,
        (min(ys) + max(ys)) * 0.5,
        (min(zs) + max(zs)) * 0.5,
    )


def model_bounds_x(model: object) -> tuple[float, float]:
    values: list[float] = []
    for mesh in getattr(model, "meshes", ()) or ():
        for position in getattr(mesh, "positions", ()) or ():
            try:
                values.append(float(position[0]))
            except (TypeError, ValueError, IndexError):
                continue
    if not values:
        return (-0.5, 0.5)
    return (min(values), max(values))


def translated_preview_model(model: object, delta_x: float, *, clone_model: Callable[[object], object]) -> object:
    cloned = clone_model(model)
    if not isinstance(cloned, ModelPreviewData):
        return cloned
    for mesh in getattr(cloned, "meshes", ()) or ():
        translated_positions = []
        for position in getattr(mesh, "positions", ()) or ():
            if len(position) >= 3:
                translated_positions.append((float(position[0]) + float(delta_x), float(position[1]), float(position[2])))
        if translated_positions:
            mesh.positions = translated_positions
    return cloned


def tag_alignment_d3d11_workspace_model(
    model: object,
    role: str,
    *,
    editable: bool,
    clone_model: Callable[[object], object],
) -> ModelPreviewData | None:
    if not isinstance(model, ModelPreviewData):
        return None
    tagged = clone_model(model)
    if not isinstance(tagged, ModelPreviewData):
        return None
    for mesh in getattr(tagged, "meshes", ()) or ():
        try:
            mesh.preview_role = role
        except Exception:
            pass
        if not editable:
            try:
                mesh.source_vertex_indices = []
                mesh.source_face_indices = []
            except Exception:
                pass
    return tagged


def rough_control_value_from_settings(settings: object) -> float:
    try:
        return max(0.0, min(1.0, (float(getattr(settings, "shininess_max", 0.0)) - 32.0) / 224.0))
    except (TypeError, ValueError):
        return 0.25


__all__ = [
    "alignment_file_signature",
    "alignment_contract_preview_path",
    "alignment_sample_sequence",
    "alignment_sequence_digest",
    "best_source_for_slot",
    "binding_matches_target",
    "coerce_float_triple",
    "compact_context_value",
    "default_texture_uv_transform_state",
    "final_preview_binding_preview_status",
    "final_preview_material_status_color",
    "html_chip_span",
    "important_static_texture_tokens",
    "is_default_source_part_adjustment",
    "is_gltf_metallic_roughness_path",
    "is_marker_source",
    "mapping_status_summary_badge",
    "mapping_source_cell_text",
    "looks_like_standalone_pbr_source",
    "material_contract_block",
    "material_plan_summary_block",
    "material_routing_conflict_messages",
    "material_route_status_color",
    "mesh_center_for_ui",
    "model_bounds_x",
    "native_manifest_input_from_descriptor",
    "part_specific_tokens",
    "rough_control_value_from_settings",
    "routing_source_material_labels",
    "slot_kind_for_final_preview_row",
    "source_indices_for_target_contract",
    "source_material_output_path",
    "source_material_group_label",
    "source_material_names_for_mapping",
    "source_slot_for_texture_row",
    "source_texture_evidence_by_local_path",
    "source_texture_reference_keys",
    "source_texture_slot_count",
    "source_texture_path_for_plan_row",
    "set_texture_row_assignment",
    "tag_alignment_d3d11_workspace_model",
    "texture_context_chip_cell",
    "texture_context_kv_row",
    "texture_context_path_html",
    "texture_assignment_summary_html",
    "texture_plan_status_color",
    "texture_override_row_sort_key",
    "texture_role_label_for_slot",
    "texture_row_can_apply_suggested_for_target",
    "texture_row_can_auto_apply",
    "texture_row_contract_status_color",
    "texture_row_effective_source",
    "texture_row_current_source_indices",
    "texture_row_is_assigned",
    "texture_row_is_shared",
    "texture_row_override_key",
    "texture_row_source_summary",
    "texture_row_source_color",
    "texture_row_table_role_color",
    "texture_row_table_display",
    "texture_row_visible",
    "texture_set_for_source_index",
    "texture_file_lookup_maps",
    "texture_source_choices_for_row",
    "texture_status_text",
    "sync_texture_row_assignment_state",
    "target_texture_status_details",
    "target_texture_status_text",
    "texture_slot_role_color",
    "texture_slot_contract_key",
    "texture_source_key",
    "texture_summary_label_html",
    "texture_summary_metrics",
    "texture_set_factor_parameters",
    "translated_preview_model",
    "texture_uv_state_has_edits",
    "texture_uv_transform_key",
    "TextureRowTableDisplay",
]
