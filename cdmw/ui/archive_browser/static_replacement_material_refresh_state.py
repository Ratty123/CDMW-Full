"""Material refresh debounce state helpers for static replacement."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass


@dataclass(frozen=True)
class MaterialRefreshPerformanceStatus:
    summary: str
    details: str = ""


def material_edit_refresh_initial_state() -> dict[str, object]:
    return {
        "refresh_plan": False,
        "force_plan": False,
        "refresh_preview": False,
        "reason": "",
    }


def source_material_plan_refresh_initial_state() -> dict[str, object]:
    return {"force_plan": False, "reason": ""}


def queue_material_edit_refresh_state(
    state: MutableMapping[str, object],
    *,
    refresh_plan: bool = False,
    force_plan: bool = False,
    refresh_preview: bool = True,
    reason: str = "material edit",
) -> str:
    normalized_reason = str(reason or "material edit").strip() or "material edit"
    state["refresh_plan"] = bool(state.get("refresh_plan")) or bool(refresh_plan)
    state["force_plan"] = bool(state.get("force_plan")) or bool(force_plan)
    state["refresh_preview"] = bool(state.get("refresh_preview")) or bool(refresh_preview)
    state["reason"] = normalized_reason
    return normalized_reason


def take_material_edit_refresh_state(state: MutableMapping[str, object]) -> dict[str, object]:
    payload = {
        "refresh_plan": bool(state.get("refresh_plan")),
        "force_plan": bool(state.get("force_plan")),
        "refresh_preview": bool(state.get("refresh_preview")),
        "reason": str(state.get("reason") or "material edit").strip() or "material edit",
    }
    state["refresh_plan"] = False
    state["force_plan"] = False
    state["refresh_preview"] = False
    state["reason"] = ""
    return payload


def queue_source_material_plan_refresh_state(
    state: MutableMapping[str, object],
    *,
    force_plan: bool = False,
    reason: str = "material edit",
) -> str:
    normalized_reason = str(reason or "material edit").strip() or "material edit"
    state["force_plan"] = bool(state.get("force_plan")) or bool(force_plan)
    state["reason"] = normalized_reason
    return normalized_reason


def take_source_material_plan_refresh_state(state: MutableMapping[str, object]) -> dict[str, object]:
    payload = {
        "force_plan": bool(state.get("force_plan")),
        "reason": str(state.get("reason") or "material edit").strip() or "material edit",
    }
    state["force_plan"] = False
    state["reason"] = ""
    return payload


def material_edit_refresh_interval_ms() -> int:
    return 150


def source_material_plan_refresh_interval_ms() -> int:
    return 260


def manual_profile_commit_interval_ms() -> int:
    """Debounce for Material Authority manual control edits.

    A slider drag emits one ``valueChanged`` per step, and each one persists the
    whole profile and restarts the exact DDS resolve. Coalescing on the same
    scale as the other material paths keeps a drag to one commit.
    """
    return 150


def material_edit_refresh_queued_performance(reason: str) -> MaterialRefreshPerformanceStatus:
    reason_text = str(reason or "material edit").strip() or "material edit"
    return MaterialRefreshPerformanceStatus(
        summary=f"Preview update queued: {reason_text}.",
        details="Material edits are debounced so role and slider changes do not rebuild preview per click.",
    )


def material_edit_refresh_queued_progress_message(reason: str) -> str:
    reason_text = str(reason or "material edit").strip() or "material edit"
    return f"Preview update queued - {reason_text}."


def material_edit_refresh_running_performance(reason: str) -> MaterialRefreshPerformanceStatus:
    reason_text = str(reason or "material edit").strip() or "material edit"
    return MaterialRefreshPerformanceStatus(
        summary=f"Refreshing material preview: {reason_text}.",
        details="Queued material edit is being applied after input settled.",
    )


def material_edit_refresh_running_progress_message(reason: str) -> str:
    reason_text = str(reason or "material edit").strip() or "material edit"
    return f"Refreshing material preview - {reason_text}."


__all__ = [
    "MaterialRefreshPerformanceStatus",
    "material_edit_refresh_initial_state",
    "material_edit_refresh_interval_ms",
    "material_edit_refresh_queued_performance",
    "material_edit_refresh_queued_progress_message",
    "material_edit_refresh_running_performance",
    "material_edit_refresh_running_progress_message",
    "manual_profile_commit_interval_ms",
    "queue_material_edit_refresh_state",
    "queue_source_material_plan_refresh_state",
    "source_material_plan_refresh_initial_state",
    "source_material_plan_refresh_interval_ms",
    "take_material_edit_refresh_state",
    "take_source_material_plan_refresh_state",
]
