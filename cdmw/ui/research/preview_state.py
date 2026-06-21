"""Preview display state rules for the Research tab."""

from __future__ import annotations

from dataclasses import dataclass

from cdmw.models import ArchivePreviewResult

__all__ = [
    "ResearchPreviewDisplayState",
    "ResearchPreviewPanelTextState",
    "archive_picker_clear_preview_state",
    "archive_picker_folder_preview_state",
    "archive_picker_loading_preview_state",
    "research_preview_display_state",
    "unknown_clear_preview_state",
    "unknown_loading_preview_state",
]


@dataclass(frozen=True, slots=True)
class ResearchPreviewDisplayState:
    title: str
    metadata_summary: str
    detail_text: str
    warning_text: str
    image_title: str
    use_image_view: bool
    use_text_view: bool
    preview_text: str


@dataclass(frozen=True, slots=True)
class ResearchPreviewPanelTextState:
    title: str
    metadata_text: str
    info_text: str
    details_text: str
    image_empty_text: str


def research_preview_display_state(result: ArchivePreviewResult) -> ResearchPreviewDisplayState:
    title = result.title or "Selected Preview"
    metadata_summary = result.metadata_summary or "Preview ready."
    return ResearchPreviewDisplayState(
        title=title,
        metadata_summary=metadata_summary,
        detail_text=result.detail_text or metadata_summary,
        warning_text=result.warning_text,
        image_title=title or "Preview image",
        use_image_view=result.preferred_view == "image" and (result.preview_image is not None or bool(result.preview_image_path)),
        use_text_view=result.preferred_view == "text" and bool(result.preview_text),
        preview_text=result.preview_text,
    )


def archive_picker_clear_preview_state(message: str) -> ResearchPreviewPanelTextState:
    return ResearchPreviewPanelTextState(
        title="Select an archive file",
        metadata_text=message,
        info_text=message,
        details_text="",
        image_empty_text=message,
    )


def archive_picker_folder_preview_state(folder_text: str, count: int) -> ResearchPreviewPanelTextState:
    folder_label = folder_text or "/"
    message = f"Folder: {folder_text}\nFiles: {count:,}"
    return ResearchPreviewPanelTextState(
        title=folder_label,
        metadata_text=f"Folder | {count:,} file(s)",
        info_text=message,
        details_text=message,
        image_empty_text="Select a file to preview it here.",
    )


def archive_picker_loading_preview_state(entry_basename: str) -> ResearchPreviewPanelTextState:
    return ResearchPreviewPanelTextState(
        title=entry_basename,
        metadata_text="Loading preview...",
        info_text="Preparing preview...",
        details_text="Preparing preview...",
        image_empty_text="",
    )


def unknown_clear_preview_state(message: str) -> ResearchPreviewPanelTextState:
    return ResearchPreviewPanelTextState(
        title="Select an unknown family member",
        metadata_text=message,
        info_text=message,
        details_text="",
        image_empty_text=message,
    )


def unknown_loading_preview_state(entry_basename: str) -> ResearchPreviewPanelTextState:
    return ResearchPreviewPanelTextState(
        title=entry_basename,
        metadata_text="Loading preview...",
        info_text="Preparing preview...",
        details_text="",
        image_empty_text="",
    )
