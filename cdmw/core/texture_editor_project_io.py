from __future__ import annotations

import base64
import dataclasses
import json
import os
import shutil
import uuid
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from cdmw.core.texture_editor import (
    _PROJECT_VERSION,
    _VISIBLE_TEXTURE_TYPES,
    _load_rgba_array,
    _new_layer_id,
    _safe_slug,
    save_rgba_array_png,
)
from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.core.upscale_profiles import infer_texture_semantics, is_technical_texture_type
from cdmw.domain.workspace import workspace_paths
from cdmw.models import (
    DdsInfo,
    TextureEditorAdjustmentLayer,
    TextureEditorDocument,
    TextureEditorFloatingSelection,
    TextureEditorLayer,
    TextureEditorSelection,
    TextureEditorSourceBinding,
)


def make_texture_editor_workspace_root(base_dir: Path) -> Path:
    root = workspace_paths(base_dir)["texture_editor_workspace_root"]
    root.mkdir(parents=True, exist_ok=True)
    return root

def build_texture_editor_document_root(workspace_root: Path, title: str) -> Path:
    safe_title = _safe_slug(title or "texture_editor")
    root = workspace_root / f"{safe_title}_{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True, exist_ok=True)
    return root

def normalize_texture_editor_source_to_png(
    source_path: Path,
    *,
    output_dir: Path,
    output_stem: str = "",
) -> Path:
    resolved = source_path.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = resolved.suffix.lower()
    stem = output_stem.strip() or resolved.stem
    output_path = output_dir / f"{stem}.png"
    if suffix == ".dds":
        preview_path = ensure_dds_display_preview_png(
            resolved,
            dds_info=parse_dds(resolved),
            max_dimension=0,
        )
        if Path(preview_path).expanduser().resolve() != output_path.expanduser().resolve():
            output_path.parent.mkdir(parents=True, exist_ok=True)
            import shutil

            shutil.copy2(preview_path, output_path)
        return output_path
    if suffix not in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tga"}:
        raise ValueError(f"Unsupported texture source for Texture Editor: {resolved.suffix}")
    with Image.open(resolved) as image:
        image.convert("RGBA").save(output_path, format="PNG")
    return output_path

def derive_texture_editor_binding(
    source_path: Path,
    *,
    binding: Optional[TextureEditorSourceBinding] = None,
) -> Tuple[TextureEditorSourceBinding, Optional[DdsInfo]]:
    resolved = source_path.expanduser().resolve()
    source_binding = dataclasses.replace(binding) if binding is not None else TextureEditorSourceBinding()
    source_binding.source_path = str(resolved)
    if not source_binding.source_identity_path:
        source_binding.source_identity_path = str(resolved)
    if not source_binding.display_name:
        source_binding.display_name = resolved.name
    dds_info: Optional[DdsInfo] = None
    original_dds = Path(source_binding.original_dds_path).expanduser() if source_binding.original_dds_path else None
    try:
        if original_dds and original_dds.exists():
            dds_info = parse_dds(original_dds)
            source_binding.original_dds_format = dds_info.dds_format
    except Exception:
        dds_info = None

    semantic_path = source_binding.relative_path or source_binding.archive_relative_path or resolved.name
    semantic = infer_texture_semantics(
        semantic_path,
        sidecar_texts=tuple(str(text or "") for text in getattr(source_binding, "semantic_sidecar_texts", ()) if text),
        original_dds_format=source_binding.original_dds_format,
    )
    source_binding.texture_type = semantic.texture_type
    source_binding.semantic_subtype = semantic.semantic_subtype
    if is_technical_texture_type(semantic.texture_type):
        source_binding.technical_warning = (
            f"This looks like a technical texture ({semantic.texture_type}/{semantic.semantic_subtype}). "
            "Painting or recoloring it may break the intended data."
        )
    elif semantic.texture_type not in _VISIBLE_TEXTURE_TYPES:
        source_binding.technical_warning = (
            f"This texture is classified as {semantic.texture_type}/{semantic.semantic_subtype}. "
            "Texture Editor is primarily intended for visible-color texture work."
        )
    else:
        source_binding.technical_warning = ""
    return source_binding, dds_info

