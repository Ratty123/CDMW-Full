from __future__ import annotations

from pathlib import Path

from cdmw.core.research import (
    MipAnalysisRow,
    NormalValidationRow,
    TextureBudgetClassSummary,
    TextureBudgetGroupSummary,
    TextureBudgetProfileSummary,
    TextureBudgetRow,
)
from cdmw.ui.research.analysis_state import (
    ANALYSIS_CONTEXT_HELP_TEXT,
    analysis_report_default_name,
    analysis_report_exported_status_text,
    analysis_report_missing_status_text,
    analysis_report_output_path,
    budget_detail_payload,
    compare_path_missing_status_text,
    mip_analysis_tooltip_lines,
    mip_focus_refresh_pending_state,
    missing_mip_focus_state,
    normal_validation_tooltip_lines,
    research_analysis_report_rows,
    texture_analysis_context_text,
)


def test_analysis_path_and_tooltip_helpers_format_planner_context() -> None:
    mip = MipAnalysisRow(
        relative_path="texture/armor.dds",
        original_format="BC7",
        rebuilt_format="BC7",
        original_size="1024x1024",
        rebuilt_size="2048x2048",
        original_mips=8,
        rebuilt_mips=9,
        warning_count=1,
        planner_profile="Default",
        planner_path_kind="color",
        planner_backend_mode="native",
        planner_alpha_policy="preserve",
        planner_preserve_reason="manual",
        warnings=["Mip count changed"],
    )
    mip_tooltip = "\n".join(mip_analysis_tooltip_lines(mip))
    assert "Mip count changed" in mip_tooltip
    assert "Planner profile: Default" in mip_tooltip
    assert "Planner preserve reason: manual" in mip_tooltip

    normal = NormalValidationRow(
        path="texture/armor_n.dds",
        root_label="Output",
        texconv_format="BC5",
        size_text="1024x1024",
        issue_count=1,
        planner_profile="Normals",
        planner_path_kind="normal",
        issues=["Normal map range issue"],
    )
    normal_tooltip = "\n".join(normal_validation_tooltip_lines(normal))
    assert "Normal map range issue" in normal_tooltip
    assert "Planner path: normal" in normal_tooltip


def test_budget_detail_payload_formats_supported_budget_rows() -> None:
    row = TextureBudgetRow(
        relative_path="texture/armor.dds",
        group_key="texture/armor",
        system_area="characters",
        folder_bucket="texture",
        texture_type="color",
        planner_profile="Default",
        planner_path_kind="color",
        planner_alpha_policy="preserve",
        original_bytes=1024,
        rebuilt_bytes=2048,
        byte_delta=1024,
        byte_ratio=2.0,
        original_width=512,
        original_height=512,
        rebuilt_width=1024,
        rebuilt_height=1024,
        pixel_ratio=4.0,
        original_mips=8,
        rebuilt_mips=9,
        mip_delta=1,
        original_format="BC7",
        rebuilt_format="BC7",
        format_changed=False,
        changed=True,
        risk_score=40,
        risk_band="Medium",
        risk_signals=["Upscaled"],
    )
    label, text = budget_detail_payload(row) or ("", "")
    assert label == "Budget file details"
    assert "Path: texture/armor.dds" in text
    assert "Byte delta: +1,024" in text
    assert "- Upscaled" in text

    class_label, class_text = budget_detail_payload(
        TextureBudgetClassSummary("color", 2, 512, 22.5, "Low", ["a.dds"])
    ) or ("", "")
    assert class_label == "Budget class summary"
    assert "Affected textures: 2" in class_text

    group_label, group_text = budget_detail_payload(
        TextureBudgetGroupSummary("terrain", "world", 3, 100, 200, 100, 2.0, 3.0, 512.0, 512.0, 1, 0, 20.0, 25, "Low", ["Large"])
    ) or ("", "")
    assert group_label == "Terrain-like group summary"
    assert "Group key: terrain" in group_text

    profile_label, profile_text = budget_detail_payload(
        TextureBudgetProfileSummary("Default", 100, 200, 100, 2.0, 3, 2, 0.25, 50, ["Changed"])
    ) or ("", "")
    assert profile_label == "Budget profile summary"
    assert "High-risk fraction: 25.0%" in profile_text
    assert budget_detail_payload(object()) is None


