from __future__ import annotations

from cdmw.core.research import ResearchNote, TextureSetGroup, TextureSetMember
from cdmw.models import ArchivePreviewResult
from cdmw.ui.research import (
    analysis_state,
    archive_picker_state,
    classification_review_state,
    display_preferences_state,
    notes_state,
    preview_state,
    reference_payload_state,
    refresh_population_state,
    state,
    texture_group_state,
)
from cdmw.ui.research.display_preferences_state import (
    clamp_preview_zoom_factor,
    next_preview_zoom_factor,
    normalize_research_preview_color_scheme,
    normalize_research_text_highlight_style,
    normalize_research_theme_key,
    preview_zoom_label,
)
from cdmw.ui.research.notes_state import (
    research_note_delete_success_status_text,
    research_note_display_state,
    research_note_save_success_status_text,
    research_note_target_state,
    sorted_research_note_items,
)
from cdmw.ui.research.preview_state import (
    archive_picker_clear_preview_state,
    archive_picker_folder_preview_state,
    archive_picker_loading_preview_state,
    research_preview_display_state,
    unknown_clear_preview_state,
    unknown_loading_preview_state,
)
from cdmw.ui.research.texture_group_state import (
    texture_group_extract_state,
    texture_group_empty_status_text,
    texture_group_no_available_status_text,
    texture_group_population_selected_status_text,
    texture_group_selected_status_text,
)
from cdmw.ui.research.layout_state import (
    research_analysis_splitter_default_sizes,
    research_analysis_splitter_responsive_sizes,
    research_analysis_splitter_saved_sizes,
    research_archive_picker_splitter_default_sizes,
    research_groups_splitter_default_sizes,
    research_groups_splitter_responsive_sizes,
    research_groups_splitter_saved_sizes,
    research_main_splitter_default_sizes,
    research_main_splitter_responsive_sizes,
    research_main_splitter_saved_sizes,
    research_notes_splitter_default_sizes,
    research_notes_splitter_responsive_sizes,
    research_notes_splitter_saved_sizes,
    research_reference_splitter_default_sizes,
    research_reference_splitter_responsive_sizes,
    research_reference_splitter_saved_sizes,
    research_unknown_splitter_default_sizes,
    research_unknown_splitter_responsive_sizes,
    research_unknown_splitter_saved_sizes,
)


OWNER_MODULES = (
    analysis_state,
    archive_picker_state,
    classification_review_state,
    display_preferences_state,
    notes_state,
    preview_state,
    reference_payload_state,
    refresh_population_state,
    texture_group_state,
)


def test_research_state_facade_exports_owner_objects() -> None:
    assert len(state.__all__) == len(set(state.__all__))

    for name in state.__all__:
        facade_value = getattr(state, name)
        assert any(
            hasattr(owner, name) and getattr(owner, name) is facade_value
            for owner in OWNER_MODULES
        ), name


def test_research_theme_and_preview_style_helpers_normalize_invalid_values() -> None:
    assert normalize_research_theme_key("") == "graphite"
    assert normalize_research_theme_key("midnight") == "midnight"
    assert normalize_research_text_highlight_style("plain") == "plain"
    assert normalize_research_text_highlight_style("missing") == "rich"
    assert normalize_research_preview_color_scheme("vscode") == "vscode"
    assert normalize_research_preview_color_scheme("missing") == "theme"


def test_preview_zoom_helpers_clamp_and_step() -> None:
    assert clamp_preview_zoom_factor(0.01) == 0.1
    assert clamp_preview_zoom_factor(20.0) == 16.0
    assert next_preview_zoom_factor(1.0, 1) == 1.5
    assert next_preview_zoom_factor(1.0, -1) == 0.75
    assert next_preview_zoom_factor(16.0, 1) == 16.0
    assert preview_zoom_label(fit_to_view=True, zoom_factor=1.25) == "Fit"
    assert preview_zoom_label(fit_to_view=False, zoom_factor=1.25) == "125%"