def create_texture_editor_document_from_source(
    source_path: Path,
    *,
    workspace_root: Path,
    binding: Optional[TextureEditorSourceBinding] = None,
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray], Path]:
    resolved = source_path.expanduser().resolve()
    binding, _dds_info = derive_texture_editor_binding(resolved, binding=binding)
    document_root = build_texture_editor_document_root(workspace_root, resolved.stem)
    normalized_png = normalize_texture_editor_source_to_png(
        resolved,
        output_dir=document_root / "normalized",
        output_stem=resolved.stem,
    )
    pixels = _load_rgba_array(normalized_png)
    height, width = pixels.shape[:2]
    layer = TextureEditorLayer(
        layer_id=_new_layer_id(),
        name="Base Layer",
        relative_png_path="layers/base.png",
        visible=True,
        opacity=100,
        thumbnail_cache_key=uuid.uuid4().hex,
    )
    document = TextureEditorDocument(
        title=resolved.stem,
        width=int(width),
        height=int(height),
        workspace_root=document_root,
        active_layer_id=layer.layer_id,
        layers=(layer,),
        source_binding=binding,
        technical_warning=binding.technical_warning,
    )
    layer_pixels = {layer.layer_id: pixels}
    return document, layer_pixels, normalized_png

def _selection_to_dict(selection: TextureEditorSelection) -> Dict[str, object]:
    return {
        "mode": selection.mode,
        "rect": list(selection.rect) if selection.rect else None,
        "polygon_points": [list(point) for point in selection.polygon_points],
        "mask_polygons": [[list(point) for point in polygon] for polygon in selection.mask_polygons],
        "mask_png_base64": base64.b64encode(selection.mask_png_blob).decode("ascii") if selection.mask_png_blob else "",
        "inverted": bool(selection.inverted),
        "feather_radius": int(selection.feather_radius),
    }

def _selection_from_dict(data: Dict[str, object]) -> TextureEditorSelection:
    rect_value = data.get("rect")
    rect: Optional[Tuple[int, int, int, int]] = None
    if isinstance(rect_value, list) and len(rect_value) == 4:
        rect = tuple(int(value) for value in rect_value)  # type: ignore[assignment]
    polygon_points_raw = data.get("polygon_points")
    polygon_points: Tuple[Tuple[float, float], ...] = ()
    if isinstance(polygon_points_raw, list):
        polygon_points = tuple(
            (float(point[0]), float(point[1]))
            for point in polygon_points_raw
            if isinstance(point, list) and len(point) == 2
        )
    mask_polygons_raw = data.get("mask_polygons")
    mask_polygons: Tuple[Tuple[Tuple[float, float], ...], ...] = ()
    if isinstance(mask_polygons_raw, list):
        polygons: List[Tuple[Tuple[float, float], ...]] = []
        for polygon in mask_polygons_raw:
            if not isinstance(polygon, list):
                continue
            points = tuple(
                (float(point[0]), float(point[1]))
                for point in polygon
                if isinstance(point, list) and len(point) == 2
            )
            if len(points) >= 3:
                polygons.append(points)
        mask_polygons = tuple(polygons)
    mask_png_blob = b""
    mask_png_base64 = data.get("mask_png_base64")
    if isinstance(mask_png_base64, str) and mask_png_base64.strip():
        try:
            mask_png_blob = base64.b64decode(mask_png_base64)
        except Exception:
            mask_png_blob = b""
    return TextureEditorSelection(
        mode=str(data.get("mode", "none") or "none"),
        rect=rect,
        polygon_points=polygon_points,
        mask_polygons=mask_polygons,
        mask_png_blob=mask_png_blob,
        inverted=bool(data.get("inverted", False)),
        feather_radius=max(0, int(data.get("feather_radius", 0) or 0)),
    )

def _floating_selection_to_dict(floating: Optional[TextureEditorFloatingSelection]) -> Optional[Dict[str, object]]:
    if floating is None:
        return None
    return {
        "source_layer_id": floating.source_layer_id,
        "label": floating.label,
        "bounds": list(floating.bounds),
        "offset_x": int(floating.offset_x),
        "offset_y": int(floating.offset_y),
        "scale_x": float(floating.scale_x),
        "scale_y": float(floating.scale_y),
        "rotation_degrees": float(floating.rotation_degrees),
        "flip_x": bool(floating.flip_x),
        "flip_y": bool(floating.flip_y),
        "paste_mode": str(floating.paste_mode or "in_place"),
        "committed": bool(floating.committed),
    }

