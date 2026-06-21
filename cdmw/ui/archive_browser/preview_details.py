"""Archive preview details text helpers."""

from __future__ import annotations

import re
from typing import List, Tuple


class ArchivePreviewDetailsMixin:
    """Compose Archive Browser preview detail text."""
    @staticmethod
    def _split_archive_detail_blocks(detail_text: str) -> Tuple[List[str], List[str], str, str]:
        text = str(detail_text or "").strip()
        if not text:
            return [], [], "", ""

        lines = text.splitlines()
        metadata_prefixes = (
            "Path:",
            "Package:",
            "PAMT:",
            "PAZ:",
            "Offset:",
            "Original size:",
            "Stored size:",
            "Compression:",
            "Encrypted:",
        )
        metadata_lines: List[str] = []
        line_index = 0
        while line_index < len(lines):
            current_line = lines[line_index].strip()
            if not current_line:
                line_index += 1
                if metadata_lines:
                    break
                continue
            if any(current_line.startswith(prefix) for prefix in metadata_prefixes):
                metadata_lines.append(current_line)
                line_index += 1
                continue
            break

        remainder = "\n".join(lines[line_index:]).strip()
        note_blocks: List[str] = []
        readable_strings_block = ""
        binary_header_block = ""
        if remainder:
            for block in re.split(r"\n\s*\n", remainder):
                normalized_block = block.strip()
                if not normalized_block:
                    continue
                if normalized_block.startswith("Binary header preview:"):
                    binary_header_block = normalized_block.partition(":")[2].strip() or normalized_block
                    continue
                if normalized_block.startswith("Readable strings from") or normalized_block.startswith("Readable strings:"):
                    readable_strings_block = normalized_block
                    continue
                if normalized_block.startswith("String scan truncated") and readable_strings_block:
                    readable_strings_block = f"{readable_strings_block}\n\n{normalized_block}".strip()
                    continue
                note_blocks.append(normalized_block)
        return metadata_lines, note_blocks, readable_strings_block, binary_header_block

    @classmethod
    def _compose_model_preview_detail_text(cls, base_detail_text: str, debug_details_text: str) -> str:
        base_text = str(base_detail_text or "").strip()
        debug_text = str(debug_details_text or "").strip()
        metadata_lines, note_blocks, readable_strings_block, binary_header_block = cls._split_archive_detail_blocks(
            base_text
        )

        sections: List[Tuple[str, str]] = []
        if metadata_lines:
            sections.append(("Entry Metadata", "\n".join(metadata_lines)))

        note_text = "\n\n".join(block for block in note_blocks if block.strip()).strip()
        if note_text:
            sections.append(("Preview / Texture Notes", note_text))
        elif base_text and not metadata_lines and not readable_strings_block and not binary_header_block:
            sections.append(("Import Summary", base_text))

        if debug_text:
            sections.append(("Preview Diagnostics", debug_text))
        if readable_strings_block:
            sections.append(("Readable Strings", readable_strings_block))
        if binary_header_block:
            sections.append(("Binary Header Preview", binary_header_block))
        if not sections:
            return "No details available."
        return "\n\n".join(
            f"{title}\n{content}".strip()
            for title, content in sections
            if str(content or "").strip()
        )

    def _refresh_archive_preview_details_text(
        self,
        _debug_text: str = "",
        *,
        include_current_model_debug: bool = True,
    ) -> None:
        base_detail_text = str(getattr(self, "_archive_preview_base_detail_text", "") or "").strip()
        if not base_detail_text and self.current_archive_preview_result is not None:
            base_detail_text = str(
                self.current_archive_preview_result.detail_text
                or self.current_archive_preview_result.metadata_summary
                or "No details available."
            ).strip()
        debug_detail_text = ""
        if (
            include_current_model_debug
            and
            self.current_archive_preview_result is not None
            and not self.archive_preview_showing_loose
            and self.current_archive_preview_result.preview_model is not None
        ):
            active_preview = self._active_archive_model_preview_widget() or self.archive_model_preview
            if hasattr(active_preview, "debug_details_text"):
                debug_detail_text = active_preview.debug_details_text()
            timing_summary = str(getattr(self.current_archive_preview_result, "timing_summary", "") or "").strip()
            if timing_summary:
                debug_detail_text = (
                    f"{debug_detail_text.rstrip()}\n{timing_summary}"
                    if debug_detail_text.strip()
                    else timing_summary
                )
        isolated_debug_text = str(getattr(self, "archive_isolated_renderer_debug_text", "") or "").strip()
        if isolated_debug_text:
            debug_detail_text = (
                f"{debug_detail_text.rstrip()}\n{isolated_debug_text}"
                if debug_detail_text.strip()
                else isolated_debug_text
            )
        self.archive_preview_details_edit.setPlainText(
            self._compose_model_preview_detail_text(base_detail_text, debug_detail_text)
        )

    def _set_archive_preview_base_detail_text(
        self,
        detail_text: str,
        *,
        include_current_model_debug: bool = True,
    ) -> None:
        self._archive_preview_base_detail_text = str(detail_text or "")
        self._refresh_archive_preview_details_text(include_current_model_debug=include_current_model_debug)
