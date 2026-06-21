"""Selected source-part append label state helpers for static replacement."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SourcePartAppendIndexState:
    appended_source_indices: tuple[int, ...]
    independent_output_source_indices: tuple[int, ...]
    preview_only_source_indices: tuple[int, ...]


@dataclass(frozen=True)
class SourcePartAppendPresentation:
    source_index: int
    display_override: str
    role_hint_text: str


@dataclass(frozen=True, slots=True)
class SourcePartAppendFileRouteState:
    route: str
    suffix: str


@dataclass(frozen=True, slots=True)
class SourcePartAppendTextureControlState:
    enable_rebuild_sidecar: bool
    enable_inject_base_color: bool


@dataclass(frozen=True, slots=True)
class SourcePartAppendRollbackSnapshot:
    replacement_mesh: object
    replacement_base_mesh: object
    appended_source_indices: tuple[int, ...]
    independent_output_source_indices: tuple[int, ...]
    preview_only_source_indices: tuple[int, ...]
    source_role_overrides: dict[int, object]
    source_display_overrides: dict[int, object]
    source_part_adjustments: dict[int, object]
    dialog_added_supplemental_files: tuple[object, ...]
    texture_files_for_mapping: tuple[object, ...]
    source_material_texture_override_assignments: dict[object, object]
    mesh_edit_redo_stack: tuple[object, ...]
    mesh_edit_redo_adjustment_stack: object
    source_geometry_revision: int
    selected_source_index: int
    selected_source_indices: tuple[int, ...]
    selected_target_index: int
    selected_original_index: int
    selected_source_highlights: tuple[int, ...]
    selected_target_source_highlights: tuple[int, ...]
    transform_source_indices: tuple[int, ...]
    selected_original_highlights: tuple[int, ...]
    selected_target_original_highlights: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SourcePartAppendImportedState:
    source_indices: tuple[int, ...]
    first_source_index: int
    index_state: SourcePartAppendIndexState
    presentations: tuple[SourcePartAppendPresentation, ...]


def source_part_append_material_label(source: object, source_index: object) -> str:
    material = getattr(source, "material", "") or getattr(source, "name", "") or f"part {source_index}"
    return str(material).strip()


def source_part_append_ordinal_suffix(*, appended_ordinal: int, appended_source_count: int) -> str:
    try:
        ordinal = int(appended_ordinal)
        count = int(appended_source_count)
    except (TypeError, ValueError):
        return ""
    if count <= 1:
        return ""
    return f" part {ordinal}/{count}"


def source_part_append_display_override(
    *,
    source_stem: object,
    material_label: object,
    ordinal_suffix: object,
) -> str:
    return f"{str(source_stem or '').strip()}: {str(material_label or '').strip()}{str(ordinal_suffix or '')}"


def source_part_append_role_hint_text(*, source_stem: object, material_label: object) -> str:
    return f"{str(source_stem or '').strip()} {str(material_label or '').strip()}"


def source_part_append_index_state(
    *,
    source_indices: Sequence[int],
    appended_source_indices: Sequence[int],
    independent_output_source_indices: Sequence[int],
    preview_only_source_indices: Sequence[int],
) -> SourcePartAppendIndexState:
    new_indices = tuple(int(index) for index in tuple(source_indices or ()))
    appended = {int(index) for index in tuple(appended_source_indices or ())}
    independent_output = {int(index) for index in tuple(independent_output_source_indices or ())}
    preview_only = {int(index) for index in tuple(preview_only_source_indices or ())}

    appended.update(new_indices)
    independent_output.difference_update(new_indices)
    preview_only.update(new_indices)

    return SourcePartAppendIndexState(
        appended_source_indices=tuple(sorted(appended)),
        independent_output_source_indices=tuple(sorted(independent_output)),
        preview_only_source_indices=tuple(sorted(preview_only)),
    )


def source_part_append_presentations(
    *,
    source_indices: Sequence[int],
    sources: Sequence[object],
    source_stem: object,
) -> tuple[SourcePartAppendPresentation, ...]:
    indices = tuple(int(index) for index in tuple(source_indices or ()))
    appended_source_count = len(indices)
    presentations: list[SourcePartAppendPresentation] = []
    for appended_ordinal, source_index in enumerate(indices, start=1):
        if not 0 <= source_index < len(sources):
            continue
        source = sources[source_index]
        material_label = source_part_append_material_label(source, source_index)
        ordinal_suffix = source_part_append_ordinal_suffix(
            appended_ordinal=appended_ordinal,
            appended_source_count=appended_source_count,
        )
        presentations.append(
            SourcePartAppendPresentation(
                source_index=source_index,
                display_override=source_part_append_display_override(
                    source_stem=source_stem,
                    material_label=material_label,
                    ordinal_suffix=ordinal_suffix,
                ),
                role_hint_text=source_part_append_role_hint_text(
                    source_stem=source_stem,
                    material_label=material_label,
                ),
            )
        )
    return tuple(presentations)


def source_part_append_mesh_file_dialog_text() -> dict[str, str]:
    return {
        "title": "Add Mesh Part",
        "mesh_filter": "Mesh Sources (*.obj *.dae *.gltf *.glb *.pac *.pam *.pamlod);;All Files (*.*)",
        "fbx_title": "FBX Import Deferred",
        "fbx_message": (
            "FBX import is not supported inside Geometry yet. Export the part as OBJ, DAE, glTF/GLB, PAC, PAM, "
            "or PAMLOD first."
        ),
        "unsupported_title": "Unsupported Mesh Part",
        "unsupported_message_prefix": "Geometry can append OBJ, DAE, glTF/GLB, PAC, PAM, or PAMLOD files.",
    }


def source_part_append_file_route_state(
    source_path: object,
    *,
    allowed_extensions: Sequence[str],
) -> SourcePartAppendFileRouteState:
    path_text = str(source_path or "").strip()
    if not path_text:
        return SourcePartAppendFileRouteState("cancel", "")
    suffix = ""
    if "." in path_text:
        suffix = "." + path_text.rsplit(".", 1)[-1].lower()
    allowed = {str(extension).lower() for extension in tuple(allowed_extensions or ())}
    if suffix == ".fbx":
        return SourcePartAppendFileRouteState("fbx_deferred", suffix)
    if suffix not in allowed:
        return SourcePartAppendFileRouteState("unsupported", suffix)
    return SourcePartAppendFileRouteState("import", suffix)


def source_part_append_texture_control_state(
    *,
    has_texture_files: bool,
    texture_sets: Sequence[object],
) -> SourcePartAppendTextureControlState:
    enable_rebuild = bool(has_texture_files)
    enable_base_color = False
    if enable_rebuild:
        for texture_set in tuple(texture_sets or ()):
            slots = getattr(texture_set, "slots", {}) or {}
            if texture_set is not None and "base" in slots:
                enable_base_color = True
                break
    return SourcePartAppendTextureControlState(
        enable_rebuild_sidecar=enable_rebuild,
        enable_inject_base_color=enable_base_color,
    )


def _int_tuple(values: Sequence[int]) -> tuple[int, ...]:
    normalized: list[int] = []
    for raw_index in tuple(values or ()):
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index not in normalized:
            normalized.append(index)
    return tuple(normalized)


def source_part_append_rollback_snapshot(
    *,
    replacement_mesh: object,
    replacement_base_mesh: object,
    appended_source_indices: Sequence[int],
    independent_output_source_indices: Sequence[int],
    preview_only_source_indices: Sequence[int],
    source_role_overrides: dict[int, object],
    source_display_overrides: dict[int, object],
    source_part_adjustments: dict[int, object],
    dialog_added_supplemental_files: Sequence[object],
    texture_files_for_mapping: Sequence[object],
    source_material_texture_override_assignments: dict[object, object],
    mesh_edit_redo_stack: Sequence[object],
    mesh_edit_redo_adjustment_stack: object,
    source_geometry_revision: object,
    selected_source_index: object,
    selected_source_indices: Sequence[int],
    selected_target_index: object,
    selected_original_index: object,
    selected_source_highlights: Sequence[int],
    selected_target_source_highlights: Sequence[int],
    transform_source_indices: Sequence[int],
    selected_original_highlights: Sequence[int],
    selected_target_original_highlights: Sequence[int],
) -> SourcePartAppendRollbackSnapshot:
    def _int_value(value: object, default: int = -1) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return SourcePartAppendRollbackSnapshot(
        replacement_mesh=replacement_mesh,
        replacement_base_mesh=replacement_base_mesh,
        appended_source_indices=_int_tuple(appended_source_indices),
        independent_output_source_indices=_int_tuple(independent_output_source_indices),
        preview_only_source_indices=_int_tuple(preview_only_source_indices),
        source_role_overrides=dict(source_role_overrides),
        source_display_overrides=dict(source_display_overrides),
        source_part_adjustments=copy.deepcopy(source_part_adjustments),
        dialog_added_supplemental_files=tuple(dialog_added_supplemental_files or ()),
        texture_files_for_mapping=tuple(texture_files_for_mapping or ()),
        source_material_texture_override_assignments=dict(source_material_texture_override_assignments),
        mesh_edit_redo_stack=tuple(mesh_edit_redo_stack or ()),
        mesh_edit_redo_adjustment_stack=copy.deepcopy(mesh_edit_redo_adjustment_stack),
        source_geometry_revision=_int_value(source_geometry_revision, 0),
        selected_source_index=_int_value(selected_source_index),
        selected_source_indices=_int_tuple(selected_source_indices),
        selected_target_index=_int_value(selected_target_index),
        selected_original_index=_int_value(selected_original_index),
        selected_source_highlights=_int_tuple(selected_source_highlights),
        selected_target_source_highlights=_int_tuple(selected_target_source_highlights),
        transform_source_indices=_int_tuple(transform_source_indices),
        selected_original_highlights=_int_tuple(selected_original_highlights),
        selected_target_original_highlights=_int_tuple(selected_target_original_highlights),
    )


def source_part_append_imported_state(
    *,
    source_indices: Sequence[int],
    sources: Sequence[object],
    source_stem: object,
    appended_source_indices: Sequence[int],
    independent_output_source_indices: Sequence[int],
    preview_only_source_indices: Sequence[int],
) -> SourcePartAppendImportedState:
    normalized_source_indices = _int_tuple(source_indices)
    return SourcePartAppendImportedState(
        source_indices=normalized_source_indices,
        first_source_index=normalized_source_indices[0] if normalized_source_indices else -1,
        index_state=source_part_append_index_state(
            source_indices=normalized_source_indices,
            appended_source_indices=appended_source_indices,
            independent_output_source_indices=independent_output_source_indices,
            preview_only_source_indices=preview_only_source_indices,
        ),
        presentations=source_part_append_presentations(
            source_indices=normalized_source_indices,
            sources=sources,
            source_stem=source_stem,
        ),
    )


def source_part_unsupported_mesh_part_message(source_name: str) -> str:
    text = source_part_append_mesh_file_dialog_text()
    return f"{text['unsupported_message_prefix']}\n\nSelected: {source_name}"


def source_part_add_mesh_part_failed_title() -> str:
    return "Add Mesh Part Failed"


def source_part_added_mesh_part_status(source_name: str, placement_note: str = "") -> str:
    note = str(placement_note or "").strip()
    if note:
        return f"Added {source_name}; {note}."
    return f"Added {source_name} as a Geometry source part."


__all__ = [
    "SourcePartAppendFileRouteState",
    "SourcePartAppendIndexState",
    "SourcePartAppendImportedState",
    "SourcePartAppendPresentation",
    "SourcePartAppendRollbackSnapshot",
    "SourcePartAppendTextureControlState",
    "source_part_add_mesh_part_failed_title",
    "source_part_added_mesh_part_status",
    "source_part_append_display_override",
    "source_part_append_file_route_state",
    "source_part_append_index_state",
    "source_part_append_imported_state",
    "source_part_append_mesh_file_dialog_text",
    "source_part_append_material_label",
    "source_part_append_ordinal_suffix",
    "source_part_append_presentations",
    "source_part_append_role_hint_text",
    "source_part_append_texture_control_state",
    "source_part_append_rollback_snapshot",
    "source_part_unsupported_mesh_part_message",
]