def _floating_selection_from_dict(data: Optional[Dict[str, object]]) -> Optional[TextureEditorFloatingSelection]:
    if not isinstance(data, dict):
        return None
    bounds_raw = data.get("bounds")
    bounds = (0, 0, 0, 0)
    if isinstance(bounds_raw, list) and len(bounds_raw) == 4:
        bounds = tuple(int(value) for value in bounds_raw)  # type: ignore[assignment]
    return TextureEditorFloatingSelection(
        source_layer_id=str(data.get("source_layer_id", "")),
        label=str(data.get("label", "")),
        bounds=bounds,
        offset_x=int(data.get("offset_x", 0) or 0),
        offset_y=int(data.get("offset_y", 0) or 0),
        scale_x=float(data.get("scale_x", 1.0) or 1.0),
        scale_y=float(data.get("scale_y", 1.0) or 1.0),
        rotation_degrees=float(data.get("rotation_degrees", 0.0) or 0.0),
        flip_x=bool(data.get("flip_x", False)),
        flip_y=bool(data.get("flip_y", False)),
        paste_mode=str(data.get("paste_mode", "in_place") or "in_place"),
        committed=bool(data.get("committed", True)),
    )

def _adjustment_layer_to_dict(layer: TextureEditorAdjustmentLayer) -> Dict[str, object]:
    return {
        "layer_id": str(layer.layer_id),
        "name": str(layer.name),
        "adjustment_type": str(layer.adjustment_type),
        "enabled": bool(layer.enabled),
        "opacity": int(layer.opacity),
        "parameters": {
            str(key): (
                str(value)
                if isinstance(value, str)
                else float(value)
            )
            for key, value in layer.parameters.items()
        },
        "mask_layer_id": str(layer.mask_layer_id),
        "revision": int(layer.revision),
    }

def _adjustment_layer_from_dict(data: Dict[str, object]) -> TextureEditorAdjustmentLayer:
    parameters_raw = data.get("parameters")
    parameters: Dict[str, object] = {}
    if isinstance(parameters_raw, dict):
        for key, value in parameters_raw.items():
            if isinstance(value, str):
                parameters[str(key)] = value
                continue
            try:
                parameters[str(key)] = float(value)
            except Exception:
                continue
    return TextureEditorAdjustmentLayer(
        layer_id=str(data.get("layer_id", "")),
        name=str(data.get("name", "Adjustment")),
        adjustment_type=str(data.get("adjustment_type", "levels") or "levels"),
        enabled=bool(data.get("enabled", True)),
        opacity=int(data.get("opacity", 100) or 100),
        parameters=parameters,
        mask_layer_id=str(data.get("mask_layer_id", "")),
        revision=int(data.get("revision", 0) or 0),
    )


