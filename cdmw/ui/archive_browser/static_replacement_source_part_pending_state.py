"""Selected source-part apply/rebuild pending state helpers."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass


@dataclass(frozen=True)
class SourcePartsPendingPresentation:
    apply_button_enabled: bool
    label_text: str
    label_visible: bool
    performance_summary: str = ""
    performance_details: str = ""


def _source_parts_reason(reason: str, default: str) -> str:
    return str(reason or default).strip() or default


def source_parts_apply_initial_state() -> dict[str, object]:
    return {
        "pending": False,
        "reason": "",
        "preview_rebuild_pending": False,
        "preview_rebuild_reason": "",
    }


def source_parts_mark_apply_pending(state: MutableMapping[str, object], reason: str) -> str:
    reason_text = _source_parts_reason(reason, "part changes")
    state["pending"] = True
    state["reason"] = reason_text
    state["preview_rebuild_pending"] = False
    state["preview_rebuild_reason"] = ""
    return reason_text


def source_parts_clear_apply_pending(state: MutableMapping[str, object]) -> None:
    state["pending"] = False
    state["reason"] = ""
    state["preview_rebuild_pending"] = False
    state["preview_rebuild_reason"] = ""


def source_parts_mark_preview_rebuild_pending(state: MutableMapping[str, object], reason: str) -> str:
    reason_text = _source_parts_reason(reason, "source-part changes")
    state["pending"] = False
    state["reason"] = ""
    state["preview_rebuild_pending"] = True
    state["preview_rebuild_reason"] = reason_text
    return reason_text


def source_parts_apply_pending_presentation(reason: str) -> SourcePartsPendingPresentation:
    reason_text = _source_parts_reason(reason, "part changes")
    return SourcePartsPendingPresentation(
        apply_button_enabled=True,
        label_text=f"Pending: {reason_text}. Preview still shows the previous build until Apply.",
        label_visible=True,
        performance_summary="Part changes pending. Deleted/unchecked parts may still render until Apply.",
        performance_details=reason_text,
    )


def source_parts_clear_apply_pending_presentation() -> SourcePartsPendingPresentation:
    return SourcePartsPendingPresentation(
        apply_button_enabled=False,
        label_text="No unapplied source-part changes.",
        label_visible=False,
    )


def source_parts_preview_rebuild_pending_presentation(reason: str) -> SourcePartsPendingPresentation:
    reason_text = _source_parts_reason(reason, "source-part changes")
    return SourcePartsPendingPresentation(
        apply_button_enabled=False,
        label_text=(
            f"Applied: {reason_text}. Rebuilding preview; old D3D11 geometry may remain visible until reload finishes."
        ),
        label_visible=True,
        performance_summary="Source-part changes applied. Rebuilding preview package.",
        performance_details=f"{reason_text}\nOld D3D11 geometry may remain visible until reload finishes.",
    )


def source_parts_selection_pending_presentation(reason: str) -> SourcePartsPendingPresentation:
    reason_text = _source_parts_reason(reason, "part changes")
    return SourcePartsPendingPresentation(
        apply_button_enabled=True,
        label_text="",
        label_visible=False,
        performance_summary="Part changes pending. Press Apply to rebuild preview.",
        performance_details=f"Pending {reason_text}; selection update did not rebuild geometry.",
    )


def source_parts_preview_rebuild_pending(state: MutableMapping[str, object]) -> bool:
    return bool(state.get("preview_rebuild_pending"))


__all__ = [
    "SourcePartsPendingPresentation",
    "source_parts_apply_initial_state",
    "source_parts_apply_pending_presentation",
    "source_parts_clear_apply_pending",
    "source_parts_clear_apply_pending_presentation",
    "source_parts_mark_apply_pending",
    "source_parts_mark_preview_rebuild_pending",
    "source_parts_preview_rebuild_pending",
    "source_parts_preview_rebuild_pending_presentation",
    "source_parts_selection_pending_presentation",
]