def _note(target_key: str, *, tags: list[str] | None = None, note: str = "body") -> ResearchNote:
    return ResearchNote(
        target_key=target_key,
        source_kind="archive",
        tags=tags or [],
        note=note,
        updated_at="2026-06-14T00:00:00+00:00",
    )


def test_research_note_target_state_handles_missing_and_existing_notes() -> None:
    missing = research_note_target_state(source_kind="archive", target_key="", notes={})

    assert missing.is_error
    assert missing.status_text == "No current selection is available for notes."
    assert missing.normalized_target == ""

    notes = {
        "texture/armor.dds": _note("texture/armor.dds", tags=["dds", "armor"], note="Check alpha."),
    }
    loaded = research_note_target_state(
        source_kind="archive",
        target_key="texture\\armor.dds",
        notes=notes,
    )

    assert not loaded.is_error
    assert loaded.normalized_target == "texture/armor.dds"
    assert loaded.source_kind == "archive"
    assert loaded.tags_text == "dds, armor"
    assert loaded.note_text == "Check alpha."
    assert loaded.status_text == "Loaded note target: texture/armor.dds"


def test_sorted_research_note_items_orders_notes_case_insensitively() -> None:
    notes = {
        "z.dds": _note("z.dds"),
        "A.dds": _note("A.dds"),
    }

    assert [key for key, _note_value in sorted_research_note_items(notes)] == ["A.dds", "z.dds"]


def test_research_note_display_and_status_helpers_format_widget_state() -> None:
    note = _note("texture/armor.dds", tags=["dds", "armor"], note="Check alpha.")
    display_state = research_note_display_state(note)

    assert display_state.target_key == "texture/armor.dds"
    assert display_state.source_kind == "archive"
    assert display_state.tags_text == "dds, armor"
    assert display_state.note_text == "Check alpha."
    assert research_note_save_success_status_text() == "Saved research note."
    assert research_note_delete_success_status_text() == "Deleted research note."


def test_research_preview_display_state_applies_fallback_text() -> None:
    display = research_preview_display_state(ArchivePreviewResult(status="ready"))

    assert display.title == "Selected Preview"
    assert display.metadata_summary == "Preview ready."
    assert display.detail_text == "Preview ready."
    assert display.warning_text == ""
    assert display.image_title == "Selected Preview"
    assert display.use_image_view is False
    assert display.use_text_view is False


def test_research_preview_display_state_detects_image_and_text_modes() -> None:
    image_display = research_preview_display_state(
        ArchivePreviewResult(
            status="ready",
            title="Armor",
            metadata_summary="DDS preview",
            detail_text="Details",
            preferred_view="image",
            preview_image_path="preview.png",
            warning_text="Large file",
        )
    )

    assert image_display.title == "Armor"
    assert image_display.metadata_summary == "DDS preview"
    assert image_display.detail_text == "Details"
    assert image_display.warning_text == "Large file"
    assert image_display.use_image_view is True
    assert image_display.use_text_view is False

    text_display = research_preview_display_state(
        ArchivePreviewResult(status="ready", preferred_view="text", preview_text="metadata")
    )

    assert text_display.use_image_view is False
    assert text_display.use_text_view is True
    assert text_display.preview_text == "metadata"


def test_archive_picker_preview_text_states_format_clear_folder_and_loading_views() -> None:
    clear_state = archive_picker_clear_preview_state("Pick a file.")
    assert clear_state.title == "Select an archive file"
    assert clear_state.metadata_text == "Pick a file."
    assert clear_state.info_text == "Pick a file."
    assert clear_state.details_text == ""
    assert clear_state.image_empty_text == "Pick a file."

    folder_state = archive_picker_folder_preview_state("texture/armor", 1200)
    assert folder_state.title == "texture/armor"
    assert folder_state.metadata_text == "Folder | 1,200 file(s)"
    assert folder_state.info_text == "Folder: texture/armor\nFiles: 1,200"
    assert folder_state.details_text == "Folder: texture/armor\nFiles: 1,200"
    assert folder_state.image_empty_text == "Select a file to preview it here."

    root_folder_state = archive_picker_folder_preview_state("", 1)
    assert root_folder_state.title == "/"

    loading_state = archive_picker_loading_preview_state("armor.dds")
    assert loading_state.title == "armor.dds"
    assert loading_state.metadata_text == "Loading preview..."
    assert loading_state.info_text == "Preparing preview..."
    assert loading_state.details_text == "Preparing preview..."


