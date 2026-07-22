"""Alignment setup presentation helpers for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from html import escape


AlignmentContextFact = tuple[str, str, str]


def alignment_selection_context_initial_text() -> str:
    return "Source: none | Target: none | Texture: none"


def alignment_selection_context_help_text() -> str:
    return (
        "This strip follows the current source, target, and texture selection. "
        "Selecting a Geometry source, target draw slot, or Texture row also highlights the related preview part."
    )


def alignment_builder_window_title() -> str:
    return "Mesh Replacement Builder"


def alignment_builder_already_open_status() -> str:
    return "Mesh Replacement Builder is already open for this target/source pair."


def alignment_builder_closed_empty_state_message() -> str:
    return "Mesh Replacement Builder closed. Choose a workflow to reopen the live .NET/Vortice Preview."


def alignment_builder_archive_preview_pause_message() -> str:
    return "Preview is paused while Mesh Replacement is open. Refresh to update anyway."


def alignment_preview_build_failed_status(message: object) -> str:
    return f"Mesh replacement preview build failed: {message}"


def alignment_setup_intro_html() -> str:
    return (
        "<div style='font-size:0.8em; line-height:1.08; padding:2px 5px; border-left:3px solid #2f81f7; background:#10233a;'>"
        "<span style='color:#79c0ff; font-weight:700;'>Setup</span>"
        "<span style='color:#c9d1d9;'> Alignment behavior, safety options, and export values.</span>"
        "</div>"
    )


def alignment_placement_review_html() -> str:
    return (
        "<div style='font-size:0.8em; line-height:1.08; padding:3px 5px; border-left:3px solid #f59e0b; background:#2a2112;'>"
        "<span style='color:#fbbf24; font-weight:700;'>Placement review required</span>"
        "<span style='color:#e5e7eb;'> Session-only clone; final output is written through loose-mod save.</span>"
        "</div>"
    )


def alignment_import_diagnostics_control_text() -> dict[str, str]:
    return {
        "details_group": "Details",
        "import_notes_section": "Import Notes",
        "fallback_label": "Note",
    }


def alignment_setup_options_control_text() -> dict[str, str]:
    return {
        "group_title": "Options",
        "alignment_mode_label": "Alignment mode",
        "alignment_mode_tooltip": (
            "Auto: Force grid flat lays the replacement's detected flat side onto the preview grid. "
            "Manual only keeps the current export transform values without automatic placement."
        ),
        "scale_to_length": "Scale replacement to original asset length",
        "scale_to_length_tooltip": (
            "When checked, the replacement length is multiplied by the shown Auto length scale. "
            "Disable it to keep the imported model size."
        ),
        "flip_direction": "Reverse main axis 180",
        "flip_direction_tooltip": (
            "Good for many swords/weapons when placement is correct but the tip points the wrong way."
        ),
    }


def alignment_setup_warning_startup_text() -> str:
    return "Alignment setup warning; continuing with limited controls..."


def alignment_setup_warning_label_text(error: object) -> str:
    return (
        "Submesh mapping could not be prepared automatically. "
        f"Mesh replacement can still continue with built-in suggestions.\n{error}"
    )


def alignment_import_diagnostic_rows(
    import_diagnostics: Sequence[object],
    *,
    limit: int = 8,
) -> tuple[tuple[str, str], ...]:
    control_text = alignment_import_diagnostics_control_text()
    rows: list[tuple[str, str]] = []
    for raw_line in tuple(import_diagnostics or ())[: max(0, int(limit))]:
        line_text = str(raw_line or "").strip()
        if not line_text:
            continue
        if ":" in line_text:
            label_text, value_text = line_text.split(":", 1)
            rows.append((label_text.strip(), value_text.strip()))
        else:
            rows.append((control_text["fallback_label"], line_text))
    return tuple(rows)


def alignment_import_diagnostics_html(rows: Sequence[tuple[str, str]]) -> str:
    import_html_rows = "".join(
        "<tr>"
        f"<td style='color:#8b949e; padding:2px 14px 2px 0; white-space:nowrap;'>{escape(label_text)}</td>"
        f"<td style='color:#f0f6fc; padding:2px 0; word-break:break-all;'>{escape(value_text)}</td>"
        "</tr>"
        for label_text, value_text in tuple(rows or ())
    )
    return (
        "<div style='font-size:0.8em; line-height:1.08;'>"
        "<table cellspacing='0' cellpadding='0' style='width:100%;'>"
        f"{import_html_rows}"
        "</table>"
        "</div>"
    )


def alignment_context_summary_group_title() -> str:
    return "Alignment Summary"


def alignment_context_summary_facts(
    context_values: Mapping[str, object],
    *,
    format_number: Callable[[float], str],
) -> tuple[AlignmentContextFact, ...]:
    original_axis_text = str(context_values.get("original_axis", "?") or "?")
    replacement_axis_text = str(context_values.get("replacement_axis", "?") or "?")
    auto_scale_value = float(context_values.get("auto_scale", 1.0) or 1.0)
    return (
        ("Original axis", original_axis_text, "#79c0ff"),
        ("Replacement axis", replacement_axis_text, "#d2a8ff"),
        ("Auto length scale", format_number(auto_scale_value), "#7ee787"),
        ("Start point", "Auto alignment, Flip 180 if needed, then fine tune Transform.", "#f2cc60"),
    )


def alignment_workflow_control_text() -> dict[str, str]:
    return {
        "setup_object": "MeshAlignmentSetupScrollTab",
        "parts_object": "MeshAlignmentPartsScrollTab",
        "mesh_edit_object": "MeshAlignmentMeshEditingScrollTab",
        "materials_object": "MeshAlignmentMaterialsScrollTab",
        "diagnostics_object": "MeshAlignmentDiagnosticsScrollTab",
        "setup_label": "Setup",
        "parts_label": "Parts && Routing",
        "mesh_edit_label": "Mesh Editing",
        "materials_label": "Materials && Textures",
        "diagnostics_label": "Diagnostics",
        "diagnostics_refresh": "Refresh",
        "diagnostics_copy": "Copy",
        "diagnostics_refresh_object": "MeshAlignmentDiagnosticsRefreshButton",
        "diagnostics_copy_object": "MeshAlignmentDiagnosticsCopyButton",
        "diagnostics_text_object": "MeshAlignmentDiagnosticsText",
    }


def alignment_workflow_tab_labels() -> tuple[str, ...]:
    text = alignment_workflow_control_text()
    return (
        text["setup_label"],
        text["parts_label"],
        text["mesh_edit_label"],
        text["materials_label"],
        text["diagnostics_label"],
    )


__all__ = [
    "AlignmentContextFact",
    "alignment_builder_already_open_status",
    "alignment_builder_archive_preview_pause_message",
    "alignment_builder_closed_empty_state_message",
    "alignment_builder_window_title",
    "alignment_preview_build_failed_status",
    "alignment_context_summary_facts",
    "alignment_context_summary_group_title",
    "alignment_import_diagnostic_rows",
    "alignment_import_diagnostics_control_text",
    "alignment_import_diagnostics_html",
    "alignment_placement_review_html",
    "alignment_selection_context_help_text",
    "alignment_selection_context_initial_text",
    "alignment_setup_intro_html",
    "alignment_setup_options_control_text",
    "alignment_setup_warning_label_text",
    "alignment_setup_warning_startup_text",
    "alignment_workflow_control_text",
    "alignment_workflow_tab_labels",
]