def test_texture_analysis_context_text_summarizes_payload_counts(tmp_path: Path) -> None:
    assert "Texture Analysis uses your current Original DDS root" in ANALYSIS_CONTEXT_HELP_TEXT
    original_root = tmp_path / "original"
    output_root = tmp_path / "output"
    original_root.mkdir()
    output_root.mkdir()
    mip = MipAnalysisRow(
        relative_path="texture/armor.dds",
        original_format="BC7",
        rebuilt_format="BC7",
        original_size="1024x1024",
        rebuilt_size="2048x2048",
        original_mips=8,
        rebuilt_mips=9,
        warning_count=0,
        planner_profile="Default",
        planner_path_kind="color",
    )
    normal = NormalValidationRow(
        path="texture/armor_n.dds",
        root_label="Output root",
        texconv_format="BC5",
        size_text="512x512",
        issue_count=0,
    )
    context = texture_analysis_context_text(
        original_root_text=str(original_root),
        output_root_text=str(output_root),
        research_payload={
            "mip_rows": [mip],
            "normal_rows": [normal],
            "budget_rows": [object(), object()],
            "budget_profile": TextureBudgetProfileSummary("Default", 100, 200, 100, 2.0, 3, 2, 0.25, 50),
        },
    )
    assert "- Original DDS root:" in context
    assert "(available)" in context
    assert "Mip Analysis rows: 1" in context
    assert "Planner path summary: color: 1" in context
    assert "Current roots represented: Output root: 1" in context
    assert "Current heuristic budget profile: Default" in context


def test_research_analysis_report_rows_preserve_export_payload_lists() -> None:
    budget_profile = TextureBudgetProfileSummary("Default", 100, 200, 100, 2.0, 1, 1, 0.0, 20)
    rows = research_analysis_report_rows(
        {
            "mip_rows": ["mip"],
            "normal_rows": ["normal"],
            "budget_rows": ["budget"],
            "budget_class_rows": object(),
            "budget_group_rows": ["group"],
            "budget_profile": budget_profile,
        }
    )

    assert rows is not None
    assert rows.mip_rows == ["mip"]
    assert rows.normal_rows == ["normal"]
    assert rows.budget_rows == ["budget"]
    assert rows.budget_class_rows == []
    assert rows.budget_group_rows == ["group"]
    assert rows.budget_profile is budget_profile
    assert research_analysis_report_rows({"mip_rows": object(), "normal_rows": []}) is None


def test_missing_mip_focus_state_formats_status_and_detail_text() -> None:
    state = missing_mip_focus_state("texture/armor.dds")

    assert state.detail_label == "Mip Analysis details"
    assert "No Mip Analysis row was found for texture/armor.dds" in state.status_text
    assert "Relative path: texture/armor.dds" in state.detail_text
    assert "Check the current DDS roots" in state.user_status_text


def test_mip_focus_status_helpers_format_compare_focus_messages() -> None:
    assert compare_path_missing_status_text() == "Select a DDS file in Compare first."

    pending_state = mip_focus_refresh_pending_state("texture/armor.dds")
    assert pending_state.status_text == (
        "Research refresh already running. Will focus mip analysis for texture/armor.dds when ready."
    )
    assert pending_state.user_status_text == pending_state.status_text


def test_analysis_report_path_and_status_helpers_normalize_export_decisions(tmp_path: Path) -> None:
    assert analysis_report_default_name(".csv") == "texture_analysis_report.csv"
    assert analysis_report_missing_status_text() == "Refresh Research first to build an analysis report."

    selected_path = tmp_path / "analysis"
    assert analysis_report_output_path(str(selected_path), ".json") == selected_path.with_suffix(".json")
    assert analysis_report_output_path(str(tmp_path / "analysis.csv"), ".json") == tmp_path / "analysis.csv"
    assert analysis_report_output_path(str(tmp_path / "analysis.JSON"), ".csv") == tmp_path / "analysis.JSON"
    assert analysis_report_output_path("", ".csv") is None

    assert analysis_report_exported_status_text(tmp_path / "analysis.csv").endswith("analysis.csv")
