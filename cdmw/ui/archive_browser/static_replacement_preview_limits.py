"""Pure preview face-limit rules for static replacement previews."""

from __future__ import annotations

import math
from collections.abc import Sequence


def adaptive_alignment_preview_face_limit(
    submesh_count: int,
    *,
    target_total_faces: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        count = max(1, int(submesh_count))
    except (TypeError, ValueError):
        count = 1
    per_submesh = int(math.ceil(max(1, int(target_total_faces)) / float(count)))
    return max(int(minimum), min(int(maximum), per_submesh))


def alignment_preview_source_face_limit_for_counts(
    submesh_face_counts: Sequence[int],
    *,
    modify_original_clone_mode: bool,
    appended_geometry: int,
    d3d11_normal_active: bool,
    interactive: bool,
) -> int:
    counts = tuple(int(count or 0) for count in submesh_face_counts if int(count or 0) > 0)
    total_faces = sum(counts)
    render_submesh_count = max(1, len(counts))
    if total_faces <= 80_000:
        return 0
    appended_geometry = int(appended_geometry or 0)
    if modify_original_clone_mode and appended_geometry <= 0:
        return adaptive_alignment_preview_face_limit(
            render_submesh_count,
            target_total_faces=35_000,
            minimum=2_000,
            maximum=10_000,
        )
    if d3d11_normal_active and total_faces >= 45_000:
        return adaptive_alignment_preview_face_limit(
            render_submesh_count,
            target_total_faces=35_000,
            minimum=2_000,
            maximum=10_000,
        )
    if interactive and total_faces >= 120_000:
        return adaptive_alignment_preview_face_limit(
            render_submesh_count,
            target_total_faces=45_000,
            minimum=2_500,
            maximum=12_000,
        )
    if modify_original_clone_mode and appended_geometry > 0:
        if total_faces >= 120_000:
            return 3_000
        if total_faces >= 40_000:
            return 5_000
        if total_faces >= 15_000:
            return 8_000
    if total_faces >= 120_000:
        return adaptive_alignment_preview_face_limit(
            render_submesh_count,
            target_total_faces=50_000,
            minimum=2_500,
            maximum=14_000,
        )
    if total_faces >= 250_000:
        return adaptive_alignment_preview_face_limit(
            render_submesh_count,
            target_total_faces=75_000,
            minimum=4_000,
            maximum=22_000,
        )
    if total_faces >= 100_000:
        return adaptive_alignment_preview_face_limit(
            render_submesh_count,
            target_total_faces=80_000,
            minimum=6_000,
            maximum=30_000,
        )
    if total_faces >= 40_000:
        return adaptive_alignment_preview_face_limit(
            render_submesh_count,
            target_total_faces=70_000,
            minimum=10_000,
            maximum=35_000,
        )
    return 0


def alignment_preview_selected_source_face_limit_for_total(
    total_faces: int,
    *,
    selected_requested: bool,
    interactive: bool,
    fallback_limit: int,
) -> int:
    total_faces = int(total_faces or 0)
    if interactive and total_faces >= 120_000:
        return 18_000 if selected_requested else 8_000
    if selected_requested:
        if total_faces <= 80_000:
            return 0
        if total_faces >= 250_000:
            return 35_000
        if total_faces >= 100_000:
            return 45_000
        if total_faces >= 80_000:
            return 55_000
    if total_faces >= 250_000:
        return 8_000
    if total_faces >= 100_000:
        return 12_000
    return int(fallback_limit or 0)


def alignment_preview_background_source_face_limit_for_total(
    total_faces: int,
    *,
    interactive: bool,
    fallback_limit: int,
) -> int:
    total_faces = int(total_faces or 0)
    if interactive and total_faces >= 120_000:
        return 2_000
    if total_faces >= 250_000:
        return 2_500
    if total_faces >= 100_000:
        return 3_500
    if total_faces >= 40_000:
        return 5_000
    return int(fallback_limit or 0)


def alignment_preview_requested_source_indices(mesh: object, source_indices: Sequence[int]) -> tuple[int, ...]:
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    requested: list[int] = []
    for raw_index in tuple(source_indices or ()):
        try:
            source_index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= source_index < len(submeshes):
            requested.append(source_index)
    return tuple(requested)


def alignment_preview_source_face_total(mesh: object, source_indices: Sequence[int]) -> int:
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    total = 0
    for raw_index in tuple(source_indices or ()):
        try:
            source_index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= source_index < len(submeshes):
            total += len(getattr(submeshes[source_index], "faces", ()) or ())
    return total


__all__ = [
    "adaptive_alignment_preview_face_limit",
    "alignment_preview_background_source_face_limit_for_total",
    "alignment_preview_requested_source_indices",
    "alignment_preview_selected_source_face_limit_for_total",
    "alignment_preview_source_face_total",
    "alignment_preview_source_face_limit_for_counts",
]
