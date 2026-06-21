from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_texture_diagnostics import texture_target_diagnostics_html


def test_texture_target_diagnostics_html_handles_empty_rows() -> None:
    html = texture_target_diagnostics_html(
        "target_body",
        (),
        texture_row_source_summary=lambda _row: "",
        texture_row_is_assigned=lambda _row: False,
    )

    assert "No sidecar texture rows were found" in html


def test_texture_target_diagnostics_html_reports_selected_row_and_warnings() -> None:
    row = {
        "target_name": "target_body",
        "part_display": "Body",
        "slot_kind": "base",
        "role_label": "Base / Color",
        "parameter_name": "_baseTexture",
        "target_path": "character/texture/body_base.dds",
        "checked": False,
        "source_path": "",
        "state_label": "Needs review",
        "confidence": "manual",
        "shader_family": "SkinnedMeshStandard_Ver2",
        "visualized": False,
        "classification": SimpleNamespace(
            semantic_type="mask",
            semantic_subtype="material_mask",
            visualized=False,
            reason="mask reason",
        ),
        "_assigned_count": 0,
        "_target_row_count": 1,
    }

    html = texture_target_diagnostics_html(
        "target_body",
        (row,),
        row,
        texture_row_source_summary=lambda _row: "Source body",
        texture_row_is_assigned=lambda _row: False,
    )

    assert "target_body" in html
    assert "0/1 slot(s) assigned" in html
    assert "Affects: Source body" in html
    assert "Original sidecar bindings" in html
    assert "Warnings" in html
    assert "no replacement base/color" in html
    assert "material/mask data" in html
    assert "advanced shader slot" in html
