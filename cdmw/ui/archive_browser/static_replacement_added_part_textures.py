"""Pure added-part texture helpers for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from cdmw.ui.archive_browser.static_replacement_texture_rows import texture_set_for_source_index


@dataclass(frozen=True, slots=True)
class AddedPartTextureEditorState:
    has_source: bool
    source_choices: tuple[tuple[str, str], ...]
    current_source: str


@dataclass(frozen=True, slots=True)
class AddedPartTextureTreeVisibilityState:
    has_rows: bool
    empty_label_visible: bool
    tree_visible: bool
    editor_visible: bool


@dataclass(frozen=True, slots=True)
class AddedPartTextureGroupSizeState:
    max_height: int
    fixed_height: bool


@dataclass(frozen=True, slots=True)
class AddedPartTextureRowState:
    source_index: int
    source_display_name: str
    target_summary: str
    material_name: str
    base_display: str
    normal_display: str
    material_display: str
    height_display: str
    status_label: str
    status_color: str
    selected: bool


@dataclass(frozen=True, slots=True)
class AddedPartTextureChooseDialogState:
    should_open: bool
    title: str
    directory: str
    file_filter: str


def added_part_texture_control_text() -> dict[str, object]:
    return {
        "group_title": "Added Part Textures",
        "group_tooltip": (
            "Assign texture files to mesh parts imported with Add Mesh Part. "
            "Attached parts can export through their target draw/material slot; preview-only parts are session display only."
        ),
        "headers": ["Part", "Target", "Material", "Base", "Normal", "Mask", "Height", "Status"],
        "empty_label": "No added mesh parts in this session.",
        "slot_options": (
            ("base", "Base"),
            ("normal", "Normal"),
            ("material", "Mask"),
            ("height", "Height"),
        ),
        "assign_button": "Assign",
        "assign_detected_button": "Assign Detected",
        "clear_button": "Clear",
        "choose_base_button": "Choose Base",
        "choose_normal_button": "Choose Normal",
        "choose_mask_button": "Choose Mask",
        "choose_height_button": "Choose Height",
        "assign_detected_tooltip": "Store detected files as explicit overrides for the selected added part.",
        "choose_base_tooltip": "Choose the visible color texture for the selected added part.",
        "choose_normal_tooltip": "Choose the normal map for the selected added part.",
        "choose_mask_tooltip": "Choose the material/mask texture for the selected added part.",
        "choose_height_tooltip": "Choose the height/displacement texture for the selected added part.",
        "clear_tooltip": "Clear the explicit override for the selected role. Detected texture files remain available.",
        "role_label": "Role",
        "source_label": "Source",
    }


def added_part_texture_role_label(slot_kind: str) -> str:
    normalized = str(slot_kind or "").strip().lower()
    return {
        "base": "Base / Color",
        "normal": "Normal",
        "material": "Material / Mask",
        "height": "Height",
    }.get(normalized, str(slot_kind or "Texture").title())


def added_part_detected_missing_message() -> tuple[str, str]:
    return (
        "Assign Detected",
        "No detected texture files were found for the selected added part.",
    )


def added_part_texture_invalid_file_message() -> tuple[str, str]:
    return (
        "Choose Texture",
        "The selected file is not a supported texture image.",
    )


def selected_added_part_texture_row_initial_state() -> dict[str, int]:
    return {"source_index": -1}


def added_texture_editor_loading_initial_state() -> dict[str, bool]:
    return {"active": False}


def added_texture_editor_loading_set(
    loading_state: dict[str, bool],
    active: bool,
) -> dict[str, bool]:
    loading_state["active"] = bool(active)
    return dict(loading_state)


def current_added_part_texture_source_index(current_item_source_index: object, fallback_source_index: object) -> int:
    try:
        source_index = int(current_item_source_index)
    except (TypeError, ValueError):
        try:
            source_index = int(fallback_source_index)
        except (TypeError, ValueError):
            source_index = -1
    return source_index


def added_part_texture_tree_visibility_state(row_count: int) -> AddedPartTextureTreeVisibilityState:
    has_rows = int(row_count) > 0
    return AddedPartTextureTreeVisibilityState(
        has_rows=has_rows,
        empty_label_visible=not has_rows,
        tree_visible=has_rows,
        editor_visible=has_rows,
    )


def added_part_texture_group_size_state(
    has_rows: bool,
    *,
    empty_label_height: int,
    font_height: int,
) -> AddedPartTextureGroupSizeState:
    if bool(has_rows):
        return AddedPartTextureGroupSizeState(max_height=360, fixed_height=False)
    return AddedPartTextureGroupSizeState(
        max_height=max(46, int(empty_label_height) + int(font_height) + 22),
        fixed_height=True,
    )


def added_part_texture_editor_state(
    source_index: int,
    *,
    source_choices: Sequence[tuple[str, str]],
    current_source: str = "",
) -> AddedPartTextureEditorState:
    has_source = int(source_index) >= 0
    return AddedPartTextureEditorState(
        has_source=has_source,
        source_choices=tuple(source_choices or ()) if has_source else (("Select an added part", ""),),
        current_source=str(current_source or "") if has_source else "",
    )


def added_part_texture_editor_context_state(
    source_index: int,
    slot_kind: str,
    *,
    replacement_mesh: object | None,
    texture_sets_by_key: Mapping[str, object],
    override_assignments: Mapping[tuple[str, str], object],
    texture_files_for_mapping: Sequence[Path],
) -> AddedPartTextureEditorState:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    normalized_slot = str(slot_kind or "base").strip().lower() or "base"
    current_source = ""
    source_choices: tuple[tuple[str, str], ...] = ()
    if normalized_source_index >= 0:
        material_name = source_material_name_for_index(
            normalized_source_index,
            replacement_mesh,
            texture_sets_by_key,
        )
        material_name, normalized_slot = source_material_override_key(material_name, normalized_slot)
        current_source = str(override_assignments.get((material_name, normalized_slot), "") or "")
        source_choices = added_texture_source_choices(
            source_slot_for_added_part(
                normalized_source_index,
                normalized_slot,
                replacement_mesh,
                texture_sets_by_key,
                override_assignments,
            ),
            texture_files_for_mapping,
        )
    return added_part_texture_editor_state(
        normalized_source_index,
        source_choices=source_choices,
        current_source=current_source,
    )


def added_part_selected_texture_assignment_state(
    *,
    loading_active: bool,
    source_index: int,
    slot_kind: str,
    source_path: str,
) -> dict[str, object]:
    if bool(loading_active):
        return {"apply": False, "source_index": -1, "slot_kind": "", "source_path": ""}
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    return {
        "apply": normalized_source_index >= 0,
        "source_index": normalized_source_index,
        "slot_kind": str(slot_kind or "base").strip().lower() or "base",
        "source_path": str(source_path or "").strip(),
    }


def added_part_texture_override_action_state(
    *,
    source_index: int,
    material_name: str,
    slot_kind: str,
    source_path: str,
) -> dict[str, object]:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    if normalized_source_index < 0:
        return {"apply": False, "source_index": -1}
    normalized_material_name, normalized_slot = source_material_override_key(material_name, slot_kind)
    normalized_source = str(source_path or "").strip()
    return {
        "apply": True,
        "source_index": normalized_source_index,
        "assignment_key": (normalized_material_name, normalized_slot),
        "source_path": normalized_source,
        "clear": not bool(normalized_source),
        "enable_rebuild_sidecar": bool(normalized_source),
        "enable_inject_base_color": bool(normalized_source and normalized_slot == "base"),
        "mark_dirty": True,
    }


def added_part_detected_assignment_state(
    *,
    source_index: int,
    slot_sources: Mapping[str, object],
) -> dict[str, object]:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    if normalized_source_index < 0:
        return {"apply": False, "assignments": (), "show_missing": False}
    assignments: list[tuple[str, str]] = []
    for slot_kind in ("base", "normal", "material", "height"):
        source_path = slot_sources.get(slot_kind)
        if isinstance(source_path, Path):
            assignments.append((slot_kind, str(source_path)))
    return {
        "apply": True,
        "assignments": tuple(assignments),
        "show_missing": not bool(assignments),
    }


def added_part_texture_choose_dialog_state(
    source_index: int,
    slot_kind: str,
    *,
    obj_parent: object,
) -> AddedPartTextureChooseDialogState:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    if normalized_source_index < 0:
        return AddedPartTextureChooseDialogState(
            should_open=False,
            title="",
            directory="",
            file_filter="",
        )
    title_slot = str(slot_kind or "base").replace("_", " ").title()
    parent_path = Path(obj_parent)
    return AddedPartTextureChooseDialogState(
        should_open=True,
        title=f"Choose {title_slot} Texture",
        directory=str(parent_path),
        file_filter="Texture files (*.png *.dds *.jpg *.jpeg *.tga *.bmp *.tif *.tiff);;All files (*.*)",
    )


def source_material_name_for_index(
    source_index: int,
    replacement_mesh: object | None,
    texture_sets_by_key: Mapping[str, object],
) -> str:
    texture_set = texture_set_for_source_index(source_index, replacement_mesh, texture_sets_by_key)
    material_name = str(getattr(texture_set, "material_name", "") or "").strip() if texture_set is not None else ""
    if material_name:
        return material_name
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ()) if replacement_mesh is not None else ()
    if source_index < 0 or source_index >= len(submeshes):
        return f"source_{source_index}"
    source = submeshes[source_index]
    return str(getattr(source, "material", "") or getattr(source, "name", "") or f"source_{source_index}").strip()


def source_material_override_key(material_name: str, slot_kind: str) -> tuple[str, str]:
    return (str(material_name or "").strip(), str(slot_kind or "").strip().lower())


def source_slot_for_added_part(
    source_index: int,
    slot_kind: str,
    replacement_mesh: object | None,
    texture_sets_by_key: Mapping[str, object],
    override_assignments: Mapping[tuple[str, str], object],
) -> Path | None:
    material_name = source_material_name_for_index(source_index, replacement_mesh, texture_sets_by_key)
    _material_name, normalized_slot = source_material_override_key(material_name, slot_kind)
    override_path = str(override_assignments.get((material_name, normalized_slot), "") or "").strip()
    if override_path:
        return Path(override_path)
    texture_set = texture_set_for_source_index(source_index, replacement_mesh, texture_sets_by_key)
    slots = getattr(texture_set, "slots", {}) or {}
    candidates = [normalized_slot]
    if normalized_slot == "material":
        candidates.extend(["material_mask", "detail_mask"])
    for candidate in candidates:
        slot = slots.get(candidate)
        source_path = getattr(slot, "source_path", None) if slot is not None else None
        if isinstance(source_path, Path):
            return source_path
    return None


def added_part_attached_targets(source_index: int, mappings: Sequence[object]) -> tuple[int, ...]:
    target_indices: list[int] = []
    for mapping in tuple(mappings or ()):
        if int(source_index) not in tuple(getattr(mapping, "source_submesh_indices", ()) or ()):
            continue
        try:
            target_index = int(getattr(mapping, "target_submesh_index", -1))
        except (TypeError, ValueError):
            target_index = -1
        if target_index >= 0 and target_index not in target_indices:
            target_indices.append(target_index)
    return tuple(target_indices)


def added_part_target_summary(
    source_index: int,
    targets: Sequence[int],
    preview_only_source_indices: set[int],
    *,
    target_display_name: Callable[[int], str],
) -> str:
    if targets:
        return ", ".join(target_display_name(int(target_index)) for target_index in tuple(targets)[:3])
    if source_index in preview_only_source_indices:
        return "Preview only"
    return "Attach required"


def added_part_target_has_material_conflict(
    source_index: int,
    mappings: Sequence[object],
    *,
    source_material_name_for_index: Callable[[int], str],
) -> bool:
    for mapping in tuple(mappings or ()):
        if int(source_index) not in tuple(getattr(mapping, "source_submesh_indices", ()) or ()):
            continue
        material_names: dict[str, str] = {}
        for mapped_source_index in tuple(getattr(mapping, "source_submesh_indices", ()) or ()):
            material_name = source_material_name_for_index(int(mapped_source_index))
            if material_name:
                material_names.setdefault(material_name.lower(), material_name)
        if len(material_names) > 1:
            return True
    return False


def added_part_texture_status(
    source_index: int,
    *,
    attached_targets: Sequence[int],
    has_material_conflict: bool,
    base_source_path: Path | None,
    preview_only_source_indices: set[int],
) -> tuple[str, str]:
    if not tuple(attached_targets or ()):
        if source_index in preview_only_source_indices:
            return "Preview only", "#79c0ff"
        return "Attach required", "#f85149"
    if has_material_conflict:
        return "Target conflict", "#f85149"
    if base_source_path is None:
        return "Missing base", "#f85149"
    return "Ready", "#3fb950"


def added_part_texture_display(
    material_name: str,
    slot_kind: str,
    override_assignments: Mapping[tuple[str, str], object],
    source_path: Path | None,
) -> str:
    _material_name, normalized_slot = source_material_override_key(material_name, slot_kind)
    override_path = str(override_assignments.get((material_name, normalized_slot), "") or "").strip()
    if override_path:
        return Path(override_path).name
    return source_path.name if isinstance(source_path, Path) else "-"


def added_texture_source_choices(
    detected_path: Path | None,
    texture_files_for_mapping: Sequence[Path],
) -> tuple[tuple[str, str], ...]:
    choices: list[tuple[str, str]] = [("Use detected / none", "")]
    seen: set[str] = set()

    def add_choice(label: str, path_value: object) -> None:
        path_text = str(path_value or "").strip()
        if not path_text:
            return
        key = path_text.replace("\\", "/").lower()
        if key in seen:
            return
        seen.add(key)
        choices.append((label, path_text))

    if isinstance(detected_path, Path):
        add_choice(f"Detected: {detected_path.name}", detected_path)
    for texture_file in tuple(texture_files_for_mapping or ()):
        add_choice(texture_file.name, texture_file)
    return tuple(choices)


def added_part_texture_row_states(
    appended_source_indices: Sequence[object],
    *,
    replacement_mesh: object | None,
    mappings: Sequence[object],
    texture_sets_by_key: Mapping[str, object],
    override_assignments: Mapping[tuple[str, str], object],
    preview_only_source_indices: set[int],
    preserve_source_index: int,
    source_display_name: Callable[[int], str],
    target_display_name: Callable[[int], str],
) -> tuple[AddedPartTextureRowState, ...]:
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ()) if replacement_mesh is not None else ()
    rows: list[AddedPartTextureRowState] = []
    for raw_source_index in sorted(int(index) for index in tuple(appended_source_indices or ())):
        source_index = int(raw_source_index)
        if replacement_mesh is None or source_index < 0 or source_index >= len(submeshes):
            continue
        material_name = source_material_name_for_index(
            source_index,
            replacement_mesh,
            texture_sets_by_key,
        )
        targets = added_part_attached_targets(source_index, mappings)
        status_label, status_color = added_part_texture_status(
            source_index,
            attached_targets=targets,
            has_material_conflict=added_part_target_has_material_conflict(
                source_index,
                mappings,
                source_material_name_for_index=lambda index: source_material_name_for_index(
                    int(index),
                    replacement_mesh,
                    texture_sets_by_key,
                ),
            ),
            base_source_path=source_slot_for_added_part(
                source_index,
                "base",
                replacement_mesh,
                texture_sets_by_key,
                override_assignments,
            ),
            preview_only_source_indices=preview_only_source_indices,
        )
        slot_displays = {
            slot_kind: added_part_texture_display(
                material_name,
                slot_kind,
                override_assignments,
                source_slot_for_added_part(
                    source_index,
                    slot_kind,
                    replacement_mesh,
                    texture_sets_by_key,
                    override_assignments,
                ),
            )
            for slot_kind in ("base", "normal", "material", "height")
        }
        rows.append(
            AddedPartTextureRowState(
                source_index=source_index,
                source_display_name=source_display_name(source_index),
                target_summary=added_part_target_summary(
                    source_index,
                    targets,
                    preview_only_source_indices,
                    target_display_name=target_display_name,
                ),
                material_name=material_name,
                base_display=slot_displays["base"],
                normal_display=slot_displays["normal"],
                material_display=slot_displays["material"],
                height_display=slot_displays["height"],
                status_label=status_label,
                status_color=status_color,
                selected=int(preserve_source_index) == source_index,
            )
        )
    return tuple(rows)


__all__ = [
    "AddedPartTextureEditorState",
    "AddedPartTextureChooseDialogState",
    "AddedPartTextureGroupSizeState",
    "AddedPartTextureRowState",
    "AddedPartTextureTreeVisibilityState",
    "added_part_detected_assignment_state",
    "added_part_selected_texture_assignment_state",
    "added_part_texture_choose_dialog_state",
    "added_part_texture_editor_context_state",
    "added_part_texture_editor_state",
    "added_part_texture_group_size_state",
    "added_part_texture_row_states",
    "added_part_texture_tree_visibility_state",
    "added_part_texture_override_action_state",
    "added_texture_editor_loading_set",
    "added_texture_editor_loading_initial_state",
    "added_part_detected_missing_message",
    "current_added_part_texture_source_index",
    "added_part_texture_control_text",
    "added_part_texture_invalid_file_message",
    "added_part_texture_role_label",
    "added_part_attached_targets",
    "added_part_target_has_material_conflict",
    "added_part_target_summary",
    "added_part_texture_display",
    "added_part_texture_status",
    "added_texture_source_choices",
    "selected_added_part_texture_row_initial_state",
    "source_material_name_for_index",
    "source_material_override_key",
    "source_slot_for_added_part",
]
