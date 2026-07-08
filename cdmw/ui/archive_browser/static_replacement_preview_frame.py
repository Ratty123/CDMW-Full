"""Placement-frame metadata helpers for static replacement previews."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from dataclasses import dataclass

from cdmw.models import ModelPreviewData


@dataclass(frozen=True, slots=True)
class AlignmentPreviewFrame:
    frame_kind: str = "original_pac_frame"
    source_path: str = ""
    normalization_center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    normalization_scale: float = 1.0
    grid_origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    grid_normal_axis: str = "y"
    grid_y: float = 0.0
    preserve_original_materials: bool = True


def _finite_float(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _tuple3(value: object, default: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    try:
        raw = tuple(value)  # type: ignore[arg-type]
        result = (_finite_float(raw[0]), _finite_float(raw[1]), _finite_float(raw[2]))
    except (TypeError, ValueError, IndexError, OverflowError):
        return default
    return result


def _normalization_scale(value: object) -> float:
    scale = _finite_float(value, 1.0)
    return scale if abs(scale) > 1e-8 else 1.0


def original_frame_grid_y(
    normalization_center: Sequence[float],
    normalization_scale: float,
) -> float:
    center = _tuple3(normalization_center)
    scale = _normalization_scale(normalization_scale)
    return (0.0 - center[1]) * scale


def alignment_preview_frame_from_model(
    model: object,
    *,
    frame_kind: str = "original_pac_frame",
    source_path: str = "",
    preserve_original_materials: bool = True,
) -> AlignmentPreviewFrame:
    center = _tuple3(getattr(model, "normalization_center", (0.0, 0.0, 0.0)))
    scale = _normalization_scale(getattr(model, "normalization_scale", 1.0))
    has_explicit_frame = any(
        str(getattr(model, attr_name, "") or "").strip()
        for attr_name in ("preview_frame_kind", "preview_grid_mode", "preview_material_parity_mode")
    )
    existing_grid_y = getattr(model, "preview_grid_y", None) if has_explicit_frame else None
    grid_y = _finite_float(existing_grid_y, original_frame_grid_y(center, scale))
    grid_origin = _tuple3(getattr(model, "preview_grid_origin", (0.0, grid_y, 0.0)), (0.0, grid_y, 0.0))
    source = str(source_path or getattr(model, "preview_frame_source_path", "") or getattr(model, "path", "") or "")
    kind = str(getattr(model, "preview_frame_kind", "") or frame_kind or "original_pac_frame")
    return AlignmentPreviewFrame(
        frame_kind=kind,
        source_path=source,
        normalization_center=center,
        normalization_scale=scale,
        grid_origin=grid_origin,
        grid_normal_axis=str(getattr(model, "preview_grid_normal_axis", "") or "y"),
        grid_y=grid_y,
        preserve_original_materials=bool(preserve_original_materials),
    )


def apply_alignment_preview_frame(
    model: object,
    frame: AlignmentPreviewFrame,
    *,
    grid_mode: str = "original_frame",
    material_parity_mode: str = "archive_preview",
    reference_tint_mode: str = "overlay_only",
) -> object:
    if not isinstance(model, ModelPreviewData):
        return model
    return dataclasses.replace(
        model,
        normalization_center=frame.normalization_center,
        normalization_scale=frame.normalization_scale,
        preview_frame_kind=frame.frame_kind,
        preview_frame_source_path=frame.source_path,
        preview_grid_origin=frame.grid_origin,
        preview_grid_normal_axis=frame.grid_normal_axis,
        preview_grid_y=frame.grid_y,
        preview_grid_mode=str(grid_mode or "original_frame"),
        preview_material_parity_mode=str(material_parity_mode or "archive_preview"),
        preview_original_materials_preserved=bool(frame.preserve_original_materials),
        preview_reference_tint_mode=str(reference_tint_mode or "overlay_only"),
    )


__all__ = [
    "AlignmentPreviewFrame",
    "alignment_preview_frame_from_model",
    "apply_alignment_preview_frame",
    "original_frame_grid_y",
]
