"""Placement-scene composition and progressive material upgrades for New Item preview."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.mesh_workflow_service import ParsedMesh
from cdmw.ui.new_item.model_import import ModelPlacement

__all__ = ["PlacementScene", "upgrade_item_preview_package_materials"]


@dataclass
class PlacementScene:
    """Reference, editable, and optional character roles for the resident viewport."""

    template: Any
    model: Any
    placement: ModelPlacement = field(default_factory=ModelPlacement)
    model_bounds: Any = None
    model_origin: Any = None
    character: Any = None


def as_parsed_mesh(item: Any) -> ParsedMesh:
    if getattr(item, "meshes", None) is not None and not hasattr(item, "submeshes"):
        from cdmw.services.mesh_rust_preview_cache import parsed_mesh_from_model_preview

        return parsed_mesh_from_model_preview(item)
    return item


def placement_reference_mesh(template: Any, character: Any) -> Optional[ParsedMesh]:
    """Merge immutable template and character context into the helper's reference role."""

    meshes = [mesh for mesh in (template, character) if mesh is not None]
    if not meshes:
        return None
    if len(meshes) == 1:
        return meshes[0]
    from cdmw.services.mesh_workflow_service import clone_mesh_for_editing, refresh_mesh_totals

    merged = clone_mesh_for_editing(meshes[0])
    for mesh in meshes[1:]:
        merged.submeshes.extend(clone_mesh_for_editing(mesh).submeshes)
    vertices = [
        vertex
        for submesh in tuple(merged.submeshes or ())
        for vertex in tuple(submesh.vertices or ())
    ]
    if vertices:
        merged.bbox_min = tuple(min(float(vertex[axis]) for vertex in vertices) for axis in range(3))
        merged.bbox_max = tuple(max(float(vertex[axis]) for vertex in vertices) for axis in range(3))
    refresh_mesh_totals(merged)
    return merged


def prepare_preview_model(
    item: Any,
    *,
    render_settings: object | None,
    stop_event: threading.Event,
) -> Any:
    if getattr(item, "meshes", None) is None or hasattr(item, "submeshes"):
        return item
    from cdmw.services.preview_rendering_service import prepare_model_preview

    prepared, _prepared_payload = prepare_model_preview(
        item,
        render_settings=render_settings,
        stop_event=stop_event,
        enable_material_combiner=False,
    )
    return prepared


def upgrade_item_preview_package_materials(
    geometry_package: Path,
    source: Any,
    *,
    output_root: Path,
    stop_event: threading.Event,
    render_settings: object | None = None,
) -> Path:
    """Attach canonical materials to a copied geometry package without re-exporting it."""

    from cdmw.services.mesh_rust_preview_package import build_rust_preview_package

    root = Path(output_root).resolve(strict=False)
    base = Path(geometry_package).resolve(strict=False)
    try:
        relative = base.relative_to(root)
    except ValueError as exc:
        raise ValueError("The progressive geometry package is outside this preview workspace.") from exc
    if len(relative.parts) != 1 or not relative.name.startswith("package_"):
        raise ValueError("The progressive geometry package is not workspace-owned.")
    if stop_event.is_set():
        raise RunCancelled("Item preview material upgrade cancelled.")
    item = source(stop_event) if callable(source) else source
    if not isinstance(item, PlacementScene):
        raise TypeError("A progressive material upgrade requires a placement scene.")
    model = as_parsed_mesh(
        prepare_preview_model(item.model, render_settings=render_settings, stop_event=stop_event)
    )
    reference = (
        as_parsed_mesh(
            prepare_preview_model(item.template, render_settings=render_settings, stop_event=stop_event)
        )
        if item.template is not None
        else None
    )
    character = (
        as_parsed_mesh(
            prepare_preview_model(item.character, render_settings=render_settings, stop_event=stop_event)
        )
        if item.character is not None
        else None
    )
    reference = placement_reference_mesh(reference, character)
    target = root / f"package_{time.time_ns()}_materials"
    package = build_rust_preview_package(
        model,
        output_package_dir=target,
        reference_mesh=reference,
        comparison_mode="overlay",
        interaction_profile="static_replacement",
        scene_transform=item.placement.build_transform(origin=item.model_origin),
        cancelled=stop_event.is_set,
        include_material_resources=True,
    )
    return Path(package.package_dir)
