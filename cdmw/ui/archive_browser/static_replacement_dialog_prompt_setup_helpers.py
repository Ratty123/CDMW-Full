"""Small setup helpers for the static replacement prompt."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import SimpleNamespace
import threading
from typing import Any

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.mesh_workflow_service import refresh_parsed_mesh_totals
from cdmw.ui.archive_browser.static_replacement_geometry_math import (
    Bounds3,
    transformed_vertices_for_work_area,
)


def static_replacement_prompt_mesh_vertices(mesh: object) -> list[tuple[float, float, float]]:
    return [
        vertex
        for submesh in tuple(getattr(mesh, "submeshes", ()) or ())
        for vertex in tuple(getattr(submesh, "vertices", ()) or ())
    ]


def static_replacement_prompt_mesh_bounds(
    mesh: object,
    *,
    stop_event: threading.Event | None = None,
) -> Bounds3 | None:
    minimum = [float("inf"), float("inf"), float("inf")]
    maximum = [float("-inf"), float("-inf"), float("-inf")]
    found = False
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        for index, vertex in enumerate(getattr(submesh, "vertices", ()) or ()):
            if index % 4096 == 0:
                raise_if_cancelled(stop_event, "Static replacement preflight stopped by user.")
            found = True
            for axis in range(3):
                value = float(vertex[axis])
                minimum[axis] = min(minimum[axis], value)
                maximum[axis] = max(maximum[axis], value)
    if not found:
        return None
    return (tuple(minimum), tuple(maximum))  # type: ignore[return-value]


def apply_static_replacement_work_area_fit(
    mesh: object,
    fit: object,
    *,
    stop_event: threading.Event | None = None,
) -> None:
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        raise_if_cancelled(stop_event, "Static replacement preflight stopped by user.")
        vertices = tuple(getattr(submesh, "vertices", ()) or ())
        if not vertices:
            continue
        submesh.vertices = transformed_vertices_for_work_area(vertices, fit, stop_event=stop_event)
        submesh.vertex_count = len(submesh.vertices)
        submesh.face_count = len(getattr(submesh, "faces", ()) or ())
    refresh_parsed_mesh_totals(mesh)


def build_static_replacement_prompt_sidecar_context(
    *,
    entry: object,
    alignment_startup_step: Callable[[str], object],
    alignment_startup_text: Mapping[str, str],
    alignment_texture_lookup_indexes: Callable[[], tuple[object, object]],
    extract_archive_model_sidecar_texture_references: Callable[..., tuple[object, object, object, object]],
    record_runtime_event: Callable[..., object] | None = None,
    dialog_title: str = "",
    modify_original_clone_mode: bool = False,
) -> SimpleNamespace:
    sidecar_bindings: object = ()
    sidecar_text_values: tuple[str, ...] = ()
    sidecar_texts_by_normalized_path: dict[str, tuple[str, ...]] = {}
    sidecar_texts_by_basename: dict[str, tuple[str, ...]] = {}
    try:
        alignment_startup_step(alignment_startup_text["material_sidecar"])
        (
            _texture_entries_by_normalized_path_for_alignment,
            texture_entries_by_basename_for_alignment,
        ) = alignment_texture_lookup_indexes()
        (
            sidecar_bindings,
            _sidecar_paths,
            sidecar_texts_by_normalized_path,
            sidecar_texts_by_basename,
        ) = extract_archive_model_sidecar_texture_references(
            entry,
            archive_entries_by_basename=texture_entries_by_basename_for_alignment,
        )
        deduped_sidecar_texts: list[str] = []
        seen_sidecar_texts: set[str] = set()
        for sidecar_index, values in enumerate(sidecar_texts_by_normalized_path.values()):
            if sidecar_index and sidecar_index % 24 == 0:
                alignment_startup_step(alignment_startup_text["sidecar_texture_references"])
            for text in values:
                normalized_text = str(text or "")
                if not normalized_text.strip() or normalized_text in seen_sidecar_texts:
                    continue
                seen_sidecar_texts.add(normalized_text)
                deduped_sidecar_texts.append(normalized_text)
        sidecar_text_values = tuple(deduped_sidecar_texts)
    except Exception as exc:
        # Event-recorded best-effort path: missing sidecar metadata must not block mesh setup.
        if callable(record_runtime_event):
            record_runtime_event(
                "mesh_alignment_sidecar_texture_lookup_failed",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                error=str(exc),
                error_type=type(exc).__name__,
                modify_original_clone=modify_original_clone_mode,
            )
    return SimpleNamespace(
        sidecar_bindings=sidecar_bindings,
        sidecar_text_values=sidecar_text_values,
        sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
        sidecar_texts_by_basename=sidecar_texts_by_basename,
    )


__all__ = [
    "apply_static_replacement_work_area_fit",
    "build_static_replacement_prompt_sidecar_context",
    "static_replacement_prompt_mesh_bounds",
    "static_replacement_prompt_mesh_vertices",
]
