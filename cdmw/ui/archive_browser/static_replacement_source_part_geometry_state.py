"""Selected source-part geometry action state helpers for static replacement."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from cdmw.ui.archive_browser.static_replacement_geometry_math import (
    AppendedPartWorkAreaFit,
    appended_part_work_area_fit,
    center_offset_for_bounds,
    fit_uniform_scale_for_bounds,
    vertices_for_source_indices,
)


@dataclass(frozen=True, slots=True)
class SourcePartPairActionState:
    source_index: int
    target_index: int
    available: bool


@dataclass(frozen=True, slots=True)
class SourcePartWorkAreaFitState:
    source_indices: tuple[int, ...]
    fit: AppendedPartWorkAreaFit | None
    placement_note: str

    @property
    def should_apply(self) -> bool:
        return bool(self.source_indices and self.fit is not None)


@dataclass(frozen=True, slots=True)
class SourcePartFitSizeState:
    source_index: int
    target_index: int
    uniform_scale: float | None

    @property
    def available(self) -> bool:
        return self.uniform_scale is not None


@dataclass(frozen=True, slots=True)
class SourcePartCenterOnTargetState:
    source_index: int
    target_index: int
    offset: tuple[float, float, float] | None

    @property
    def available(self) -> bool:
        return self.offset is not None


def source_part_pair_action_available(
    *,
    source_index: int,
    target_index: int,
    source_count: int,
    target_count: int,
) -> bool:
    return source_part_pair_action_state(
        source_index=source_index,
        target_index=target_index,
        source_count=source_count,
        target_count=target_count,
    ).available


def source_part_pair_action_state(
    *,
    source_index: int,
    target_index: int,
    source_count: int,
    target_count: int,
) -> SourcePartPairActionState:
    try:
        normalized_source = int(source_index)
        normalized_target = int(target_index)
        normalized_source_count = int(source_count)
        normalized_target_count = int(target_count)
    except (TypeError, ValueError):
        return SourcePartPairActionState(source_index=-1, target_index=-1, available=False)
    available = (
        0 <= normalized_source < max(0, normalized_source_count)
        and 0 <= normalized_target < max(0, normalized_target_count)
    )
    return SourcePartPairActionState(
        source_index=normalized_source if available else -1,
        target_index=normalized_target if available else -1,
        available=bool(available),
    )


def source_part_valid_indices(source_indices: Sequence[int], *, source_count: int) -> tuple[int, ...]:
    try:
        normalized_count = max(0, int(source_count))
    except (TypeError, ValueError):
        normalized_count = 0
    normalized: list[int] = []
    for raw_index in tuple(source_indices or ()):
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < normalized_count and index not in normalized:
            normalized.append(index)
    return tuple(normalized)


def source_part_appended_work_area_fit_state(
    *,
    source_indices: Sequence[int],
    source_count: int,
    replacement_mesh: object,
    reference_vertices: Sequence[tuple[float, float, float]],
) -> SourcePartWorkAreaFitState:
    normalized_indices = source_part_valid_indices(source_indices, source_count=source_count)
    if not normalized_indices:
        return SourcePartWorkAreaFitState(source_indices=(), fit=None, placement_note="")
    source_vertices = vertices_for_source_indices(replacement_mesh, normalized_indices)
    fit = appended_part_work_area_fit(source_vertices, reference_vertices)
    return SourcePartWorkAreaFitState(
        source_indices=normalized_indices,
        fit=fit,
        placement_note=", ".join(fit.notes) if fit is not None else "",
    )


def source_part_fit_size_state(
    *,
    source_index: int,
    target_index: int,
    replacement_mesh: object,
    original_mesh: object,
) -> SourcePartFitSizeState:
    source_submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ())
    target_submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    action_state = source_part_pair_action_state(
        source_index=source_index,
        target_index=target_index,
        source_count=len(source_submeshes),
        target_count=len(target_submeshes),
    )
    if not action_state.available:
        return SourcePartFitSizeState(source_index=-1, target_index=-1, uniform_scale=None)
    source_vertices = list(getattr(source_submeshes[action_state.source_index], "vertices", ()) or ())
    target_vertices = list(getattr(target_submeshes[action_state.target_index], "vertices", ()) or ())
    return SourcePartFitSizeState(
        source_index=action_state.source_index,
        target_index=action_state.target_index,
        uniform_scale=fit_uniform_scale_for_bounds(source_vertices, target_vertices),
    )


def source_part_center_on_target_state(
    *,
    source_index: int,
    target_index: int,
    replacement_mesh: object,
    original_mesh: object,
) -> SourcePartCenterOnTargetState:
    source_submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ())
    target_submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    action_state = source_part_pair_action_state(
        source_index=source_index,
        target_index=target_index,
        source_count=len(source_submeshes),
        target_count=len(target_submeshes),
    )
    if not action_state.available:
        return SourcePartCenterOnTargetState(source_index=-1, target_index=-1, offset=None)
    source_vertices = list(getattr(source_submeshes[action_state.source_index], "vertices", ()) or ())
    target_vertices = list(getattr(target_submeshes[action_state.target_index], "vertices", ()) or ())
    return SourcePartCenterOnTargetState(
        source_index=action_state.source_index,
        target_index=action_state.target_index,
        offset=center_offset_for_bounds(source_vertices, target_vertices),
    )


def source_part_nudge_delta(axis: str, step: float, direction: float) -> tuple[float, float, float]:
    normalized_axis = str(axis or "").strip().lower()
    delta = float(step) * float(direction)
    return (
        delta if normalized_axis == "x" else 0.0,
        delta if normalized_axis == "y" else 0.0,
        delta if normalized_axis == "z" else 0.0,
    )


__all__ = [
    "SourcePartCenterOnTargetState",
    "SourcePartFitSizeState",
    "SourcePartPairActionState",
    "SourcePartWorkAreaFitState",
    "source_part_appended_work_area_fit_state",
    "source_part_center_on_target_state",
    "source_part_fit_size_state",
    "source_part_nudge_delta",
    "source_part_pair_action_available",
    "source_part_pair_action_state",
    "source_part_valid_indices",
]
