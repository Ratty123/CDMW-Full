from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_alignment_setup_state import (
    alignment_builder_already_open_status,
    alignment_builder_archive_preview_pause_message,
    alignment_builder_closed_empty_state_message,
    alignment_builder_window_title,
    alignment_preview_build_failed_status,
    alignment_context_summary_facts,
    alignment_context_summary_group_title,
    alignment_import_diagnostic_rows,
    alignment_import_diagnostics_control_text,
    alignment_import_diagnostics_html,
    alignment_placement_review_html,
    alignment_selection_context_help_text,
    alignment_selection_context_initial_text,
    alignment_setup_intro_html,
    alignment_setup_options_control_text,
    alignment_setup_warning_label_text,
    alignment_setup_warning_startup_text,
    alignment_workflow_control_text,
    alignment_workflow_tab_labels,
)


def test_alignment_builder_window_title_preserves_default_title() -> None:
    assert alignment_builder_window_title() == "Mesh Replacement Builder"
    assert alignment_builder_already_open_status() == (
        "Mesh Replacement Builder is already open for this target/source pair."
    )
    assert alignment_builder_closed_empty_state_message() == (
        "Mesh Replacement Builder closed. Choose a workflow to reopen the live D3D11 preview."
    )
    assert alignment_builder_archive_preview_pause_message() == (
        "Preview is paused while Mesh Replacement is open. Refresh to update anyway."
    )
    assert alignment_preview_build_failed_status("boom") == "Mesh replacement preview build failed: boom"


def test_alignment_selection_context_text_preserves_copy() -> None:
    assert alignment_selection_context_initial_text() == "Source: none | Target: none | Texture: none"
    help_text = alignment_selection_context_help_text()

    assert "current source, target, and texture selection" in help_text
    assert "highlights the related preview part" in help_text


def test_alignment_setup_intro_html_preserves_copy() -> None:
    html = alignment_setup_intro_html()

    assert "Setup" in html
    assert "Alignment behavior, safety options, and export values." in html
    assert "border-left:3px solid #2f81f7" in html


def test_alignment_placement_review_html_preserves_copy() -> None:
    html = alignment_placement_review_html()

    assert "Placement review required" in html
    assert "Session-only clone; final output is written through loose-mod save." in html
    assert "border-left:3px solid #f59e0b" in html


def test_alignment_import_diagnostics_control_text_preserves_copy() -> None:
    text = alignment_import_diagnostics_control_text()

    assert text["details_group"] == "Details"
    assert text["import_notes_section"] == "Import Notes"
    assert text["fallback_label"] == "Note"


def test_alignment_setup_options_control_text_preserves_copy() -> None:
    text = alignment_setup_options_control_text()

    assert text["group_title"] == "Options"
    assert text["alignment_mode_label"] == "Alignment mode"
    assert "detected flat side" in text["alignment_mode_tooltip"]
    assert text["scale_to_length"] == "Scale replacement to original asset length"
    assert "Auto length scale" in text["scale_to_length_tooltip"]
    assert text["flip_direction"] == "Reverse main axis 180"
    assert "tip points the wrong way" in text["flip_direction_tooltip"]


def test_alignment_setup_warning_text_preserves_copy() -> None:
    assert alignment_setup_warning_startup_text() == "Alignment setup warning; continuing with limited controls..."
    warning = alignment_setup_warning_label_text("boom")

    assert "Submesh mapping could not be prepared automatically." in warning
    assert "Mesh replacement can still continue with built-in suggestions." in warning
    assert warning.endswith("\nboom")


def test_alignment_import_diagnostic_rows_splits_labels_and_limits_rows() -> None:
    rows = alignment_import_diagnostic_rows(
        [
            "File: source.obj",
            "",
            "No delimiter note",
            "Size: 42",
            "Ignored: 1",
        ],
        limit=4,
    )

    assert rows == (
        ("File", "source.obj"),
        ("Note", "No delimiter note"),
        ("Size", "42"),
    )


def test_alignment_import_diagnostics_html_preserves_table_format_and_escapes() -> None:
    html = alignment_import_diagnostics_html((("File", "<source.obj>"), ("Note", "safe")))

    assert "font-size:0.8em" in html
    assert "<table cellspacing='0' cellpadding='0' style='width:100%;'>" in html
    assert "File" in html
    assert "&lt;source.obj&gt;" in html
    assert "word-break:break-all" in html


def test_alignment_context_summary_facts_preserves_labels_colors_and_values() -> None:
    facts = alignment_context_summary_facts(
        {"original_axis": "X", "replacement_axis": "Z", "auto_scale": 1.25},
        format_number=lambda value: f"{value:.2f}",
    )

    assert alignment_context_summary_group_title() == "Alignment Summary"
    assert facts == (
        ("Original axis", "X", "#79c0ff"),
        ("Replacement axis", "Z", "#d2a8ff"),
        ("Auto length scale", "1.25", "#7ee787"),
        ("Start point", "Auto alignment, Flip 180 if needed, then fine tune Transform.", "#f2cc60"),
    )


def test_alignment_context_summary_facts_uses_fallbacks() -> None:
    facts = alignment_context_summary_facts({}, format_number=lambda value: f"{value:g}")

    assert facts[0] == ("Original axis", "?", "#79c0ff")
    assert facts[1] == ("Replacement axis", "?", "#d2a8ff")
    assert facts[2] == ("Auto length scale", "1", "#7ee787")


def test_alignment_workflow_control_text_preserves_labels_and_object_names() -> None:
    text = alignment_workflow_control_text()

    assert text["setup_object"] == "MeshAlignmentSetupScrollTab"
    assert text["parts_object"] == "MeshAlignmentPartsScrollTab"
    assert text["mesh_edit_object"] == "MeshAlignmentMeshEditingScrollTab"
    assert text["materials_object"] == "MeshAlignmentMaterialsScrollTab"
    assert text["diagnostics_object"] == "MeshAlignmentDiagnosticsScrollTab"
    assert text["setup_label"] == "Setup"
    assert text["parts_label"] == "Parts && Routing"
    assert text["mesh_edit_label"] == "Mesh Editing"
    assert text["materials_label"] == "Materials && Textures"
    assert text["diagnostics_label"] == "Diagnostics"
    assert text["diagnostics_refresh"] == "Refresh"
    assert text["diagnostics_copy"] == "Copy"
    assert text["diagnostics_refresh_object"] == "MeshAlignmentDiagnosticsRefreshButton"
    assert text["diagnostics_copy_object"] == "MeshAlignmentDiagnosticsCopyButton"
    assert text["diagnostics_text_object"] == "MeshAlignmentDiagnosticsText"


def test_alignment_workflow_tab_labels_follow_control_text_order() -> None:
    assert alignment_workflow_tab_labels() == (
        "Setup",
        "Parts && Routing",
        "Mesh Editing",
        "Materials && Textures",
        "Diagnostics",
    )
