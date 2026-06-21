"""Presentation state for archive mesh import setup dialogs."""

from __future__ import annotations


def mesh_import_file_dialog_title() -> str:
    return "Select Mesh File"


def mesh_import_setup_dialog_title() -> str:
    return "Mesh Import Setup"


def mesh_import_replacement_mode_log(suffix: object) -> str:
    return f"{str(suffix or '').upper().lstrip('.')} imports use Mesh Replacement mode."


def direct_source_model_swap_unexpected_payload_status() -> str:
    return "Direct source model swap finished with an unexpected result payload."


def direct_source_model_swap_incomplete_payload_status() -> str:
    return "Direct source model swap finished with an incomplete result payload."


def direct_source_model_swap_written_status(target_basename: object, package_root: object) -> str:
    return f"Wrote direct source model swap for {target_basename}: {package_root}"


def direct_source_model_swap_task_status(target_basename: object) -> str:
    return f"Writing direct source model swap for {target_basename}..."


def pending_in_game_mesh_swap_target_status(entry_basename: object) -> str:
    return (
        f"In-game mesh swap target set: {entry_basename}. "
        "Select the source mesh in Archive Browser, then click Use as Swap Source."
    )


def pending_in_game_mesh_swap_cancelled_status() -> str:
    return "Cancelled the pending in-game mesh swap target."


def mesh_import_preview_unexpected_payload_status() -> str:
    return "Mesh import preview finished with an unexpected result payload."


def mesh_import_preview_rebuilt_status(entry_basename: object) -> str:
    return f"Rebuilt preview for {entry_basename}."


def mesh_import_preview_rebuild_task_status(entry_basename: object) -> str:
    return f"Rebuilding mesh preview for {entry_basename}..."


def mesh_import_preview_cancelled_status() -> str:
    return "Mesh import preview cancelled before alignment options were accepted."


def in_game_mesh_swap_same_source_status() -> str:
    return "Choose a different archive mesh as the in-game swap source."


def in_game_mesh_swap_progress_text() -> dict[str, str]:
    return {
        "label": "Reading in-game mesh source...",
        "title": "In-Game Mesh Swap",
    }


def mesh_import_compatibility_control_text() -> dict[str, str]:
    return {
        "details_section": "Compatibility Details",
        "details_group": "Details",
    }


def mesh_import_setup_control_text() -> dict[str, str]:
    return {
        "startup_label": "Analyzing imported mesh...",
        "startup_title": "Mesh Import Preflight",
        "reading_replacement_scene": "Reading replacement scene...",
        "reading_original_mesh": "Reading original mesh donor...",
        "checking_asset_compatibility": "Checking asset compatibility...",
        "unsupported_title": "Mesh Import Unsupported",
        "local_source": "Local source",
        "replacement_ready": "Replacement ready",
        "replacement_blocked": "Replacement blocked",
        "roundtrip_unavailable": "Round-trip unavailable",
        "payload_group": "Preflight & Files",
        "cancel_button": "Cancel",
    }


def mesh_import_static_guidance_text(guidance: object) -> str:
    return (
        f"{guidance} Texture assignment is estimated; "
        "review visible color/normal/material slots in the alignment step."
    )


def mesh_import_replacement_status_chip(*, static_enabled: bool) -> tuple[str, str]:
    text = mesh_import_setup_control_text()
    return (text["replacement_ready"], "ready") if static_enabled else (text["replacement_blocked"], "warn")


def mesh_import_placement_status_chips() -> tuple[tuple[str, str], ...]:
    return (
        ("Next: review placement", "warn"),
        ("Offset / rotation / scale", "info"),
    )


def mesh_import_continue_button_text(*, placement_context_note: str) -> str:
    return "Review Placement" if placement_context_note.strip() else "Continue"


__all__ = [
    "direct_source_model_swap_incomplete_payload_status",
    "direct_source_model_swap_task_status",
    "direct_source_model_swap_unexpected_payload_status",
    "direct_source_model_swap_written_status",
    "in_game_mesh_swap_progress_text",
    "in_game_mesh_swap_same_source_status",
    "mesh_import_compatibility_control_text",
    "mesh_import_continue_button_text",
    "mesh_import_file_dialog_title",
    "mesh_import_preview_cancelled_status",
    "mesh_import_preview_rebuild_task_status",
    "mesh_import_preview_rebuilt_status",
    "mesh_import_preview_unexpected_payload_status",
    "mesh_import_placement_status_chips",
    "mesh_import_replacement_mode_log",
    "mesh_import_replacement_status_chip",
    "mesh_import_setup_control_text",
    "mesh_import_setup_dialog_title",
    "mesh_import_static_guidance_text",
    "pending_in_game_mesh_swap_cancelled_status",
    "pending_in_game_mesh_swap_target_status",
]
