from __future__ import annotations

from pathlib import Path

from cdmw.ui.archive_browser.static_replacement_source_mix_state import (
    alignment_source_mix_control_text,
    alignment_source_mix_current_status,
    alignment_source_mix_loose_added_message,
    alignment_source_mix_loose_scan_status,
    alignment_source_mix_parity_presentation,
    alignment_source_mix_reopening_archive_status,
    alignment_source_mix_reopening_loose_status,
    alignment_source_mix_reopening_mod_archive_status,
)


def test_alignment_source_mix_control_text_preserves_copy() -> None:
    text = alignment_source_mix_control_text()

    assert text["group_title"] == "Source Mixing"
    assert "in-game swap path" in text["tray_tooltip"]
    assert text["hint"] == "Add alternate sources without leaving this dialog."
    assert text["add_archive"] == "Add Archive Source"
    assert "existing in-game swap flow" in text["add_archive_tooltip"]
    assert text["add_loose"] == "Add Loose Mod Folder"
    assert "Mesh Replacement Setup" in text["add_loose_tooltip"]
    assert text["add_mod_archive"] == "Add .pamt/.paz Mod"
    assert "replacement source" in text["add_mod_archive_tooltip"]
    assert text["archive_source_prompt"] == "Search archive source by name, path, package, or role"
    assert text["loose_source_prompt"] == "Search loose mesh source by name, path, or role"
    assert text["mod_archive_source_prompt"] == "Search mod archive mesh source by name, path, or role"
    assert text["use_loose_mesh_title"] == "Use Loose Mesh Source"
    assert text["use_mod_archive_mesh_title"] == "Use Mod Archive Mesh Source"
    assert text["loose_added_title"] == "Loose Source Added"
    assert text["loose_source_label_prefix"] == "Loose mod source: "
    assert text["loose_placement_review_title"] == "Loose Mesh Source Placement"
    assert "This source came from a loose mod folder" in text["loose_placement_context_note"]
    assert "texture sidecar output" in text["loose_placement_context_note"]
    assert text["mod_archive_file_filter"] == "Archive Mod Sources (*.pamt *.paz);;All Files (*.*)"
    assert text["no_loaded_archive_sources"] == "No other loaded archive mesh sources are available."
    assert text["no_mod_archive_mesh_entries"] == "The selected mod archive did not contain mesh entries."


def test_alignment_source_mix_current_status_uses_filename_for_display_and_full_tooltip() -> None:
    status = alignment_source_mix_current_status(Path("mods/source/test_mesh.pac"))

    assert status.text == "Current: test_mesh.pac"
    assert status.tooltip == "mods\\source\\test_mesh.pac" or status.tooltip == "mods/source/test_mesh.pac"
    assert alignment_source_mix_current_status("").text == "Current: replacement source"


def test_alignment_source_mix_parity_presentation_preserves_modes() -> None:
    clone = alignment_source_mix_parity_presentation(modify_original_clone_mode=True)
    regular = alignment_source_mix_parity_presentation(modify_original_clone_mode=False)

    assert clone.text == "Geometry same | Materials same | Render settings same | Camera synced"
    assert regular.text == "Roundtrip import diagnostic mode can show OBJ/material differences separately."
    assert "Selection highlight preserves texture bindings" in clone.tooltip
    assert clone.tooltip == regular.tooltip


def test_alignment_source_mix_status_messages_format_counts_and_paths() -> None:
    assert alignment_source_mix_reopening_archive_status("archive/foo.pac") == (
        "Reopening with archive source: archive/foo.pac"
    )
    assert alignment_source_mix_reopening_loose_status("C:/mods/foo.obj") == (
        "Reopening with loose mesh source: C:/mods/foo.obj"
    )
    assert alignment_source_mix_reopening_mod_archive_status("archive/bar.pac") == (
        "Reopening with mod archive source: archive/bar.pac"
    )
    assert alignment_source_mix_loose_scan_status("C:/mods/folder", mesh_count=2, supplemental_count=1200) == (
        "Loose source scanned: folder | 2 mesh candidate(s), 1,200 texture/sidecar candidate(s)."
    )


def test_alignment_source_mix_loose_added_message_preserves_guidance() -> None:
    message = alignment_source_mix_loose_added_message("C:/mods/folder", mesh_count=2, supplemental_count=3)

    assert "Scanned C:/mods/folder" in message
    assert "Mesh candidates: 2" in message
    assert "Texture/sidecar candidates: 3" in message
    assert "local texture/sidecar files are added from Mesh Replacement Setup" in message
    assert "Use Add Archive Source or Add .pamt/.paz Mod" in message
