from __future__ import annotations

from pathlib import Path

from cdmw.core.research import (
    MaterialTextureReferenceRow,
    MipAnalysisRow,
    NormalValidationRow,
    ResearchNote,
    TextureBudgetClassSummary,
    TextureBudgetGroupSummary,
    TextureBudgetProfileSummary,
    TextureBudgetRow,
    TextureClassificationRow,
    TextureSetGroup,
    TextureUsageHeatRow,
    UnknownResolverGroup,
    UnknownResolverMember,
    UnknownResolverSuggestion,
)
from cdmw.models import ArchiveEntry
from cdmw.ui.research.state import (
    ANALYSIS_CONTEXT_HELP_TEXT,
    analysis_report_default_name,
    analysis_report_exported_status_text,
    analysis_report_missing_status_text,
    analysis_report_output_path,
    archive_picker_entry_for_path,
    archive_picker_entry_index_for_path,
    archive_picker_file_label,
    archive_picker_folder_parts,
    build_archive_snapshot_cache_key,
    budget_detail_payload,
    cached_archive_snapshot_cache_key,
    classification_review_focus_candidates,
    clamp_preview_zoom_factor,
    compare_path_missing_status_text,
    current_ui_constraint_related_paths,
    mip_analysis_tooltip_lines,
    mip_focus_refresh_pending_state,
    missing_mip_focus_state,
    normalize_archive_path,
    normalize_relative_path,
    normalize_research_preview_color_scheme,
    normalize_research_text_highlight_style,
    normalize_research_target_key,
    normalize_research_theme_key,
    next_preview_zoom_factor,
    normal_validation_tooltip_lines,
    preferred_unknown_choice_for_member,
    primary_unknown_member,
    preview_zoom_label,
    reference_resolve_already_running_status_text,
    reference_resolve_complete_state,
    reference_resolve_missing_target_status_text,
    reference_resolve_start_state,
    reference_row_review_enabled,
    reference_review_incomplete_status_text,
    reference_review_missing_status_text,
    research_note_delete_success_status_text,
    research_note_display_state,
    research_note_save_success_status_text,
    research_refresh_initial_status_text,
    research_analysis_report_rows,
    research_refresh_phase_status_text,
    research_refresh_population_rows,
    research_refresh_population_total,
    research_refresh_ready_status_text,
    research_refresh_start_state,
    resolved_extract_paths,
    review_reference_text_search_payload,
    ui_constraint_initial_status_text,
    ui_constraint_refresh_preserved_status_text,
    ui_constraint_refresh_stale_status_text,
    ui_constraint_scan_complete_state,
    ui_constraint_scan_start_state,
    semantic_subtype_for_unknown_member,
    texture_group_empty_status_text,
    texture_group_no_available_status_text,
    texture_group_population_selected_status_text,
    texture_group_selected_status_text,
    unknown_group_empty_status_text,
    unknown_group_classification_text,
    unknown_group_display_name,
    unknown_group_filter_progress_status_text,
    unknown_group_focus_status_text,
    unknown_group_matches_filters,
    unknown_group_package_text,
    unknown_group_ready_status_text,
    unknown_group_target_paths,
    unknown_label_choice_index,
    unknown_label_tuple,
    unknown_member_local_text,
    unknown_no_current_family_unknown_status_text,
    unknown_no_current_role_status_text,
    unknown_no_selected_families_unknown_status_text,
    unknown_removed_current_file_status_text,
    unknown_removed_family_status_text,
    unknown_removed_selected_families_status_text,
    unknown_saved_current_file_status_text,
    unknown_saved_current_role_status_text,
    unknown_saved_family_status_text,
    unknown_saved_selected_families_status_text,
    unknown_select_dds_status_text,
    unknown_select_families_status_text,
    unknown_select_family_status_text,
    texture_analysis_context_text,
    wildcard_filter_matches,
)


def _member(path: str, **overrides: object) -> UnknownResolverMember:
    values = {
        "path": path,
        "package_label": "pak_a",
        "current_kind": "unknown",
        "reason": "test",
        "extension": ".dds",
    }
    values.update(overrides)
    return UnknownResolverMember(**values)  # type: ignore[arg-type]


def _group() -> UnknownResolverGroup:
    members = [
        _member("0001/texture/armor_albedo.dds"),
        _member("0001/texture/armor_normal.dds", current_kind="normal", is_unknown=False),
    ]
    return UnknownResolverGroup(
        group_key="texture/armor",
        display_name="Armor",
        unknown_count=1,
        total_members=len(members),
        package_labels=["pak_a", "pak_b", "pak_c"],
        known_kinds=["normal"],
        sidecar_paths=[],
        suggestion_label="Color / Albedo",
        members=members,
    )


def _entry(path: str, package: str = "pakchunk0/paz00001.paz") -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path(package),
        paz_file=Path(package),
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


