"""Selected source-part properties text helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourcePartPropertiesInspectorState:
    identity_text: str
    assignment_text: str
    dds_text: str
    output_text: str
    warning_text: str
    identity_html: str
    assignment_html: str
    dds_html: str
    output_html: str
    warning_html: str
    warning_visible: bool


def source_part_properties_control_text() -> dict[str, object]:
    return {
        "title": "Properties",
        "group_object": "MeshReplacementPropertiesContext",
        "placeholder": "-",
        "sections": {
            "identity": ("Identity", "MeshReplacementPropertiesIdentity"),
            "assignment": ("Assignment", "MeshReplacementPropertiesAssignment"),
            "dds": ("DDS / Sidecar", "MeshReplacementPropertiesDDS"),
            "output": ("Output", "MeshReplacementPropertiesOutput"),
            "warnings": ("Warnings", "MeshReplacementPropertiesWarnings"),
        },
        "dds_default": "DDS | -",
        "none_identity": "Selection | none",
        "none_assignment": "Target/source/material row not selected.",
    }


def source_part_properties_label_html(section_title: str, value: str) -> str:
    return f"<b>{escape(str(section_title))}</b><br>{escape(str(value or '-'))}"


def source_part_properties_output_text(
    removed_count: int,
    used_source_count: int,
    disabled_source_count: int,
    generated_dds_count: int,
    sidecar_status: str,
) -> str:
    return (
        f"Output | remove {int(removed_count):,} | source {int(used_source_count):,} "
        f"| disabled {int(disabled_source_count):,} | DDS {int(generated_dds_count):,} "
        f"| sidecar {str(sidecar_status or '-')}"
    )


def source_part_target_properties_warning(state: str, sidecar_status: str) -> str:
    normalized_state = str(state or "").strip()
    normalized_sidecar = str(sidecar_status or "").strip()
    if normalized_state == "Removed" and normalized_sidecar in {"prune removed", "visible only"}:
        return "Removed target: geometry is omitted; patched sidecar prunes its DDS parameters."
    if normalized_state == "Removed":
        return "Removed target: geometry is omitted; sidecar DDS references are kept unless material sidecar patching is enabled."
    if normalized_state == "Physics":
        return "Review physics/collision companion data."
    return ""


def source_part_source_properties_warning(mapped_targets: Sequence[int]) -> str:
    return "" if tuple(mapped_targets or ()) else "This source will not replace an original target until assigned."


def source_part_source_properties_dds_text(material_name: str) -> str:
    return f"DDS | {str(material_name or '').strip() or 'material route in Materials tab'}"


def source_part_material_properties_text(
    material_name: str,
    texture_role: str,
    texture_source_name: str,
) -> tuple[str, str, str]:
    source_name = str(texture_source_name or "").strip() or "-"
    return (
        f"Material | {str(material_name or '').strip() or '-'}",
        f"{str(texture_role or '').strip() or 'DDS'} | {source_name}",
        f"DDS | {source_name}",
    )


def _int_tuple(values: object) -> tuple[int, ...]:
    normalized: list[int] = []
    for value in tuple(values or ()):
        try:
            normalized.append(int(value))
        except (TypeError, ValueError):
            continue
    return tuple(normalized)


def source_part_properties_inspector_state(
    selection_model: Mapping[str, object],
    *,
    output_counts: Sequence[object],
    target_source_indices: Callable[[int], Sequence[int]],
    target_outliner_state: Callable[[int, Sequence[int]], tuple[str, str]],
    format_source_indices: Callable[[Sequence[int]], str],
    format_target_indices: Callable[[Sequence[int]], str],
    target_dds_label: Callable[[int], str],
    target_texture_status_text: Callable[[str], str],
    source_assigned_target_indices: Callable[[int], Sequence[int]],
    source_outliner_state: Callable[[int, Sequence[int]], object],
    source_material_name: Callable[[int], str],
) -> SourcePartPropertiesInspectorState:
    control_text = source_part_properties_control_text()
    sections = control_text["sections"]
    kind = str(selection_model.get("kind") or "none")
    source_indices = _int_tuple(selection_model.get("source_indices", ()))
    target_indices = _int_tuple(selection_model.get("target_indices", ()))
    material_name = str(selection_model.get("material_name") or "")
    texture_role = str(selection_model.get("texture_role") or "")
    texture_path = str(selection_model.get("texture_path") or "")
    warning = str(selection_model.get("warning") or "")
    removed_count, used_source_count, disabled_source_count, generated_dds_count, sidecar_status = tuple(output_counts)
    dds_text = str(control_text["dds_default"])
    if kind == "target":
        target_index = target_indices[0] if target_indices else -1
        source_indices = tuple(int(index) for index in target_source_indices(target_index))
        state, _color = target_outliner_state(target_index, source_indices)
        identity = f"Target | {format_target_indices((target_index,))}"
        assignment = f"{state} | {format_source_indices(source_indices)}"
        target_name = target_dds_label(target_index)
        sidecar_text = str(sidecar_status if state == "Removed" else "mapped")
        dds_text = f"DDS | {target_texture_status_text(target_name) if target_name else '-'} | sidecar {sidecar_text}"
        warning = warning or source_part_target_properties_warning(state, str(sidecar_status))
    elif kind == "source":
        mapped_targets = tuple(
            int(target_index)
            for source_index in source_indices
            for target_index in source_assigned_target_indices(int(source_index))
        )
        raw_source_state = source_outliner_state(source_indices[0], mapped_targets) if source_indices else "Unassigned"
        source_state = raw_source_state[0] if isinstance(raw_source_state, tuple) else raw_source_state
        if not material_name and source_indices:
            material_name = source_material_name(source_indices[0])
        identity = f"Source | {format_source_indices(source_indices)}"
        if material_name:
            identity = f"{identity} | {material_name}"
        assignment = f"{source_state} | {format_target_indices(mapped_targets)}"
        dds_text = source_part_source_properties_dds_text(material_name)
        warning = warning or source_part_source_properties_warning(mapped_targets)
    elif kind == "material":
        identity, assignment, dds_text = source_part_material_properties_text(
            material_name,
            texture_role,
            Path(texture_path).name if texture_path else "",
        )
    else:
        identity = str(control_text["none_identity"])
        assignment = str(control_text["none_assignment"])
    output = source_part_properties_output_text(
        int(removed_count),
        int(used_source_count),
        int(disabled_source_count),
        int(generated_dds_count),
        str(sidecar_status),
    )
    warning_text = warning or "-"
    return SourcePartPropertiesInspectorState(
        identity_text=identity,
        assignment_text=assignment,
        dds_text=dds_text,
        output_text=output,
        warning_text=warning_text,
        identity_html=source_part_properties_label_html(sections["identity"][0], identity),
        assignment_html=source_part_properties_label_html(sections["assignment"][0], assignment),
        dds_html=source_part_properties_label_html(sections["dds"][0], dds_text),
        output_html=source_part_properties_label_html(sections["output"][0], output),
        warning_html=source_part_properties_label_html(sections["warnings"][0], warning_text),
        warning_visible=bool(warning),
    )


__all__ = [
    "SourcePartPropertiesInspectorState",
    "source_part_material_properties_text",
    "source_part_properties_control_text",
    "source_part_properties_inspector_state",
    "source_part_properties_label_html",
    "source_part_properties_output_text",
    "source_part_source_properties_dds_text",
    "source_part_source_properties_warning",
    "source_part_target_properties_warning",
]
