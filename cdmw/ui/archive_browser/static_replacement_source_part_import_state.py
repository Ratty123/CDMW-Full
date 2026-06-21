"""Selected source-part scene-import state helpers for static replacement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SourcePartMultipartImportState:
    part_count: int
    should_prompt: bool


@dataclass(frozen=True)
class SourcePartHighDensityReductionLimits:
    max_faces_per_submesh: int
    max_vertices_per_submesh: int


@dataclass(frozen=True, slots=True)
class SourcePartMultipartPromptState:
    should_prompt: bool
    part_count: int
    title: str
    message: str
    keep_separate_parts: str
    group_by_material: str
    flatten_to_one_part: str
    cancel_import: str


@dataclass(frozen=True, slots=True)
class SourcePartHighDensityPromptState:
    should_prompt: bool
    title: str
    message: str
    keep_full_quality: str
    reduce_quality: str
    cancel_import: str
    reduction_title: str


def source_part_scene_import_prompt_text() -> dict[str, str]:
    return {
        "multipart_title": "Mesh Contains Multiple Parts",
        "keep_separate_parts": "Keep Separate Parts",
        "group_by_material": "Group By Material",
        "flatten_to_one_part": "Flatten To One Part",
        "cancel_import": "Cancel Import",
        "high_density_title": "High Density Mesh Import",
        "keep_full_quality": "Keep Full Quality",
        "reduce_quality": "Reduce For Performance/Size",
        "reduction_title": "Mesh Quality Reduced",
        "reduction_intro": "Using a reduced session-only copy for this import.",
        "reduction_not_modified": "The original mesh file was not modified.",
        "cancel_status_suffix": "Geometry was unchanged.",
    }


def source_part_multipart_import_message(
    *,
    source_name: str,
    part_count: int,
    density_text: str,
) -> str:
    return (
        f"{source_name} imports as {int(part_count):,} separate mesh part(s).\n\n"
        "Keep Separate Parts lets you assign and transform each imported group individually.\n\n"
        "Group By Material keeps separate texture/material groups but reduces duplicate part rows.\n\n"
        "Flatten To One Part combines them into one Geometry source part so the whole attachment moves, scales, "
        "and assigns as one piece. Vertices, faces, and UVs are preserved, but multiple source materials collapse "
        "to one in-session material; use baked/atlased textures or route one material in Materials & Textures.\n\n"
        f"Imported mesh: {density_text}"
    )


def source_part_high_density_import_message(*, density_text: str, size_text: str) -> str:
    return (
        "This mesh has a high vertex/face count. File size alone can be misleading; a 20 MB OBJ can still be slow "
        "if it contains many dense draw parts.\n\n"
        f"Imported mesh: {density_text}"
        f"{size_text}\n\n"
        "Keep Full Quality preserves the imported geometry for final output. "
        "Reduce For Performance/Size creates a lower-density session-only copy; the source file is not changed."
    )


def source_part_reduction_result_message(
    *,
    original_vertices: int,
    original_faces: int,
    reduced_vertices: int,
    reduced_faces: int,
) -> str:
    return (
        "Using a reduced session-only copy for this import.\n\n"
        f"Before: {int(original_vertices):,} vertices, {int(original_faces):,} faces\n"
        f"After: {int(reduced_vertices):,} vertices, {int(reduced_faces):,} faces\n\n"
        "The original mesh file was not modified."
    )


def source_part_cancel_import_status(source_name: str) -> str:
    return f"Canceled {source_name}; Geometry was unchanged."


def _source_part_mesh_submeshes(mesh: object) -> tuple[object, ...]:
    return tuple(getattr(mesh, "submeshes", ()) or ())


def source_part_format_mesh_density_counts(mesh: object) -> str:
    submeshes = _source_part_mesh_submeshes(mesh)
    total_vertices = sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in submeshes)
    total_faces = sum(len(getattr(submesh, "faces", ()) or ()) for submesh in submeshes)
    largest_vertices = max((len(getattr(submesh, "vertices", ()) or ()) for submesh in submeshes), default=0)
    largest_faces = max((len(getattr(submesh, "faces", ()) or ()) for submesh in submeshes), default=0)
    return (
        f"{len(submeshes):,.0f} part(s), "
        f"{total_vertices:,.0f} vertices, {total_faces:,.0f} faces "
        f"(largest part: {largest_vertices:,.0f} vertices, {largest_faces:,.0f} faces)"
    )


def source_part_scene_import_appendable_part_count(mesh: object) -> int:
    return sum(
        1
        for submesh in _source_part_mesh_submeshes(mesh)
        if getattr(submesh, "vertices", None) and getattr(submesh, "faces", None)
    )


def source_part_multipart_import_state(mesh: object) -> SourcePartMultipartImportState:
    part_count = source_part_scene_import_appendable_part_count(mesh)
    return SourcePartMultipartImportState(
        part_count=part_count,
        should_prompt=part_count > 1,
    )


def source_part_multipart_prompt_state(*, source_name: str, mesh: object) -> SourcePartMultipartPromptState:
    import_state = source_part_multipart_import_state(mesh)
    prompt_text = source_part_scene_import_prompt_text()
    density_text = source_part_format_mesh_density_counts(mesh)
    return SourcePartMultipartPromptState(
        should_prompt=import_state.should_prompt,
        part_count=import_state.part_count,
        title=prompt_text["multipart_title"],
        message=source_part_multipart_import_message(
            source_name=source_name,
            part_count=import_state.part_count,
            density_text=density_text,
        ),
        keep_separate_parts=prompt_text["keep_separate_parts"],
        group_by_material=prompt_text["group_by_material"],
        flatten_to_one_part=prompt_text["flatten_to_one_part"],
        cancel_import=prompt_text["cancel_import"],
    )


def source_part_multipart_import_action(
    clicked_button: object,
    *,
    cancel_button: object,
    group_button: object,
    flatten_button: object,
) -> Literal["cancel", "group", "flatten", "keep"]:
    if clicked_button is cancel_button:
        return "cancel"
    if clicked_button is group_button:
        return "group"
    if clicked_button is flatten_button:
        return "flatten"
    return "keep"


def source_part_scene_import_is_high_density(mesh: object) -> bool:
    submeshes = _source_part_mesh_submeshes(mesh)
    total_vertices = sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in submeshes)
    total_faces = sum(len(getattr(submesh, "faces", ()) or ()) for submesh in submeshes)
    largest_vertices = max((len(getattr(submesh, "vertices", ()) or ()) for submesh in submeshes), default=0)
    largest_faces = max((len(getattr(submesh, "faces", ()) or ()) for submesh in submeshes), default=0)
    return (
        largest_vertices >= 55_000
        or largest_faces >= 80_000
        or total_vertices >= 120_000
        or total_faces >= 180_000
    )


def source_part_high_density_prompt_state(
    *,
    mesh: object,
    size_text: str,
) -> SourcePartHighDensityPromptState:
    prompt_text = source_part_scene_import_prompt_text()
    should_prompt = source_part_scene_import_is_high_density(mesh)
    return SourcePartHighDensityPromptState(
        should_prompt=should_prompt,
        title=prompt_text["high_density_title"],
        message=source_part_high_density_import_message(
            density_text=source_part_format_mesh_density_counts(mesh),
            size_text=size_text,
        ),
        keep_full_quality=prompt_text["keep_full_quality"],
        reduce_quality=prompt_text["reduce_quality"],
        cancel_import=prompt_text["cancel_import"],
        reduction_title=prompt_text["reduction_title"],
    )


def source_part_high_density_import_action(
    clicked_button: object,
    *,
    cancel_button: object,
    reduce_button: object,
) -> Literal["cancel", "reduce", "keep"]:
    if clicked_button is cancel_button:
        return "cancel"
    if clicked_button is reduce_button:
        return "reduce"
    return "keep"


def source_part_high_density_reduction_limits() -> SourcePartHighDensityReductionLimits:
    return SourcePartHighDensityReductionLimits(
        max_faces_per_submesh=45_000,
        max_vertices_per_submesh=55_000,
    )


__all__ = [
    "SourcePartHighDensityPromptState",
    "SourcePartHighDensityReductionLimits",
    "SourcePartMultipartImportState",
    "SourcePartMultipartPromptState",
    "source_part_cancel_import_status",
    "source_part_format_mesh_density_counts",
    "source_part_high_density_import_action",
    "source_part_high_density_import_message",
    "source_part_high_density_prompt_state",
    "source_part_high_density_reduction_limits",
    "source_part_multipart_import_action",
    "source_part_multipart_import_message",
    "source_part_multipart_import_state",
    "source_part_multipart_prompt_state",
    "source_part_reduction_result_message",
    "source_part_scene_import_appendable_part_count",
    "source_part_scene_import_is_high_density",
    "source_part_scene_import_prompt_text",
]
