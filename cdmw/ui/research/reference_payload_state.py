"""Reference and target payload state rules for the Research tab."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Mapping, Optional

from cdmw.core.research import MaterialTextureReferenceRow

__all__ = [
    "current_ui_constraint_related_paths",
    "normalize_relative_path",
    "normalize_research_target_key",
    "ReferenceResolveCompleteState",
    "ReferenceResolveStartState",
    "UIConstraintScanCompleteState",
    "UIConstraintScanStartState",
    "reference_resolve_already_running_status_text",
    "reference_resolve_complete_state",
    "reference_resolve_missing_target_status_text",
    "reference_resolve_start_state",
    "reference_row_review_enabled",
    "reference_review_incomplete_status_text",
    "reference_review_missing_status_text",
    "reference_target_load_state",
    "ReferenceTargetLoadState",
    "resolved_extract_request_state",
    "resolved_extract_paths",
    "ResolvedExtractRequestState",
    "review_reference_text_search_payload",
    "ui_constraint_initial_status_text",
    "ui_constraint_refresh_preserved_status_text",
    "ui_constraint_refresh_stale_status_text",
    "ui_constraint_scan_complete_state",
    "ui_constraint_scan_start_state",
]


@dataclass(frozen=True, slots=True)
class ReferenceTargetLoadState:
    normalized_target: str
    status_text: str
    is_error: bool
    should_focus_archive_browser: bool


@dataclass(frozen=True, slots=True)
class ResolvedExtractRequestState:
    extract_paths: list[str]
    status_text: str
    is_error: bool


@dataclass(frozen=True, slots=True)
class ReferenceResolveStartState:
    status_text: str
    user_status_text: str


@dataclass(frozen=True, slots=True)
class ReferenceResolveCompleteState:
    status_text: str
    user_status_text: str


@dataclass(frozen=True, slots=True)
class UIConstraintScanStartState:
    status_text: str
    user_status_text: str


@dataclass(frozen=True, slots=True)
class UIConstraintScanCompleteState:
    status_text: str
    user_status_text: str


def normalize_relative_path(relative_path: str) -> str:
    text = str(relative_path).strip().replace("\\", "/")
    if not text:
        return ""
    return PurePosixPath(text).as_posix()


def normalize_research_target_key(value: object) -> str:
    return str(value or "").strip().replace("\\", "/")


def current_ui_constraint_related_paths(research_payload: Mapping[str, object]) -> list[str]:
    rows = research_payload.get("ui_constraint_rows", [])
    return [
        row.related_path
        for row in rows
        if isinstance(row, MaterialTextureReferenceRow) and str(row.related_path or "").strip()
    ] if isinstance(rows, list) else []


def ui_constraint_initial_status_text() -> str:
    return "Not scanned for the current archive set yet. Run this when you specifically want UI/XML rect evidence."


def ui_constraint_refresh_preserved_status_text() -> str:
    return "Using the latest UI rect scan for the current archive set."


def ui_constraint_refresh_stale_status_text() -> str:
    return "Not scanned for the current archive set yet. Run 'Scan UI Rect References' when you need UI/XML rect evidence."


def ui_constraint_scan_start_state() -> UIConstraintScanStartState:
    return UIConstraintScanStartState(
        status_text="Preparing UI/XML rect scan across archive text references...",
        user_status_text="Scanning archive UI/XML references for explicit GetRect evidence...",
    )


def ui_constraint_scan_complete_state(row_count: int) -> UIConstraintScanCompleteState:
    status_text = f"UI rect scan complete. Found {row_count:,} explicit UI/XML rect reference row(s)."
    return UIConstraintScanCompleteState(status_text=status_text, user_status_text=status_text)


def resolved_extract_paths(reference_payload: Mapping[str, object]) -> list[str]:
    extract_paths = reference_payload.get("extract_paths", [])
    return [str(path) for path in extract_paths if isinstance(path, str)] if isinstance(extract_paths, list) else []


def reference_resolve_missing_target_status_text() -> str:
    return "Select or enter an archive path first."


def reference_resolve_start_state(target_path: str) -> ReferenceResolveStartState:
    return ReferenceResolveStartState(
        status_text=f"Resolving archive relationships for {target_path}",
        user_status_text=f"Resolving archive relationships for {target_path}...",
    )


def reference_resolve_already_running_status_text(target_path: str) -> str:
    return f"Reference resolve already running. Will use {target_path} next."


def reference_resolve_complete_state(reference_payload: Mapping[str, object]) -> ReferenceResolveCompleteState:
    stats = reference_payload.get("reference_stats", {})
    if isinstance(stats, dict):
        mode = str(stats.get("mode", ""))
        searched_count = int(stats.get("searched_count", 0))
        unreadable_count = int(stats.get("unreadable_count", 0))
    else:
        mode = ""
        searched_count = 0
        unreadable_count = 0
    sidecar_rows = reference_payload.get("sidecar_rows", [])
    reference_rows = reference_payload.get("reference_rows", [])
    sidecar_count = len(sidecar_rows) if isinstance(sidecar_rows, list) else 0
    reference_count = len(reference_rows) if isinstance(reference_rows, list) else 0
    mode_label = "material -> textures" if mode == "outbound" else "textures <- materials"
    return ReferenceResolveCompleteState(
        status_text=(
            f"Resolved {reference_count:,} reference row(s), {sidecar_count:,} sidecar candidate(s), "
            f"searched {searched_count:,} text file(s), skipped {unreadable_count:,}. Mode: {mode_label}."
        ),
        user_status_text="Reference resolver ready.",
    )


def reference_review_missing_status_text() -> str:
    return "Select a reference result first."


def reference_review_incomplete_status_text() -> str:
    return "The selected reference row does not include enough information for Text Search review."


def reference_target_load_state(target_path: str) -> ReferenceTargetLoadState:
    normalized = normalize_research_target_key(target_path)
    if not normalized:
        return ReferenceTargetLoadState(
            normalized_target="",
            status_text=(
                "No archive file is currently selected. Use the Archive Files panel in Research, "
                "or go to Archive Browser and select a file first."
            ),
            is_error=True,
            should_focus_archive_browser=True,
        )
    return ReferenceTargetLoadState(
        normalized_target=normalized,
        status_text=f"Loaded resolver target: {normalized}",
        is_error=False,
        should_focus_archive_browser=False,
    )


def resolved_extract_request_state(reference_payload: Mapping[str, object]) -> ResolvedExtractRequestState:
    extract_paths = resolved_extract_paths(reference_payload)
    if not extract_paths:
        return ResolvedExtractRequestState(
            extract_paths=[],
            status_text="Resolve a reference target first.",
            is_error=True,
        )
    return ResolvedExtractRequestState(
        extract_paths=extract_paths,
        status_text="Extracting resolved related set...",
        is_error=False,
    )


def review_reference_text_search_payload(row: object) -> Optional[tuple[str, str]]:
    if not isinstance(row, MaterialTextureReferenceRow):
        return None
    source_path = normalize_research_target_key(row.source_path)
    highlight_query = PurePosixPath(normalize_research_target_key(row.related_path)).name
    if not source_path or not highlight_query:
        return None
    return source_path, highlight_query


def reference_row_review_enabled(row: object) -> bool:
    return (
        isinstance(row, MaterialTextureReferenceRow)
        and bool(str(row.source_path or "").strip())
        and bool(str(row.related_path or "").strip())
    )