def test_unknown_preview_text_states_format_clear_and_loading_views() -> None:
    clear_state = unknown_clear_preview_state("Select a DDS review item.")
    assert clear_state.title == "Select an unknown family member"
    assert clear_state.metadata_text == "Select a DDS review item."
    assert clear_state.info_text == "Select a DDS review item."
    assert clear_state.image_empty_text == "Select a DDS review item."

    loading_state = unknown_loading_preview_state("armor_n.dds")
    assert loading_state.title == "armor_n.dds"
    assert loading_state.metadata_text == "Loading preview..."
    assert loading_state.info_text == "Preparing preview..."
    assert loading_state.details_text == ""


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


def test_texture_group_extract_state_reports_empty_selection_and_ready_paths() -> None:
    no_groups = texture_group_extract_state([], None)
    assert no_groups.is_error
    assert no_groups.paths == []
    assert no_groups.status_text == "No grouped texture sets are available yet. Click 'Refresh Research' first."

    group = TextureSetGroup(
        group_key="armor",
        display_name="Armor",
        member_count=2,
        package_labels=["pak_a"],
        member_kinds=["color", "normal"],
        members=[
            TextureSetMember("texture/armor_a.dds", "pak_a", "color", ".dds"),
            TextureSetMember("texture/armor_n.dds", "pak_a", "normal", ".dds"),
        ],
    )
    no_selection = texture_group_extract_state([group], None)
    assert no_selection.is_error
    assert no_selection.paths == []
    assert no_selection.status_text == "Select a grouped texture set first. If the list is stale or empty, click 'Refresh Research'."

    ready = texture_group_extract_state([group], group)
    assert not ready.is_error
    assert ready.paths == ["texture/armor_a.dds", "texture/armor_n.dds"]
    assert ready.status_text == "Extracting related texture set..."


def test_research_main_splitter_sizes_keep_details_visible() -> None:
    assert research_main_splitter_default_sizes(320) == [1296, 504]
    assert research_main_splitter_responsive_sizes(1000, 320) == [680, 320]
    assert research_main_splitter_saved_sizes(1000, [900, 100], 320) == [680, 320]


def test_research_group_and_unknown_splitter_sizes_scale_from_content_width() -> None:
    assert research_groups_splitter_default_sizes() == [607, 773]
    assert research_groups_splitter_responsive_sizes(1000) == [420, 500]
    assert research_groups_splitter_saved_sizes(1000, [100, 900]) == [420, 500]

    assert research_unknown_splitter_default_sizes() == [605, 1015, 540]
    assert research_unknown_splitter_responsive_sizes(1000) == [300, 360, 260]
    assert research_unknown_splitter_saved_sizes(1000, [50, 900, 50]) == [300, 360, 260]


def test_research_reference_archive_analysis_and_notes_splitters_keep_minimums() -> None:
    assert research_reference_splitter_default_sizes() == [801, 739]
    assert research_reference_splitter_responsive_sizes(1000) == [499, 461]
    assert research_reference_splitter_saved_sizes(1000, [50, 950]) == [420, 540]

    assert research_archive_picker_splitter_default_sizes() == [660, 540]

    assert research_analysis_splitter_default_sizes() == [557, 557, 626]
    assert research_analysis_splitter_responsive_sizes(1000) == [294, 294, 332]
    assert research_analysis_splitter_saved_sizes(1000, [50, 50, 900]) == [280, 280, 360]

    assert research_notes_splitter_default_sizes() == [728, 672]
    assert research_notes_splitter_responsive_sizes(1000) == [478, 442]
    assert research_notes_splitter_saved_sizes(1000, [50, 950]) == [320, 600]
