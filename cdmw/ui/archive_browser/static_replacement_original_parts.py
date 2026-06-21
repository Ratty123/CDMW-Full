"""Pure original-part copy helpers for static replacement."""

from __future__ import annotations

import copy
import dataclasses
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path


def original_target_label(original_index: int, original_mesh: object | None) -> str:
    if original_mesh is None:
        return f"original {original_index}"
    submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    if original_index < 0 or original_index >= len(submeshes):
        return f"original {original_index}"
    original_part = submeshes[original_index]
    return str(getattr(original_part, "material", "") or getattr(original_part, "name", "") or f"original {original_index}").strip()


def part_physics_review_reason(label_text: str, part: object) -> str:
    text = " ".join(
        (
            str(label_text or ""),
            str(getattr(part, "name", "") or ""),
            str(getattr(part, "material", "") or ""),
            str(getattr(part, "path", "") or ""),
        )
    ).lower()
    physics_tokens = (
        "physics",
        "collision",
        "cloth",
        "pbd",
        "ragdoll",
        "shape",
        "hkx",
        "hkt",
        "flag",
        "cape",
        "skirt",
        "sleeve",
    )
    matched = [token for token in physics_tokens if token in text]
    if not matched:
        return ""
    return (
        "Likely physics/collision-sensitive part "
        f"({', '.join(matched[:3])}). Target physics is preserved; copied geometry/textures do not auto-copy HKX/HKT."
    )


def target_physics_status_text(
    target_label_text: str,
    target: object,
    *,
    physics_review_reason: Callable[[str, object], str] = part_physics_review_reason,
) -> str:
    if physics_review_reason(target_label_text, target):
        return "Review"
    return "-"


def source_physics_status_text(
    source_index: int,
    target_index: int,
    replacement_mesh: object | None,
    copied_original_physics_sensitive_sources: set[int],
    *,
    source_role_label: Callable[[int], str],
    source_display_name: Callable[[int], str],
    physics_review_reason: Callable[[str, object], str] = part_physics_review_reason,
) -> str:
    try:
        source_index = int(source_index)
    except (TypeError, ValueError):
        return "-"
    if source_index in copied_original_physics_sensitive_sources:
        return "Review"
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ()) if replacement_mesh is not None else ()
    if source_index < 0 or source_index >= len(submeshes):
        return "-"
    source = submeshes[source_index]
    if physics_review_reason(
        f"{source_role_label(source_index)} {source_display_name(source_index)}",
        source,
    ):
        return "Review"
    if target_index >= 0:
        return "Preserved"
    return "-"


def physics_status_tooltip(status_text: str) -> str:
    if status_text == "Review":
        return "Likely physics/collision-sensitive. Target physics is preserved; geometry/textures can be copied, but HKX/HKT physics payloads are not auto-copied."
    if status_text == "Preserved":
        return "Replacement source uses the selected target slot; target-side physics/collision behavior remains unchanged."
    return "No physics/collision warning detected for this row."


def original_part_texture_intent_rows(
    original_index: int,
    original_mesh: object | None,
    sidecar_bindings: Sequence[object],
    *,
    target_label: Callable[[int], str],
    preview_source_for_path: Callable[[str], Path | None],
    binding_matches_target: Callable[[object, str], bool],
    classify_texture_binding: Callable[[str, str], object],
) -> list[dict[str, str]]:
    if original_mesh is None:
        return []
    submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    if original_index < 0 or original_index >= len(submeshes):
        return []
    target_name = target_label(original_index)
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_row(*, parameter_name: str, texture_path: str, slot_kind: str) -> None:
        normalized_texture = str(texture_path or "").replace("\\", "/").strip()
        if not normalized_texture.lower().endswith(".dds"):
            return
        normalized_parameter = str(parameter_name or "").strip()
        key = (normalized_parameter.lower(), normalized_texture.lower())
        if key in seen:
            return
        seen.add(key)
        source_path = ""
        preview_source = preview_source_for_path(normalized_texture)
        if isinstance(preview_source, Path) and preview_source.is_file():
            source_path = str(preview_source)
        rows.append(
            {
                "parameter_name": normalized_parameter,
                "texture_path": normalized_texture,
                "slot_kind": str(slot_kind or "material").strip().lower() or "material",
                "source_path": source_path,
            }
        )

    for binding in tuple(sidecar_bindings or ()):
        if not binding_matches_target(binding, target_name):
            continue
        texture_path = str(getattr(binding, "texture_path", "") or getattr(binding, "reference_name", "") or "")
        parameter_name = str(getattr(binding, "parameter_name", "") or getattr(binding, "sidecar_parameter_name", "") or "")
        classification = classify_texture_binding(parameter_name, texture_path)
        add_row(
            parameter_name=parameter_name,
            texture_path=texture_path,
            slot_kind=str(getattr(classification, "slot_kind", "") or "material"),
        )

    original_part = submeshes[original_index]
    mesh_texture = str(getattr(original_part, "texture", "") or "")
    if mesh_texture.lower().endswith(".dds"):
        add_row(parameter_name="mesh texture", texture_path=mesh_texture, slot_kind="base")
    role_order = {"base": 0, "normal": 1, "height": 2, "material": 3, "material_mask": 3}
    rows.sort(
        key=lambda row: (
            role_order.get(str(row.get("slot_kind", "") or "").lower(), 9),
            str(row.get("parameter_name", "") or "").lower(),
            str(row.get("texture_path", "") or "").lower(),
        )
    )
    return rows


