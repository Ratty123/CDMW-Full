from __future__ import annotations

"""Synchronous Texture Editor file task bodies run through the UI task worker."""

from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

import numpy as np

from cdmw.core.texture_editor import (
    create_texture_editor_document_from_source,
    export_texture_editor_flattened_png,
    export_texture_editor_grid_slices,
    export_texture_editor_region_png,
    load_texture_editor_project,
    save_texture_editor_project,
)
from cdmw.models import TextureEditorDocument, TextureEditorSourceBinding
from cdmw.ui.texture_workflow.editor_export_state import texture_editor_workspace_png_path


def copy_texture_editor_layer_pixels(
    layer_pixels: Mapping[str, np.ndarray],
) -> Dict[str, np.ndarray]:
    return {key: value.copy() for key, value in layer_pixels.items()}


def create_texture_editor_source_document_task(
    source_path: Path,
    *,
    texconv_path: Optional[Path],
    workspace_root: Path,
    binding: TextureEditorSourceBinding,
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray]]:
    document, layer_pixels, _normalized_png = create_texture_editor_document_from_source(
        source_path,
        texconv_path=texconv_path,
        workspace_root=workspace_root,
        binding=binding,
    )
    return document, layer_pixels


def load_texture_editor_project_task(
    project_path: Path,
) -> object:
    return load_texture_editor_project(project_path)


def save_texture_editor_project_task(
    document: TextureEditorDocument,
    layer_pixels: Mapping[str, np.ndarray],
    project_path: Path,
    *,
    floating_pixels: Optional[np.ndarray] = None,
) -> TextureEditorDocument:
    return save_texture_editor_project(
        document,
        copy_texture_editor_layer_pixels(layer_pixels),
        project_path,
        floating_pixels=None if floating_pixels is None else floating_pixels.copy(),
    )


def export_texture_editor_workspace_png_task(
    document: TextureEditorDocument,
    layer_pixels: Mapping[str, np.ndarray],
    workspace_root: Path,
    suffix: str,
) -> Path:
    output_path = texture_editor_workspace_png_path(document, workspace_root, suffix)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return export_texture_editor_flattened_png(document, copy_texture_editor_layer_pixels(layer_pixels), output_path)


def export_texture_editor_flattened_png_task(
    document: TextureEditorDocument,
    layer_pixels: Mapping[str, np.ndarray],
    output_path: Path,
) -> Path:
    return export_texture_editor_flattened_png(
        document,
        copy_texture_editor_layer_pixels(layer_pixels),
        output_path,
    )


def export_texture_editor_region_png_task(
    document: TextureEditorDocument,
    layer_pixels: Mapping[str, np.ndarray],
    output_path: Path,
    bounds: Tuple[int, int, int, int],
    *,
    padding: int,
    trim_transparent: bool,
) -> Path:
    return export_texture_editor_region_png(
        document,
        copy_texture_editor_layer_pixels(layer_pixels),
        output_path,
        bounds,
        padding=padding,
        trim_transparent=trim_transparent,
    )


def export_texture_editor_grid_slices_task(
    document: TextureEditorDocument,
    layer_pixels: Mapping[str, np.ndarray],
    output_dir: Path,
    *,
    cell_size: int,
    padding: int,
    trim_transparent: bool,
    skip_empty: bool,
) -> object:
    return export_texture_editor_grid_slices(
        document,
        copy_texture_editor_layer_pixels(layer_pixels),
        output_dir,
        cell_width=cell_size,
        cell_height=cell_size,
        padding=padding,
        trim_transparent=trim_transparent,
        skip_empty=skip_empty,
    )
