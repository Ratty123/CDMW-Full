from __future__ import annotations

"""Synchronous Texture Editor file task bodies run through the UI task worker."""

from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

import numpy as np

from cdmw.models import TextureEditorDocument, TextureEditorSourceBinding
from cdmw.services.texture_editor_service import (
    TextureEditorService,
    TextureEditorNativeDdsOptions,
    TextureEditorNativeDdsResult,
    TextureEditorNativeDdsService,
)
from cdmw.ui.texture_workflow.editor_export_state import texture_editor_workspace_png_path


def copy_texture_editor_layer_pixels(
    layer_pixels: Mapping[str, np.ndarray],
) -> Dict[str, np.ndarray]:
    """Take the sole worker-owned pixel snapshot for an export request."""
    snapshot: Dict[str, np.ndarray] = {}
    for key, value in layer_pixels.items():
        pixels = value.copy()
        pixels.setflags(write=False)
        snapshot[str(key)] = pixels
    return snapshot


def create_texture_editor_source_document_task(
    source_path: Path,
    *,
    workspace_root: Path,
    binding: TextureEditorSourceBinding,
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray]]:
    document, layer_pixels, _normalized_png = TextureEditorService.create_document_from_source(
        source_path,
        workspace_root=workspace_root,
        binding=binding,
    )
    return document, layer_pixels


def load_texture_editor_project_task(
    project_path: Path,
) -> object:
    return TextureEditorService.load_project(project_path)


def save_texture_editor_project_task(
    document: TextureEditorDocument,
    layer_pixels: Mapping[str, np.ndarray],
    project_path: Path,
    *,
    floating_pixels: Optional[np.ndarray] = None,
) -> TextureEditorDocument:
    return TextureEditorService.save_project(
        document,
        layer_pixels,
        project_path,
        floating_pixels=floating_pixels,
    )


def export_texture_editor_workspace_png_task(
    document: TextureEditorDocument,
    layer_pixels: Mapping[str, np.ndarray],
    workspace_root: Path,
    suffix: str,
) -> Path:
    output_path = texture_editor_workspace_png_path(document, workspace_root, suffix)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return TextureEditorService.export_flattened_png(document, layer_pixels, output_path)


def export_texture_editor_flattened_png_task(
    document: TextureEditorDocument,
    layer_pixels: Mapping[str, np.ndarray],
    output_path: Path,
) -> Path:
    return TextureEditorService.export_flattened_png(
        document,
        layer_pixels,
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
    return TextureEditorService.export_region_png(
        document,
        layer_pixels,
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
    return TextureEditorService.export_grid_slices(
        document,
        layer_pixels,
        output_dir,
        cell_width=cell_size,
        cell_height=cell_size,
        padding=padding,
        trim_transparent=trim_transparent,
        skip_empty=skip_empty,
    )


def export_texture_editor_native_dds_task(
    document: TextureEditorDocument,
    layer_pixels: Mapping[str, np.ndarray],
    options: TextureEditorNativeDdsOptions,
) -> TextureEditorNativeDdsResult:
    return TextureEditorNativeDdsService().export_dds(
        document,
        layer_pixels,
        options,
    )


def preview_texture_editor_native_dds_task(
    document: TextureEditorDocument,
    layer_pixels: Mapping[str, np.ndarray],
    options: TextureEditorNativeDdsOptions,
) -> TextureEditorNativeDdsResult:
    return TextureEditorNativeDdsService().preview_compressed(
        document,
        layer_pixels,
        options,
    )