def copied_original_texture_tooltip(rows: Sequence[Mapping[str, object]]) -> str:
    if not rows:
        return ""
    lines = ["Copied original DDS refs:"]
    for row in rows[:24]:
        role = str(row.get("slot_kind", "") or "texture")
        parameter = str(row.get("parameter_name", "") or "DDS")
        texture_path = str(row.get("texture_path", "") or "")
        source_path = str(row.get("source_path", "") or "")
        lines.append(f"{role} | {parameter}: {texture_path}" + (f" -> {Path(source_path).name}" if source_path else " (visible only)"))
    return "\n".join(lines)


def copy_original_part_payload(
    original_index: int,
    original_mesh: object | None,
    *,
    target_label: Callable[[int], str],
    role_hint: Callable[[str], str],
    texture_intent_rows: Callable[[int], list[dict[str, str]]],
    physics_review_reason: Callable[[str, object], str],
) -> dict[str, object] | None:
    if original_mesh is None:
        return None
    submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    if original_index < 0 or original_index >= len(submeshes):
        return None
    original_part = submeshes[original_index]
    copied_part = dataclasses.replace(original_part)
    copied_part.vertices = list(getattr(original_part, "vertices", ()) or ())
    copied_part.normals = list(getattr(original_part, "normals", ()) or ())
    copied_part.uvs = list(getattr(original_part, "uvs", ()) or ())
    copied_part.faces = list(getattr(original_part, "faces", ()) or ())
    if hasattr(copied_part, "bone_indices"):
        copied_part.bone_indices = list(getattr(original_part, "bone_indices", ()) or ())
    if hasattr(copied_part, "bone_weights"):
        copied_part.bone_weights = list(getattr(original_part, "bone_weights", ()) or ())
    label = target_label(original_index)
    physics_reason = physics_review_reason(label, original_part)
    return {
        "kind": "original_part",
        "original_submesh_index": int(original_index),
        "label": label,
        "role": role_hint(f"{getattr(original_part, 'name', '')} {getattr(original_part, 'material', '')} {label}"),
        "submesh": copied_part,
        "texture_rows": texture_intent_rows(original_index),
        "physics_review_reason": physics_reason,
    }


def copied_original_dds_badge(
    source_index: int,
    rows: Sequence[Mapping[str, object]],
    disabled_sources: set[int],
) -> str:
    if not rows:
        return ""
    if int(source_index) in disabled_sources:
        return "Route DDS"
    return f"Copied Orig {len(rows):,}"


def copied_original_source_indices(
    replacement_mesh: object | None,
    copied_source_indices: set[int],
) -> set[int]:
    if replacement_mesh is None:
        return set()
    source_count = len(tuple(getattr(replacement_mesh, "submeshes", ()) or ()))
    return {
        int(source_index)
        for source_index in copied_source_indices
        if 0 <= int(source_index) < source_count
    }


def original_part_clipboard_can_paste(
    clipboard: Mapping[str, object],
    original_mesh: object | None,
) -> bool:
    if str(clipboard.get("kind", "") or "") != "original_part":
        return False
    try:
        original_index = int(clipboard.get("original_submesh_index", -1))
    except (TypeError, ValueError):
        return False
    submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ()) if original_mesh is not None else ()
    return bool(0 <= original_index < len(submeshes) and clipboard.get("submesh") is not None)