def test_archive_picker_path_state_helpers_normalize_labels_and_cache_keys() -> None:
    assert normalize_archive_path(r" 0001\texture\armor.dds ") == "0001/texture/armor.dds"
    assert archive_picker_file_label(r"0001\texture\armor.dds", show_full_path=False) == "armor.dds"
    assert archive_picker_file_label(r"0001\texture\armor.dds", show_full_path=True) == "0001/texture/armor.dds"
    assert archive_picker_folder_parts(r"0001\texture\armor.dds") == ("0001", "texture")

    entries = [_entry(r"0001\texture\armor.dds"), _entry("0001/texture/armor_n.dds")]
    assert build_archive_snapshot_cache_key(entries) == build_archive_snapshot_cache_key(entries)
    assert build_archive_snapshot_cache_key(entries).startswith("2:")
    assert build_archive_snapshot_cache_key([]) == "0:empty"

    cache: dict[tuple[int, int, str, str], str] = {}
    cached_key = cached_archive_snapshot_cache_key(entries, cache)
    assert cached_key == build_archive_snapshot_cache_key(entries)
    assert cached_archive_snapshot_cache_key(entries, cache) == cached_key
    assert len(cache) == 1
    assert cached_archive_snapshot_cache_key([], cache) == "0:empty"

    eager_index = {normalize_archive_path(entries[0].path).casefold(): 0}
    lazy_index: dict[str, int] = {}
    assert archive_picker_entry_index_for_path(
        "0001/texture/armor.dds",
        entries=entries,
        entry_index_by_path=eager_index,
        lazy_entry_index_by_path=lazy_index,
    ) == 0
    assert archive_picker_entry_index_for_path(
        "0001/texture/armor_n.dds",
        entries=entries,
        entry_index_by_path=eager_index,
        lazy_entry_index_by_path=lazy_index,
    ) == 1
    assert lazy_index["0001/texture/armor_n.dds"] == 1
    assert archive_picker_entry_for_path(
        r"0001\texture\armor.dds",
        entries=entries,
        entry_by_path={normalize_archive_path(entries[0].path): entries[0]},
        entry_index_by_path=eager_index,
        lazy_entry_index_by_path=lazy_index,
    ) is entries[0]
    assert archive_picker_entry_for_path(
        "missing.dds",
        entries=entries,
        entry_by_path={},
        entry_index_by_path={},
        lazy_entry_index_by_path={},
    ) is None


def test_research_theme_and_preview_style_helpers_normalize_invalid_values() -> None:
    assert normalize_research_theme_key("") == "graphite"
    assert normalize_research_theme_key("midnight") == "midnight"
    assert normalize_research_text_highlight_style("plain") == "plain"
    assert normalize_research_text_highlight_style("missing") == "rich"
    assert normalize_research_preview_color_scheme("vscode") == "vscode"
    assert normalize_research_preview_color_scheme("missing") == "theme"
    assert normalize_research_target_key(r" texture\armor.dds ") == "texture/armor.dds"


def test_preview_zoom_helpers_clamp_and_step() -> None:
    assert clamp_preview_zoom_factor(0.01) == 0.1
    assert clamp_preview_zoom_factor(20.0) == 16.0
    assert next_preview_zoom_factor(1.0, 1) == 1.5
    assert next_preview_zoom_factor(1.0, -1) == 0.75
    assert next_preview_zoom_factor(16.0, 1) == 16.0
    assert preview_zoom_label(fit_to_view=True, zoom_factor=1.25) == "Fit"
    assert preview_zoom_label(fit_to_view=False, zoom_factor=1.25) == "125%"


