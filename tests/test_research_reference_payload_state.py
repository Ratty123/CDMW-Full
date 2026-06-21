from __future__ import annotations

from cdmw.core.research import MaterialTextureReferenceRow
from cdmw.ui.research.reference_payload_state import (
    current_ui_constraint_related_paths,
    normalize_relative_path,
    normalize_research_target_key,
    reference_resolve_already_running_status_text,
    reference_resolve_complete_state,
    reference_resolve_missing_target_status_text,
    reference_resolve_start_state,
    reference_row_review_enabled,
    reference_review_incomplete_status_text,
    reference_review_missing_status_text,
    reference_target_load_state,
    resolved_extract_request_state,
    resolved_extract_paths,
    review_reference_text_search_payload,
    ui_constraint_initial_status_text,
    ui_constraint_refresh_preserved_status_text,
    ui_constraint_refresh_stale_status_text,
    ui_constraint_scan_complete_state,
    ui_constraint_scan_start_state,
)


def test_reference_payload_helpers_normalize_and_collect_targets() -> None:
    ui_row = MaterialTextureReferenceRow(
        source_path="ui/layout.xml",
        source_package_label="pak_a",
        related_path="texture/ui.dds",
        related_package_label="pak_a",
        relation_kind="ui_rect",
        match_count=1,
        snippet="GetRect",
    )
    assert normalize_relative_path(r" texture\armor.dds ") == "texture/armor.dds"
    assert normalize_research_target_key(r" texture\armor.dds ") == "texture/armor.dds"
    assert current_ui_constraint_related_paths({"ui_constraint_rows": [ui_row, object()]}) == ["texture/ui.dds"]
    assert current_ui_constraint_related_paths({"ui_constraint_rows": object()}) == []
    assert resolved_extract_paths({"extract_paths": ["a.dds", object(), "b.dds"]}) == ["a.dds", "b.dds"]
    assert resolved_extract_paths({"extract_paths": object()}) == []


def test_ui_constraint_status_helpers_format_scan_and_refresh_states() -> None:
    assert ui_constraint_initial_status_text() == (
        "Not scanned for the current archive set yet. Run this when you specifically want UI/XML rect evidence."
    )
    assert ui_constraint_refresh_preserved_status_text() == "Using the latest UI rect scan for the current archive set."
    assert ui_constraint_refresh_stale_status_text() == (
        "Not scanned for the current archive set yet. Run 'Scan UI Rect References' when you need UI/XML rect evidence."
    )

    start_state = ui_constraint_scan_start_state()
    assert start_state.status_text == "Preparing UI/XML rect scan across archive text references..."
    assert start_state.user_status_text == "Scanning archive UI/XML references for explicit GetRect evidence..."

    complete_state = ui_constraint_scan_complete_state(1234)
    assert complete_state.status_text == (
        "UI rect scan complete. Found 1,234 explicit UI/XML rect reference row(s)."
    )
    assert complete_state.user_status_text == complete_state.status_text


def test_reference_payload_helpers_enable_text_search_review_only_for_valid_rows() -> None:
    ui_row = MaterialTextureReferenceRow(
        source_path="ui/layout.xml",
        source_package_label="pak_a",
        related_path="texture/ui.dds",
        related_package_label="pak_a",
        relation_kind="ui_rect",
        match_count=1,
        snippet="GetRect",
    )
    assert review_reference_text_search_payload(ui_row) == ("ui/layout.xml", "ui.dds")
    assert reference_row_review_enabled(ui_row)
    assert not reference_row_review_enabled(
        MaterialTextureReferenceRow("", "pak_a", "texture/ui.dds", "pak_a", "ui_rect", 1, "GetRect")
    )
    assert not reference_row_review_enabled(object())
    assert review_reference_text_search_payload(object()) is None


def test_reference_target_and_extract_request_states_format_user_actions() -> None:
    missing_target = reference_target_load_state("")
    assert missing_target.is_error
    assert missing_target.should_focus_archive_browser
    assert "No archive file is currently selected" in missing_target.status_text

    loaded_target = reference_target_load_state("texture\\armor.dds")
    assert not loaded_target.is_error
    assert not loaded_target.should_focus_archive_browser
    assert loaded_target.normalized_target == "texture/armor.dds"
    assert loaded_target.status_text == "Loaded resolver target: texture/armor.dds"

    missing_extract = resolved_extract_request_state({"extract_paths": []})
    assert missing_extract.is_error
    assert missing_extract.extract_paths == []
    assert missing_extract.status_text == "Resolve a reference target first."

    ready_extract = resolved_extract_request_state({"extract_paths": ["a.dds", object(), "b.dds"]})
    assert not ready_extract.is_error
    assert ready_extract.extract_paths == ["a.dds", "b.dds"]
    assert ready_extract.status_text == "Extracting resolved related set..."


def test_reference_resolve_status_helpers_format_worker_states() -> None:
    assert reference_resolve_missing_target_status_text() == "Select or enter an archive path first."

    start_state = reference_resolve_start_state("texture/armor.dds")
    assert start_state.status_text == "Resolving archive relationships for texture/armor.dds"
    assert start_state.user_status_text == "Resolving archive relationships for texture/armor.dds..."

    assert reference_resolve_already_running_status_text("texture/armor.dds") == (
        "Reference resolve already running. Will use texture/armor.dds next."
    )

    complete_state = reference_resolve_complete_state(
        {
            "reference_rows": [object(), object()],
            "sidecar_rows": [object()],
            "reference_stats": {
                "mode": "outbound",
                "searched_count": 1234,
                "unreadable_count": 5,
            },
        }
    )
    assert complete_state.status_text == (
        "Resolved 2 reference row(s), 1 sidecar candidate(s), searched 1,234 text file(s), "
        "skipped 5. Mode: material -> textures."
    )
    assert complete_state.user_status_text == "Reference resolver ready."

    fallback_state = reference_resolve_complete_state({"reference_rows": object(), "sidecar_rows": object()})
    assert "Resolved 0 reference row(s), 0 sidecar candidate(s)" in fallback_state.status_text
    assert "Mode: textures <- materials." in fallback_state.status_text


def test_reference_review_status_text_helpers_preserve_user_messages() -> None:
    assert reference_review_missing_status_text() == "Select a reference result first."
    assert reference_review_incomplete_status_text() == (
        "The selected reference row does not include enough information for Text Search review."
    )
