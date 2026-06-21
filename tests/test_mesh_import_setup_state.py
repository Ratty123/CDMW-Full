from __future__ import annotations

from cdmw.ui.archive_browser.mesh_import_setup_state import (
    direct_source_model_swap_incomplete_payload_status,
    direct_source_model_swap_task_status,
    direct_source_model_swap_unexpected_payload_status,
    direct_source_model_swap_written_status,
    in_game_mesh_swap_progress_text,
    in_game_mesh_swap_same_source_status,
    mesh_import_compatibility_control_text,
    mesh_import_continue_button_text,
    mesh_import_file_dialog_title,
    mesh_import_preview_cancelled_status,
    mesh_import_preview_rebuild_task_status,
    mesh_import_preview_rebuilt_status,
    mesh_import_preview_unexpected_payload_status,
    mesh_import_placement_status_chips,
    mesh_import_replacement_mode_log,
    mesh_import_replacement_status_chip,
    mesh_import_setup_control_text,
    mesh_import_setup_dialog_title,
    mesh_import_static_guidance_text,
    pending_in_game_mesh_swap_cancelled_status,
    pending_in_game_mesh_swap_target_status,
)


def test_mesh_import_compatibility_control_text_preserves_copy() -> None:
    text = mesh_import_compatibility_control_text()

    assert text["details_section"] == "Compatibility Details"
    assert text["details_group"] == "Details"


def test_mesh_import_dialog_titles_and_log_text_preserve_copy() -> None:
    assert mesh_import_file_dialog_title() == "Select Mesh File"
    assert mesh_import_setup_dialog_title() == "Mesh Import Setup"
    assert mesh_import_replacement_mode_log(".gltf") == "GLTF imports use Mesh Replacement mode."


def test_mesh_import_flow_status_text_preserves_copy() -> None:
    assert direct_source_model_swap_unexpected_payload_status() == (
        "Direct source model swap finished with an unexpected result payload."
    )
    assert direct_source_model_swap_incomplete_payload_status() == (
        "Direct source model swap finished with an incomplete result payload."
    )
    assert direct_source_model_swap_written_status("target.pac", "C:/out") == (
        "Wrote direct source model swap for target.pac: C:/out"
    )
    assert direct_source_model_swap_task_status("target.pac") == (
        "Writing direct source model swap for target.pac..."
    )
    assert pending_in_game_mesh_swap_target_status("target.pac") == (
        "In-game mesh swap target set: target.pac. "
        "Select the source mesh in Archive Browser, then click Use as Swap Source."
    )
    assert pending_in_game_mesh_swap_cancelled_status() == "Cancelled the pending in-game mesh swap target."
    assert mesh_import_preview_unexpected_payload_status() == (
        "Mesh import preview finished with an unexpected result payload."
    )
    assert mesh_import_preview_rebuilt_status("target.pac") == "Rebuilt preview for target.pac."
    assert mesh_import_preview_rebuild_task_status("target.pac") == "Rebuilding mesh preview for target.pac..."
    assert mesh_import_preview_cancelled_status() == (
        "Mesh import preview cancelled before alignment options were accepted."
    )
    assert in_game_mesh_swap_same_source_status() == "Choose a different archive mesh as the in-game swap source."
    assert in_game_mesh_swap_progress_text() == {
        "label": "Reading in-game mesh source...",
        "title": "In-Game Mesh Swap",
    }


def test_mesh_import_placement_status_chips_preserve_copy_and_tones() -> None:
    assert mesh_import_placement_status_chips() == (
        ("Next: review placement", "warn"),
        ("Offset / rotation / scale", "info"),
    )


def test_mesh_import_setup_control_text_preserves_copy() -> None:
    text = mesh_import_setup_control_text()

    assert text["startup_label"] == "Analyzing imported mesh..."
    assert text["startup_title"] == "Mesh Import Preflight"
    assert text["reading_replacement_scene"] == "Reading replacement scene..."
    assert text["reading_original_mesh"] == "Reading original mesh donor..."
    assert text["checking_asset_compatibility"] == "Checking asset compatibility..."
    assert text["unsupported_title"] == "Mesh Import Unsupported"
    assert text["local_source"] == "Local source"
    assert text["replacement_ready"] == "Replacement ready"
    assert text["replacement_blocked"] == "Replacement blocked"
    assert text["roundtrip_unavailable"] == "Round-trip unavailable"
    assert text["payload_group"] == "Preflight & Files"
    assert text["cancel_button"] == "Cancel"


def test_mesh_import_static_guidance_text_preserves_suffix() -> None:
    assert mesh_import_static_guidance_text("Ready.") == (
        "Ready. Texture assignment is estimated; "
        "review visible color/normal/material slots in the alignment step."
    )


def test_mesh_import_replacement_status_chip_preserves_labels_and_tones() -> None:
    assert mesh_import_replacement_status_chip(static_enabled=True) == ("Replacement ready", "ready")
    assert mesh_import_replacement_status_chip(static_enabled=False) == ("Replacement blocked", "warn")


def test_mesh_import_continue_button_text_uses_placement_context() -> None:
    assert mesh_import_continue_button_text(placement_context_note="Review before export.") == "Review Placement"
    assert mesh_import_continue_button_text(placement_context_note="   ") == "Continue"
