"""Archive preview preparation boundary."""

from __future__ import annotations

from typing import Any


def ensure_archive_preview_source(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_media_preview import ensure_archive_preview_source as owner

    return owner(*args, **kwargs)


def build_archive_preview_result(*args: Any, **kwargs: Any) -> Any:
    from cdmw.core.archive_preview_result_builder import build_archive_preview_result as owner

    return owner(*args, **kwargs)


def clone_archive_preview_model(preview_model: object, *, strip_images: bool = False) -> object:
    """Copy mutable preview records while sharing geometry and optional decoded images."""
    import dataclasses

    from cdmw.models import ModelPreviewData, ModelPreviewMesh, PREVIEW_MESH_IMAGE_FIELD_NAMES

    if not isinstance(preview_model, ModelPreviewData):
        return preview_model
    cloned_meshes: list[object] = []
    for mesh in getattr(preview_model, "meshes", []) or []:
        if isinstance(mesh, ModelPreviewMesh):
            mesh_values = {
                field_info.name: getattr(mesh, field_info.name)
                for field_info in dataclasses.fields(ModelPreviewMesh)
            }
            if strip_images:
                for image_field in PREVIEW_MESH_IMAGE_FIELD_NAMES:
                    mesh_values[image_field] = None
            cloned_meshes.append(ModelPreviewMesh(**mesh_values))
        else:
            cloned_meshes.append(mesh)
    return ModelPreviewData(
        **{
            field_info.name: cloned_meshes if field_info.name == "meshes" else getattr(preview_model, field_info.name)
            for field_info in dataclasses.fields(ModelPreviewData)
        }
    )


__all__ = ["build_archive_preview_result", "clone_archive_preview_model", "ensure_archive_preview_source"]