def original_part_action_control_text() -> dict[str, str]:
    return {
        "copy": "Copy Original As Source",
        "copy_assign": "Copy + Assign To Target",
        "clear_selection": "Clear Original",
        "copy_tooltip": (
            "Copy the selected original reference part into Replacement sources, then select it for role, target, "
            "and transform edits."
        ),
        "copy_assign_tooltip": (
            "Copy the selected original reference part, add it to Replacement sources, and map it to the currently "
            "selected target row."
        ),
        "clear_selection_tooltip": "Clear only the original reference part selection and preview highlight.",
    }


def original_part_tree_control_text() -> dict[str, object]:
    return {
        "headers": ["#", "Original part", "Role", "Geometry", "Copied as"],
    }


def original_part_clipboard_action_text() -> dict[str, str]:
    return {
        "copy_part_with_textures": "Copy Part With Textures",
        "copy_select_title": "Copy Part With Textures",
        "copy_select_message": "Select an original reference part to copy first.",
        "paste_replacement_source": "Paste As Replacement Source",
        "paste_select_title": "Paste Replacement Source",
        "paste_select_message": "Copy an original reference part first.",
        "select_original_title": "Select Original Part",
        "select_original_message": "Select an original reference part to copy first.",
        "paste_undo_label": "Paste original part as source",
        "copy_undo_label": "Copy original as source",
    }


def copied_original_physics_status_message() -> str:
    return (
        "Copied original part as replacement geometry. Target physics is preserved; "
        "no HKX/HKT physics files were auto-copied."
    )


def copied_original_clipboard_status_message(original_index: int, texture_row_count: int) -> str:
    return f"Copied original part {int(original_index)} with {int(texture_row_count):,} DDS reference(s)."


def pasted_original_source_status_message(source_index: int) -> str:
    return f"Pasted original part as preview-only replacement source {int(source_index)}."


def copied_original_dds_cell_text(state_text: object, *, disabled: bool, copied_badge: object) -> str:
    return f"{str(state_text)} | {'Route DDS' if disabled else str(copied_badge)}"


def appended_original_copy_column_text(previous: object, source_index: int) -> str:
    previous_text = str(previous or "")
    if not previous_text:
        return str(int(source_index))
    return f"{previous_text}, {int(source_index)}"


def missing_copied_original_part_message() -> tuple[str, str]:
    return (
        "Paste Replacement Source",
        "The copied original part is no longer available in this alignment window.",
    )


def remapped_original_copy_source_text(text: str, index_map: Mapping[int, int]) -> str:
    remapped: list[str] = []
    for raw_part in re.split(r"[,;\s]+", str(text or "").strip()):
        if not raw_part:
            continue
        try:
            old_index = int(raw_part)
        except ValueError:
            continue
        new_index = index_map.get(old_index)
        if new_index is not None and str(int(new_index)) not in remapped:
            remapped.append(str(int(new_index)))
    return ", ".join(remapped)


def copied_original_part_source(
    copied_source: object,
    payload: Mapping[str, object],
    original_index: int,
    fallback_label: str,
    pasted: bool,
) -> object:
    copied_part = copy.deepcopy(copied_source)
    base_label = str(payload.get("label", "") or fallback_label).strip() or f"original {original_index}"
    copied_part.name = f"{base_label} (pasted copy)" if pasted else f"{base_label} (original copy)"
    if not getattr(copied_part, "material", ""):
        copied_part.material = base_label
    return copied_part


__all__ = [
    "appended_original_copy_column_text",
    "copy_original_part_payload",
    "copied_original_dds_cell_text",
    "copied_original_dds_badge",
    "copied_original_part_source",
    "copied_original_clipboard_status_message",
    "copied_original_physics_status_message",
    "copied_original_source_indices",
    "copied_original_texture_tooltip",
    "missing_copied_original_part_message",
    "original_part_action_control_text",
    "original_part_clipboard_action_text",
    "original_part_clipboard_can_paste",
    "original_part_tree_control_text",
    "original_part_texture_intent_rows",
    "original_target_label",
    "part_physics_review_reason",
    "pasted_original_source_status_message",
    "physics_status_tooltip",
    "remapped_original_copy_source_text",
    "source_physics_status_text",
    "target_physics_status_text",
]