def test_payload_path_helpers_collect_ui_constraints_and_unknown_targets() -> None:
    ui_row = MaterialTextureReferenceRow(
        source_path="ui/layout.xml",
        source_package_label="pak_a",
        related_path="texture/ui.dds",
        related_package_label="pak_a",
        relation_kind="ui_rect",
        match_count=1,
        snippet="GetRect",
    )
    assert current_ui_constraint_related_paths({"ui_constraint_rows": [ui_row, object()]}) == ["texture/ui.dds"]
    assert current_ui_constraint_related_paths({"ui_constraint_rows": object()}) == []
    assert ui_constraint_initial_status_text().startswith("Not scanned for the current archive set")
    assert ui_constraint_refresh_preserved_status_text() == "Using the latest UI rect scan for the current archive set."
    assert "Scan UI Rect References" in ui_constraint_refresh_stale_status_text()
    assert ui_constraint_scan_start_state().status_text == "Preparing UI/XML rect scan across archive text references..."
    assert "Found 3 explicit" in ui_constraint_scan_complete_state(3).status_text
    assert resolved_extract_paths({"extract_paths": ["a.dds", object(), "b.dds"]}) == ["a.dds", "b.dds"]
    assert resolved_extract_paths({"extract_paths": object()}) == []
    assert review_reference_text_search_payload(ui_row) == ("ui/layout.xml", "ui.dds")
    assert reference_row_review_enabled(ui_row)
    assert not reference_row_review_enabled(
        MaterialTextureReferenceRow("", "pak_a", "texture/ui.dds", "pak_a", "ui_rect", 1, "GetRect")
    )
    assert not reference_row_review_enabled(object())
    assert review_reference_text_search_payload(object()) is None
    assert reference_resolve_missing_target_status_text() == "Select or enter an archive path first."
    assert reference_resolve_start_state("texture/ui.dds").status_text == (
        "Resolving archive relationships for texture/ui.dds"
    )
    assert reference_resolve_already_running_status_text("texture/ui.dds") == (
        "Reference resolve already running. Will use texture/ui.dds next."
    )
    assert "Resolved 1 reference row(s)" in reference_resolve_complete_state(
        {"reference_rows": [ui_row], "sidecar_rows": []}
    ).status_text
    assert reference_review_missing_status_text() == "Select a reference result first."
    assert "does not include enough information" in reference_review_incomplete_status_text()

    group = _group()
    assert unknown_group_target_paths([group], unknown_only=True) == ["0001/texture/armor_albedo.dds"]
    assert unknown_group_target_paths([group], unknown_only=False) == [
        "0001/texture/armor_albedo.dds",
        "0001/texture/armor_normal.dds",
    ]


def test_research_note_state_compatibility_exports() -> None:
    note = ResearchNote(
        target_key="texture/armor.dds",
        source_kind="archive",
        tags=["dds", "armor"],
        note="Check alpha.",
        updated_at="2026-06-14T00:00:00+00:00",
    )
    display_state = research_note_display_state(note)

    assert display_state.target_key == "texture/armor.dds"
    assert display_state.source_kind == "archive"
    assert display_state.tags_text == "dds, armor"
    assert display_state.note_text == "Check alpha."
    assert research_note_save_success_status_text() == "Saved research note."
    assert research_note_delete_success_status_text() == "Deleted research note."


def test_analysis_path_and_tooltip_helpers_format_planner_context() -> None:
    assert normalize_relative_path(r" texture\armor.dds ") == "texture/armor.dds"

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
        root_label="Output root",
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
        size_text="1024x1024",
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


def test_analysis_report_state_compatibility_exports(tmp_path: Path) -> None:
    missing_state = missing_mip_focus_state("texture/armor.dds")
    assert missing_state.detail_label == "Mip Analysis details"
    assert "texture/armor.dds" in missing_state.status_text
    assert compare_path_missing_status_text() == "Select a DDS file in Compare first."
    assert "texture/armor.dds" in mip_focus_refresh_pending_state("texture/armor.dds").status_text
    assert analysis_report_default_name(".csv") == "texture_analysis_report.csv"
    assert analysis_report_output_path(str(tmp_path / "report"), ".json") == tmp_path / "report.json"
    assert analysis_report_missing_status_text() == "Refresh Research first to build an analysis report."
    assert "report.json" in analysis_report_exported_status_text(tmp_path / "report.json")


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
    assert "cached archive insights" in research_refresh_start_state(
        uses_full_archive_view=True,
        archive_entry_count=1200,
        view_entry_count=2,
        has_cached_archive_snapshot=True,
    ).status_text
    assert research_refresh_ready_status_text(
        uses_full_archive_view=False,
        archive_entry_count=1200,
        view_entry_count=2,
    ) == "Research snapshot ready for the current Archive Browser view (2 file(s))."


def test_texture_group_status_text_helpers_format_selection_states() -> None:
    assert texture_group_empty_status_text(has_current_item=False) == (
        "Select a grouped texture set to extract its related files and sidecars."
    )
    assert texture_group_empty_status_text(has_current_item=True) == (
        "Select a grouped texture set on the left, then click 'Extract Selected Set'."
    )
    assert texture_group_selected_status_text(display_name="Armor", member_count=1200, package_count=3) == (
        "Selected group: Armor (1,200 member(s), 3 package(s))."
    )
    assert texture_group_population_selected_status_text("Armor") == (
        "Selected group: Armor. Click 'Extract Selected Set' to extract its related files and sidecars."
    )
    assert texture_group_no_available_status_text() == (
        "No grouped texture sets are available in the current Research snapshot."
    )


