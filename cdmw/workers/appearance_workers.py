"""Cancellable request operations for appearance review planning."""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from cdmw.core.appearance_composite import (
    AppearanceCompositePreviewPlan,
    AppearanceSinglePacSwapPlan,
    build_appearance_composite_preview_plan,
    build_appearance_single_pac_swap_plan,
)
from cdmw.core.archive import read_archive_entry_data, try_decode_text_like_archive_data
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry


@dataclass(frozen=True, slots=True)
class AppearanceExactMatchRequest:
    donor_model_entry: ArchiveEntry
    app_entries: tuple[ArchiveEntry, ...]
    request_id: int = 0


@dataclass(frozen=True, slots=True)
class AppearanceExactMatchResult:
    request_id: int
    donor_model_entry: ArchiveEntry
    candidates: tuple[ArchiveEntry, ...]


@dataclass(frozen=True, slots=True)
class AppearanceCompositePlanRequest:
    target_app_entry: ArchiveEntry
    donor_model_entry: ArchiveEntry
    archive_entries: tuple[ArchiveEntry, ...]
    path_index: Mapping[str, Sequence[ArchiveEntry]]
    basename_index: Mapping[str, Sequence[ArchiveEntry]]
    request_id: int = 0


@dataclass(frozen=True, slots=True)
class AppearanceCompositePlanResult:
    request_id: int
    request: AppearanceCompositePlanRequest
    plan: AppearanceCompositePreviewPlan


@dataclass(frozen=True, slots=True)
class AppearanceSwapPlanRequest:
    target_app_entry: ArchiveEntry
    donor_model_entry: ArchiveEntry
    archive_entries: tuple[ArchiveEntry, ...]
    target_component_index: int
    target_model_entry: ArchiveEntry | None
    allow_experimental_mismatch: bool
    path_index: Mapping[str, Sequence[ArchiveEntry]]
    basename_index: Mapping[str, Sequence[ArchiveEntry]]
    request_id: int = 0


@dataclass(frozen=True, slots=True)
class AppearanceSwapPlanResult:
    request_id: int
    request: AppearanceSwapPlanRequest
    plan: AppearanceSinglePacSwapPlan


def appearance_swap_exact_app_match(
    model_entry: ArchiveEntry,
    app_entry: ArchiveEntry,
    *,
    stop_event: threading.Event | None = None,
) -> bool:
    model_stem = PurePosixPath(str(model_entry.path or "").replace("\\", "/")).stem.strip().casefold()
    if not model_stem:
        return False
    raise_if_cancelled(stop_event, "Appearance context search cancelled.")
    try:
        data, _decompressed, _note = read_archive_entry_data(app_entry)
        text = (try_decode_text_like_archive_data(data) or data.decode("utf-8-sig", errors="ignore")).casefold()
    except Exception:
        raise_if_cancelled(stop_event, "Appearance context search cancelled.")
        return False
    raise_if_cancelled(stop_event, "Appearance context search cancelled.")
    pattern = re.compile(r"\bname\s*=\s*['\"]" + re.escape(model_stem) + r"['\"]", flags=re.IGNORECASE)
    return bool(pattern.search(text))


def run_appearance_exact_match(
    request: AppearanceExactMatchRequest,
    *,
    stop_event: threading.Event | None = None,
) -> AppearanceExactMatchResult:
    matches: list[ArchiveEntry] = []
    for candidate in request.app_entries:
        raise_if_cancelled(stop_event, "Appearance context search cancelled.")
        if str(candidate.extension or "").casefold() != ".app_xml":
            continue
        if appearance_swap_exact_app_match(request.donor_model_entry, candidate, stop_event=stop_event):
            matches.append(candidate)
    return AppearanceExactMatchResult(request.request_id, request.donor_model_entry, tuple(matches))


def run_appearance_composite_plan(
    request: AppearanceCompositePlanRequest,
    *,
    stop_event: threading.Event | None = None,
) -> AppearanceCompositePlanResult:
    raise_if_cancelled(stop_event, "Appearance composite planning cancelled.")
    plan = build_appearance_composite_preview_plan(
        request.target_app_entry,
        request.archive_entries,
        appearance_entry=request.target_app_entry,
        path_index=request.path_index,
        basename_index=request.basename_index,
    )
    raise_if_cancelled(stop_event, "Appearance composite planning cancelled.")
    return AppearanceCompositePlanResult(request.request_id, request, plan)


def run_appearance_swap_plan(
    request: AppearanceSwapPlanRequest,
    *,
    stop_event: threading.Event | None = None,
) -> AppearanceSwapPlanResult:
    raise_if_cancelled(stop_event, "Appearance swap planning cancelled.")
    plan = build_appearance_single_pac_swap_plan(
        request.target_app_entry,
        request.donor_model_entry,
        request.archive_entries,
        target_component_index=request.target_component_index,
        target_model_entry=request.target_model_entry,
        allow_experimental_mismatch=request.allow_experimental_mismatch,
        path_index=request.path_index,
        basename_index=request.basename_index,
    )
    raise_if_cancelled(stop_event, "Appearance swap planning cancelled.")
    return AppearanceSwapPlanResult(request.request_id, request, plan)


__all__ = [
    "AppearanceCompositePlanRequest",
    "AppearanceCompositePlanResult",
    "AppearanceExactMatchRequest",
    "AppearanceExactMatchResult",
    "AppearanceSwapPlanRequest",
    "AppearanceSwapPlanResult",
    "appearance_swap_exact_app_match",
    "run_appearance_composite_plan",
    "run_appearance_exact_match",
    "run_appearance_swap_plan",
]
