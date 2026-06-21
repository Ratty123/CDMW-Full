from __future__ import annotations

from cdmw.core.research import (
    MaterialTextureReferenceRow,
    MipAnalysisRow,
    NormalValidationRow,
    TextureBudgetClassSummary,
    TextureBudgetGroupSummary,
    TextureBudgetProfileSummary,
    TextureBudgetRow,
    TextureClassificationRow,
    TextureSetGroup,
    TextureUsageHeatRow,
)
from cdmw.ui.research.refresh_population_state import (
    research_refresh_initial_status_text,
    research_refresh_phase_status_text,
    research_refresh_ready_status_text,
    research_refresh_start_state,
    research_refresh_population_rows,
    research_refresh_population_total,
)


def test_research_refresh_population_rows_filter_and_group_payloads() -> None:
    texture_group = TextureSetGroup("texture/armor", "Armor", 1, ["pak_a"], ["color"], [])
    classification = TextureClassificationRow("texture/armor.dds", "pak_a", "color", 90, "name", "texture/armor")
    heat_a = TextureUsageHeatRow("world", "terrain", 2, 1, 0, 0, 1, 0, 25, ["a.dds"])
    heat_b = TextureUsageHeatRow("ui", "hud", 1, 1, 0, 0, 0, 0, 10, ["b.dds"])
    heat_c = TextureUsageHeatRow("world", "props", 1, 0, 1, 0, 0, 0, 15, ["c.dds"])
    mip = MipAnalysisRow("texture/armor.dds", "BC7", "BC7", "512x512", "1024x1024", 8, 9, 1)
    normal = NormalValidationRow("texture/armor_n.dds", "Output", "BC5", "512x512", 0)
    ui_row = MaterialTextureReferenceRow("ui.xml", "pak_a", "texture/ui.dds", "pak_a", "ui_rect", 1, "GetRect")
    budget = TextureBudgetRow(
        relative_path="texture/armor.dds",
        group_key="texture/armor",
        system_area="characters",
        folder_bucket="texture",
        texture_type="color",
        planner_profile="Default",
        planner_path_kind="color",
        planner_alpha_policy="preserve",
        original_bytes=100,
        rebuilt_bytes=200,
        byte_delta=100,
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
        risk_score=20,
        risk_band="Low",
    )
    budget_class = TextureBudgetClassSummary("color", 1, 100, 20, "Low", ["texture/armor.dds"])
    budget_group = TextureBudgetGroupSummary("texture/armor", "characters", 1, 100, 200, 100, 2.0, 4.0, 512, 1024, 1, 0, 20, 20, "Low")
    budget_profile = TextureBudgetProfileSummary("Default", 100, 200, 100, 2.0, 1, 1, 0.0, 20)

    rows = research_refresh_population_rows(
        {
            "texture_groups": [texture_group, object()],
            "classification_rows": [classification],
            "heatmap_rows": [heat_a, object(), heat_b, heat_c],
            "mip_rows": [mip],
            "normal_rows": [normal],
            "ui_constraint_rows": [ui_row],
            "budget_rows": [budget],
            "budget_class_rows": [budget_class],
            "budget_group_rows": [budget_group],
            "budget_profile": budget_profile,
        }
    )

    assert rows.texture_groups == [texture_group]
    assert rows.classification_rows == [classification]
    assert [(scope, len(scope_rows)) for scope, scope_rows in rows.heatmap_groups] == [("world", 2), ("ui", 1)]
    assert rows.mip_rows == [mip]
    assert rows.normal_rows == [normal]
    assert rows.ui_constraint_rows == [ui_row]
    assert rows.budget_rows == [budget]
    assert rows.budget_class_rows == [budget_class]
    assert rows.budget_group_rows == [budget_group]
    assert rows.budget_profile_rows == [budget_profile]
    assert research_refresh_population_total(rows) == 11

    empty_rows = research_refresh_population_rows({"texture_groups": object(), "heatmap_rows": object()})
    assert research_refresh_population_total(empty_rows) == 0


def test_research_refresh_population_status_text() -> None:
    assert research_refresh_initial_status_text(uses_full_archive_view=True, total=1200).endswith(
        "the full loaded archive... 0 / 1,200"
    )
    assert research_refresh_initial_status_text(uses_full_archive_view=False, total=2).endswith(
        "the current Archive Browser view... 0 / 2"
    )
    assert research_refresh_phase_status_text(phase_name="mip analysis", processed=7, total=12) == (
        "Populating mip analysis... 7 / 12"
    )

    cached_start = research_refresh_start_state(
        uses_full_archive_view=True,
        archive_entry_count=1200,
        view_entry_count=3,
        has_cached_archive_snapshot=True,
    )
    assert cached_start.status_text == (
        "Preparing research snapshot from the full loaded archive (1,200 file(s)) with cached archive insights..."
    )
    assert cached_start.user_status_text == "Refreshing research snapshot with cached archive insights..."

    current_start = research_refresh_start_state(
        uses_full_archive_view=False,
        archive_entry_count=1200,
        view_entry_count=3,
        has_cached_archive_snapshot=False,
    )
    assert current_start.status_text == "Preparing research snapshot from the current Archive Browser view (3 file(s))..."
    assert current_start.user_status_text == "Refreshing research snapshot..."
    assert research_refresh_ready_status_text(
        uses_full_archive_view=True,
        archive_entry_count=1200,
        view_entry_count=3,
    ) == "Research snapshot ready for the full loaded archive (1,200 file(s))."
    assert research_refresh_ready_status_text(
        uses_full_archive_view=False,
        archive_entry_count=1200,
        view_entry_count=3,
    ) == "Research snapshot ready for the current Archive Browser view (3 file(s))."