def test_unknown_group_status_text_helpers_format_population_states() -> None:
    assert "Workflow needs a saved local approval" in unknown_group_focus_status_text()
    assert unknown_group_filter_progress_status_text(scanned=1000, total=2000, matched=25) == (
        "Filtering classification review... 1,000 / 2,000 scanned | 25 matched"
    )
    assert unknown_group_empty_status_text(showing_classified=True, has_focus_keys=False) == (
        "No review items are available in the current Research snapshot."
    )
    assert unknown_group_empty_status_text(showing_classified=False, has_focus_keys=False) == (
        "No unresolved review items match the current filters."
    )
    assert "No current-run unclassified DDS files matched" in unknown_group_empty_status_text(
        showing_classified=False,
        has_focus_keys=True,
    )
    assert unknown_group_ready_status_text(
        item_count=2,
        registry_text="registry.json",
        showing_classified=True,
        has_focus_keys=False,
    ) == "2 review item(s) are available. Approved labels are stored in registry.json."
    focused_status = unknown_group_ready_status_text(
        item_count=3,
        registry_text="local registry",
        showing_classified=False,
        has_focus_keys=True,
    )
    assert focused_status.startswith("3 unresolved item(s) need review.")
    assert "targeted DDS files" in focused_status


def test_unknown_action_status_text_compatibility_exports() -> None:
    assert unknown_select_dds_status_text() == "Select a DDS file in Family Members first."
    assert unknown_no_current_role_status_text() == (
        "The selected DDS does not currently have a concrete role to accept yet."
    )
    assert unknown_select_family_status_text() == "Select a texture family first."
    assert unknown_select_families_status_text() == "Select one or more texture families first."
    assert unknown_no_current_family_unknown_status_text() == "No unknown DDS files remain in the current family."
    assert unknown_no_selected_families_unknown_status_text() == "No unknown DDS files remain in the selected families."
    assert "normal/normal" in unknown_saved_current_role_status_text("normal", "normal")
    assert "current DDS file" in unknown_saved_current_file_status_text("color", "albedo")
    assert "3 file(s) in the current family" in unknown_saved_family_status_text("mask", "specular", 3)
    assert "2 selected family/families" in unknown_saved_selected_families_status_text(
        "emissive",
        "emissive",
        4,
        2,
    )
    assert "current DDS file" in unknown_removed_current_file_status_text()
    assert "current family" in unknown_removed_family_status_text(2)
    assert "3 selected family/families" in unknown_removed_selected_families_status_text(5, 3)


def test_classification_review_focus_candidates_include_stripped_archive_prefix() -> None:
    assert classification_review_focus_candidates(r"0001\texture\armor_albedo.dds") == {
        "0001/texture/armor_albedo.dds",
        "texture/armor_albedo.dds",
    }


def test_unknown_group_display_and_status_text() -> None:
    group = _group()

    assert unknown_group_display_name(group, primary_member=group.members[0]) == "armor_albedo.dds (+1)"
    assert primary_unknown_member(group) == group.members[0]
    assert primary_unknown_member(None) is None
    assert unknown_group_classification_text(group) == "Color / Albedo"
    assert unknown_group_package_text(group) == "pak_a, pak_b..."


def test_unknown_member_local_text_formats_saved_approval() -> None:
    assert unknown_member_local_text(_member("a.dds")) == "No"
    assert unknown_member_local_text(
        _member("a.dds", local_texture_type="COLOR", local_semantic_subtype="ALBEDO")
    ) == "Yes: color/albedo"
    assert unknown_label_tuple(("mask_specular", "mask", "specular")) == ("mask_specular", "mask", "specular")
    assert unknown_label_tuple("bad") == ("color_albedo", "color", "albedo")
    assert unknown_label_choice_index([("color_albedo", "color", "albedo"), ("mask_specular", "mask", "specular")], "mask_specular") == 1
    assert unknown_label_choice_index([], "mask_specular") == -1


def test_unknown_group_matches_focus_name_and_package_filters() -> None:
    group = _group()

    assert wildcard_filter_matches("armor_albedo.dds", "armor")
    assert unknown_group_matches_filters(
        group,
        pending_focus_keys={"texture/armor_albedo.dds"},
        name_filter="armor",
        package_filter="pak_b",
        primary_member=group.members[0],
    )


def test_preferred_unknown_choice_uses_current_kind_then_group_suggestion() -> None:
    mask_member = _member("texture/armor_spec.dds", current_kind="mask")
    assert semantic_subtype_for_unknown_member(mask_member) == "specular"
    assert preferred_unknown_choice_for_member(mask_member, None) == "mask_specular"

    group = _group()
    group.suggestions.append(
        UnknownResolverSuggestion(
            choice_key="emissive_emissive",
            texture_type="emissive",
            semantic_subtype="emissive",
            confidence=80,
            reason="test",
        )
    )
    assert preferred_unknown_choice_for_member(_member("texture/unknown.dds"), group) == "emissive_emissive"
    assert not unknown_group_matches_filters(
        group,
        pending_focus_keys={"texture/missing.dds"},
        name_filter="armor",
        package_filter="pak_b",
        primary_member=group.members[0],
    )