def _texture_editor_assets_dir(project_path: Path) -> Path:
    assets_root = project_path.with_suffix("")
    return assets_root.parent / f"{assets_root.name}_assets"


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _replace_path(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _write_texture_editor_project(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    project_path: Path,
    assets_dir: Path,
    *,
    floating_pixels: Optional[np.ndarray],
) -> Tuple[TextureEditorLayer, ...]:
    layers_dir = assets_dir / "layers"
    layers_dir.mkdir(parents=True)

    saved_layers: List[TextureEditorLayer] = []
    saved_masks: Dict[str, str] = {}
    for index, layer in enumerate(document.layers, start=1):
        pixels = layer_pixels.get(layer.layer_id)
        if pixels is None:
            continue
        file_name = f"{index:02d}_{_safe_slug(layer.name)}.png"
        relative_png = PurePosixPath("layers") / file_name
        save_rgba_array_png(pixels, layers_dir / file_name)
        saved_layers.append(dataclasses.replace(layer, relative_png_path=relative_png.as_posix()))
        if layer.mask_layer_id and layer.mask_layer_id in layer_pixels:
            masks_dir = assets_dir / "masks"
            masks_dir.mkdir(parents=True, exist_ok=True)
            mask_name = f"{index:02d}_{_safe_slug(layer.name)}_mask.png"
            save_rgba_array_png(layer_pixels[layer.mask_layer_id], masks_dir / mask_name)
            saved_masks[layer.mask_layer_id] = (PurePosixPath("masks") / mask_name).as_posix()

    payload = {
        "version": _PROJECT_VERSION,
        "title": document.title,
        "width": document.width,
        "height": document.height,
        "active_layer_id": document.active_layer_id,
        "technical_warning": document.technical_warning,
        "last_flattened_png_path": document.last_flattened_png_path,
        "source_binding": dataclasses.asdict(document.source_binding),
        "selection": _selection_to_dict(document.selection),
        "floating_selection": _floating_selection_to_dict(document.floating_selection),
        "adjustment_layers": [_adjustment_layer_to_dict(layer) for layer in document.adjustment_layers],
        "composite_revision": int(document.composite_revision),
        "quick_mask_enabled": bool(document.quick_mask_enabled),
        "edit_red_channel": bool(document.edit_red_channel),
        "edit_green_channel": bool(document.edit_green_channel),
        "edit_blue_channel": bool(document.edit_blue_channel),
        "edit_alpha_channel": bool(document.edit_alpha_channel),
        "masks": saved_masks,
        "floating_pixels_path": "",
        "layers": [dataclasses.asdict(layer) for layer in saved_layers],
    }
    if document.floating_selection is not None and floating_pixels is not None:
        floating_dir = assets_dir / "floating"
        floating_dir.mkdir(parents=True)
        floating_name = "floating_selection.png"
        save_rgba_array_png(floating_pixels, floating_dir / floating_name)
        payload["floating_pixels_path"] = (PurePosixPath("floating") / floating_name).as_posix()
    project_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return tuple(saved_layers)


def _restore_texture_editor_project(
    project_path: Path,
    assets_dir: Path,
    backup_project_path: Path,
    backup_assets_dir: Path,
    *,
    had_project: bool,
    had_assets: bool,
    project_backup_ready: bool,
) -> List[BaseException]:
    errors: List[BaseException] = []
    try:
        if had_assets and _path_exists(backup_assets_dir):
            _remove_path(assets_dir)
            _replace_path(backup_assets_dir, assets_dir)
        elif not had_assets:
            _remove_path(assets_dir)
    except BaseException as exc:
        errors.append(exc)
    try:
        if had_project and project_backup_ready:
            _replace_path(backup_project_path, project_path)
        elif not had_project:
            _remove_path(project_path)
        else:
            _remove_path(backup_project_path)
    except BaseException as exc:
        errors.append(exc)
    return errors


def _publish_texture_editor_project(
    staged_project_path: Path,
    staged_assets_dir: Path,
    project_path: Path,
    assets_dir: Path,
    backup_project_path: Path,
    backup_assets_dir: Path,
) -> None:
    had_project = _path_exists(project_path)
    had_assets = _path_exists(assets_dir)
    project_backup_ready = False
    try:
        if had_project:
            shutil.copy2(project_path, backup_project_path)
            project_backup_ready = True
        if had_assets:
            _replace_path(assets_dir, backup_assets_dir)
        _replace_path(staged_assets_dir, assets_dir)
        _replace_path(staged_project_path, project_path)
    except BaseException:
        rollback_errors = _restore_texture_editor_project(
            project_path,
            assets_dir,
            backup_project_path,
            backup_assets_dir,
            had_project=had_project,
            had_assets=had_assets,
            project_backup_ready=project_backup_ready,
        )
        if rollback_errors:
            recovery_paths = ", ".join(
                str(path)
                for path in (backup_project_path, backup_assets_dir)
                if _path_exists(path)
            )
            raise RuntimeError(
                "Texture Editor project save failed and rollback was incomplete. "
                f"Recovery data was retained at: {recovery_paths or 'no recoverable backup path'}"
            ) from rollback_errors[0]
        raise
    for backup_path in (backup_project_path, backup_assets_dir):
        try:
            _remove_path(backup_path)
        except OSError:
            pass


def save_texture_editor_project(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    project_path: Path,
    *,
    floating_pixels: Optional[np.ndarray] = None,
) -> TextureEditorDocument:
    project_path = project_path.expanduser().resolve()
    project_path.parent.mkdir(parents=True, exist_ok=True)
    assets_dir = _texture_editor_assets_dir(project_path)
    transaction_id = uuid.uuid4().hex
    staged_project_path = project_path.parent / f".{project_path.name}.{transaction_id}.tmp.json"
    staged_assets_dir = _texture_editor_assets_dir(staged_project_path)
    backup_project_path = project_path.parent / f".{project_path.name}.{transaction_id}.backup"
    backup_assets_dir = assets_dir.parent / f".{assets_dir.name}.{transaction_id}.backup"
    try:
        saved_layers = _write_texture_editor_project(
            document,
            layer_pixels,
            staged_project_path,
            staged_assets_dir,
            floating_pixels=floating_pixels,
        )
        load_texture_editor_project(staged_project_path)
        _publish_texture_editor_project(
            staged_project_path,
            staged_assets_dir,
            project_path,
            assets_dir,
            backup_project_path,
            backup_assets_dir,
        )
    finally:
        _remove_path(staged_project_path)
        _remove_path(staged_assets_dir)
    return dataclasses.replace(
        document,
        project_path=project_path,
        layers=saved_layers,
    )

def load_texture_editor_project(
    project_path: Path,
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray], Optional[np.ndarray]]:
    resolved = project_path.expanduser().resolve()
    data = json.loads(resolved.read_text(encoding="utf-8"))
    assets_dir = _texture_editor_assets_dir(resolved)
    layers: List[TextureEditorLayer] = []
    layer_pixels: Dict[str, np.ndarray] = {}
    missing_assets: List[str] = []
    for layer_data in data.get("layers", []):
        layer = TextureEditorLayer(
            layer_id=str(layer_data.get("layer_id", "")),
            name=str(layer_data.get("name", "Layer")),
            relative_png_path=str(layer_data.get("relative_png_path", "")),
            visible=bool(layer_data.get("visible", True)),
            opacity=int(layer_data.get("opacity", 100)),
            blend_mode=str(layer_data.get("blend_mode", "normal") or "normal"),
            offset_x=int(layer_data.get("offset_x", 0) or 0),
            offset_y=int(layer_data.get("offset_y", 0) or 0),
            locked=bool(layer_data.get("locked", False)),
            alpha_locked=bool(layer_data.get("alpha_locked", False)),
            mask_layer_id=str(layer_data.get("mask_layer_id", "")),
            mask_enabled=bool(layer_data.get("mask_enabled", True)),
            revision=int(layer_data.get("revision", 0) or 0),
            thumbnail_cache_key=str(layer_data.get("thumbnail_cache_key", "")),
        )
        png_path = assets_dir / Path(layer.relative_png_path)
        if png_path.exists():
            layer_pixels[layer.layer_id] = _load_rgba_array(png_path)
            layers.append(layer)
        else:
            missing_assets.append(str(png_path))
    masks_raw = data.get("masks") or {}
    if isinstance(masks_raw, dict):
        for mask_layer_id, relative_path in masks_raw.items():
            mask_path = assets_dir / Path(str(relative_path))
            if mask_path.exists():
                try:
                    layer_pixels[str(mask_layer_id)] = _load_rgba_array(mask_path)
                except Exception:
                    missing_assets.append(str(mask_path))
            else:
                missing_assets.append(str(mask_path))
    floating_pixels: Optional[np.ndarray] = None
    floating_pixels_path = str(data.get("floating_pixels_path", "") or "").strip()
    if floating_pixels_path:
        floating_path = assets_dir / Path(floating_pixels_path)
        if floating_path.exists():
            floating_pixels = _load_rgba_array(floating_path)
        else:
            missing_assets.append(str(floating_path))
    elif data.get("floating_selection"):
        missing_assets.append("<floating selection pixels>")
    if missing_assets:
        sample = ", ".join(missing_assets[:3])
        if len(missing_assets) > 3:
            sample += ", ..."
        raise FileNotFoundError(f"Texture Editor project is missing required asset files: {sample}")
    source_binding_data = dict(data.get("source_binding") or {})
    source_binding_data["mesh_submesh_indices"] = tuple(
        int(index) for index in tuple(source_binding_data.get("mesh_submesh_indices") or ())
    )
    source_binding = TextureEditorSourceBinding(**source_binding_data)
    document = TextureEditorDocument(
        title=str(data.get("title", resolved.stem)),
        width=int(data.get("width", 0)),
        height=int(data.get("height", 0)),
        project_path=resolved,
        workspace_root=assets_dir,
        active_layer_id=str(data.get("active_layer_id", "")),
        layers=tuple(layers),
        source_binding=source_binding,
        selection=_selection_from_dict(data.get("selection") or {}),
        floating_selection=_floating_selection_from_dict(data.get("floating_selection") or None),
        adjustment_layers=tuple(
            _adjustment_layer_from_dict(item)
            for item in (data.get("adjustment_layers") or [])
            if isinstance(item, dict)
        ),
        technical_warning=str(data.get("technical_warning", "")),
        last_flattened_png_path=str(data.get("last_flattened_png_path", "")),
        composite_revision=int(data.get("composite_revision", 0) or 0),
        quick_mask_enabled=bool(data.get("quick_mask_enabled", False)),
        edit_red_channel=bool(data.get("edit_red_channel", True)),
        edit_green_channel=bool(data.get("edit_green_channel", True)),
        edit_blue_channel=bool(data.get("edit_blue_channel", True)),
        edit_alpha_channel=bool(data.get("edit_alpha_channel", True)),
    )
    return document, layer_pixels, floating_pixels
