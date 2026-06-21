from __future__ import annotations

from cdmw.models import ArchivePreviewResult
from cdmw.ui.research.preview_state import (
    archive_picker_clear_preview_state,
    archive_picker_folder_preview_state,
    archive_picker_loading_preview_state,
    research_preview_display_state,
    unknown_clear_preview_state,
    unknown_loading_preview_state,
)


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
