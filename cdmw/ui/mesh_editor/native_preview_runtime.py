"""Standalone native preview runtime helpers for Mesh Editor."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt

from cdmw.constants import MODEL_PREVIEW_BACKGROUND_COLOR, MODEL_PREVIEW_TEXT_COLOR
from cdmw.models import ModelPreviewData, ModelPreviewRenderSettings, PreparedModelPreviewData
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.rendering.native_d3d11_host import find_native_d3d11_host
from cdmw.rendering.native_preview_package_writer import write_isolated_d3d11_preview_package
from cdmw.ui.mesh_editor.native_preview_payloads import mesh_to_native_preview


def mesh_editor_native_preview_data(
    mesh: ParsedMesh,
    *,
    reference_mesh: ParsedMesh | None = None,
) -> PreparedModelPreviewData:
    prepared = mesh_to_native_preview(mesh)
    if reference_mesh is None:
        return prepared
    reference = mesh_to_native_preview(reference_mesh)
    reference_batches = tuple(
        dataclasses.replace(batch, editor_role="original_reference", editor_editable=False)
        for batch in tuple(reference.batches or ())
    )
    edited_batches = tuple(
        dataclasses.replace(batch, editor_role="replacement_preview", editor_editable=True)
        for batch in tuple(prepared.batches or ())
    )
    return dataclasses.replace(
        prepared,
        mesh_count=len(reference_batches) + len(edited_batches),
        vertex_count=int(reference.vertex_count or 0) + int(prepared.vertex_count or 0),
        face_count=int(reference.face_count or 0) + int(prepared.face_count or 0),
        batches=reference_batches + edited_batches,
    )


def mesh_editor_write_native_preview_package(
    mesh: ParsedMesh,
    *,
    reference_mesh: ParsedMesh | None = None,
    output_root: Optional[Path] = None,
    render_settings: Optional[ModelPreviewRenderSettings] = None,
    use_textures: bool = False,
    high_quality_textures: bool = False,
    backend: str = "d3d11",
    display_mode: str = "replacement_only",
    skeleton_overlay: object | None = None,
) -> Path:
    if not isinstance(mesh, ParsedMesh):
        raise TypeError("mesh must be ParsedMesh")
    model = ModelPreviewData(path=str(mesh.path or "mesh_editor.pac"), physics_overlay=skeleton_overlay)
    return write_isolated_d3d11_preview_package(
        model,
        mesh_editor_native_preview_data(mesh, reference_mesh=reference_mesh),
        output_root=output_root,
        render_settings=render_settings,
        use_textures=bool(use_textures),
        high_quality_textures=bool(high_quality_textures),
        backend=str(backend or "d3d11"),
        display_mode=str(display_mode or "replacement_only"),
    )


def mesh_editor_native_preview_command(
    package_dir: Path,
    status_file: Path,
    *,
    host_widget: object | None = None,
    theme_background: str = MODEL_PREVIEW_BACKGROUND_COLOR,
    theme_text: str = MODEL_PREVIEW_TEXT_COLOR,
    crash_dir: Path | None = None,
    diagnostic_log: Path | None = None,
) -> tuple[str, list[str]]:
    host_binary = find_native_d3d11_host()
    if host_binary is None:
        raise FileNotFoundError(
            "Native D3D11 preview host is not built. Build native/cdmw_d3d11_preview or set CDMW_D3D11_PREVIEW_BIN."
        )
    arguments = [
        "--backend",
        "d3d11",
        "--preview-package",
        str(Path(package_dir)),
        "--status-file",
        str(Path(status_file)),
        "--theme-background",
        str(theme_background or MODEL_PREVIEW_BACKGROUND_COLOR),
        "--theme-text",
        str(theme_text or MODEL_PREVIEW_TEXT_COLOR),
    ]
    if crash_dir is not None:
        arguments.extend(["--crash-dir", str(Path(crash_dir))])
    if diagnostic_log is not None:
        arguments.extend(["--diagnostic-log", str(Path(diagnostic_log))])
    parent_hwnd = _host_widget_hwnd(host_widget)
    if parent_hwnd:
        arguments.extend(["--parent-hwnd", str(parent_hwnd)])
    return str(host_binary), arguments


def _host_widget_hwnd(host_widget: object | None) -> int:
    if host_widget is None:
        return 0
    try:
        set_attribute = getattr(host_widget, "setAttribute")
        win_id = getattr(host_widget, "winId")
    except Exception:
        return 0
    try:
        set_attribute(Qt.WA_NativeWindow, True)
        return int(win_id())
    except Exception:
        return 0


__all__ = [
    "mesh_editor_native_preview_data",
    "mesh_editor_native_preview_command",
    "mesh_editor_write_native_preview_package",
]
