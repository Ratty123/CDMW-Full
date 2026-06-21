from __future__ import annotations

import dataclasses
import threading
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImageReader

from cdmw.core.archive import ArchiveEntry
from cdmw.core.replace_assistant import (
    ReplaceAssistantArchiveIndex,
    build_replace_assistant_archive_index,
    build_replace_assistant_items,
    build_replace_assistant_package,
    build_replace_assistant_preview_assets,
    match_replace_assistant_original,
)
from cdmw.core.research import summarize_ui_reference_constraints
from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.core.texture_pipeline.preview import build_compare_preview_pane_result
from cdmw.models import (
    ArchivePreviewResult,
    ReplaceAssistantBuildOptions,
    ReplaceAssistantItem,
    ReplaceAssistantReviewItem,
    RunCancelled,
)


class ReplaceAssistantPreviewWorker(QObject):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        texconv_path: Optional[Path],
        source_path: Path,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.texconv_path = texconv_path
        self.source_path = source_path
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            preview_png_path, metadata_summary, detail_text = build_replace_assistant_preview_assets(
                self.texconv_path,
                self.source_path,
            )
            result = ArchivePreviewResult(
                status="ok" if preview_png_path or self.source_path.exists() else "missing",
                title=self.source_path.name,
                metadata_summary=metadata_summary,
                detail_text=detail_text,
                preview_image_path=preview_png_path,
                preferred_view="preview",
            )
            if not self.stop_event.is_set() and result.preview_image_path:
                reader = QImageReader(result.preview_image_path)
                image = reader.read()
                if not image.isNull():
                    result = dataclasses.replace(result, preview_image=image)
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, result)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, str(exc))
        finally:
            self.finished.emit()


class ReplaceAssistantBuildWorker(QObject):
    log_message = Signal(str)
    current_file = Signal(str)
    progress = Signal(int, int, str)
    completed = Signal(object)
    cancelled = Signal(str)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        items: Sequence[ReplaceAssistantItem],
        options: ReplaceAssistantBuildOptions,
        *,
        archive_entries: Sequence[ArchiveEntry],
        original_dds_root: Optional[Path],
    ) -> None:
        super().__init__()
        self.items = list(items)
        self.options = options
        self.archive_entries = list(archive_entries)
        self.original_dds_root = original_dds_root
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            summary = build_replace_assistant_package(
                self.items,
                self.options,
                archive_entries=self.archive_entries,
                original_dds_root=self.original_dds_root,
                stop_event=self.stop_event,
                on_log=self.log_message.emit,
                on_progress=self.progress.emit,
                on_current_file=self.current_file.emit,
            )
            if summary.cancelled:
                self.cancelled.emit("Texture Replacer build stopped by user.")
            else:
                self.completed.emit(summary)
        except RunCancelled as exc:
            self.cancelled.emit(str(exc) or "Texture Replacer build stopped by user.")
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class ReplaceAssistantImportWorker(QObject):
    stage_message = Signal(str)
    progress = Signal(int, int, str)
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        paths: Sequence[Path | str],
        *,
        archive_entries: Sequence[ArchiveEntry],
        original_dds_root: Optional[Path],
        archive_index: Optional[ReplaceAssistantArchiveIndex],
    ) -> None:
        super().__init__()
        self.paths = list(paths)
        self.archive_entries = archive_entries
        self.original_dds_root = original_dds_root
        self.archive_index = archive_index
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            items = build_replace_assistant_items(
                self.paths,
                on_stage=self.stage_message.emit,
                on_progress=self.progress.emit,
                perform_matching=False,
            )
            if not self.stop_event.is_set():
                self.completed.emit(
                    {
                        "items": items,
                        "archive_index": self.archive_index,
                        "original_dds_root": self.original_dds_root,
                    }
                )
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(str(exc))
        finally:
            self.finished.emit()


class ReplaceAssistantAutoMatchWorker(QObject):
    stage_message = Signal(str)
    progress = Signal(int, int, str)
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        items: Sequence[ReplaceAssistantItem],
        *,
        archive_entries: Sequence[ArchiveEntry],
        original_dds_root: Optional[Path],
        archive_index: Optional[ReplaceAssistantArchiveIndex],
    ) -> None:
        super().__init__()
        self.items = [dataclasses.replace(item) for item in items]
        self.archive_entries = archive_entries
        self.original_dds_root = original_dds_root
        self.archive_index = archive_index
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            archive_entries = list(self.archive_entries)
            active_index = self.archive_index
            if active_index is None:
                self.stage_message.emit("Indexing archive and original DDS files...")
                active_index = build_replace_assistant_archive_index(
                    archive_entries,
                    original_dds_root=self.original_dds_root,
                    on_progress=self.progress.emit,
                )
            if self.stop_event.is_set():
                return
            self.stage_message.emit("Matching imported files to original DDS entries...")
            total = len(self.items)
            for index, item in enumerate(self.items, start=1):
                if self.stop_event.is_set():
                    return
                source_path = item.source_path.expanduser().resolve()
                self.progress.emit(index - 1, total, f"[{index}/{total}] Matching {source_path.name}")
                matched = match_replace_assistant_original(source_path, active_index)
                if matched.archive_entry is not None or matched.original_dds_path is not None:
                    item.matched_original = matched
                    item.detected_package_root = matched.package_root
                    item.detected_relative_path = matched.archive_relative_path
                    item.status = "matched"
                    item.status_detail = matched.match_reason
                    item.warning = matched.match_reason if matched.match_reason.startswith("ambiguous") else ""
                else:
                    item.matched_original = None
                    item.status = "unresolved"
                    item.status_detail = matched.match_reason or "unmatched"
                    item.warning = matched.match_reason if matched.match_reason.startswith("ambiguous") else ""
            if not self.stop_event.is_set():
                self.progress.emit(total, total, f"{total} / {total}")
                self.completed.emit(
                    {
                        "items": self.items,
                        "archive_index": active_index,
                        "original_dds_root": self.original_dds_root,
                    }
                )
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(str(exc))
        finally:
            self.finished.emit()


class ReplaceAssistantReviewCompareWorker(QObject):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request_id: int, texconv_path: Optional[Path], item: ReplaceAssistantReviewItem) -> None:
        super().__init__()
        self.request_id = request_id
        self.texconv_path = texconv_path
        self.item = item
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def _collect_source_metadata(self, path: Path) -> Dict[str, str]:
        resolved = path.expanduser().resolve()
        suffix = resolved.suffix.lower()
        metadata: Dict[str, str] = {
            "kind": suffix.lstrip(".").upper() or "FILE",
            "path": str(resolved),
        }
        if suffix == ".dds":
            try:
                dds_info = parse_dds(resolved)
                metadata.update(
                    {
                        "format": dds_info.texconv_format,
                        "size": f"{dds_info.width}x{dds_info.height}",
                        "mips": str(dds_info.mip_count),
                    }
                )
            except Exception:
                pass
            return metadata

        reader = QImageReader(str(resolved))
        size = reader.size()
        if size.isValid():
            metadata["size"] = f"{size.width()}x{size.height()}"
        format_bytes = reader.format()
        image_format = bytes(format_bytes).decode("ascii", errors="ignore").upper().strip()
        if image_format:
            metadata["format"] = image_format
        return metadata

    def _collect_dds_metadata(self, path: Optional[Path]) -> Optional[Dict[str, str]]:
        if path is None:
            return None
        resolved = path.expanduser().resolve()
        if not resolved.exists():
            return None
        try:
            dds_info = parse_dds(resolved)
        except Exception:
            return None
        return {
            "path": str(resolved),
            "format": dds_info.texconv_format,
            "size": f"{dds_info.width}x{dds_info.height}",
            "mips": str(dds_info.mip_count),
        }

    def _build_comparison_rows(
        self,
        *,
        source_metadata: Dict[str, str],
        original_metadata: Optional[Dict[str, str]],
        output_metadata: Optional[Dict[str, str]],
    ) -> List[tuple[str, str]]:
        rows: List[tuple[str, str]] = [
            ("Build mode", "Upscale with NCNN, then rebuild" if self.item.build_mode == "upscale_then_rebuild" else "Rebuild only"),
            ("Size mode", "Match original size" if self.item.size_mode == "match_original" else "Use edited size"),
        ]
        if original_metadata is not None and output_metadata is not None:
            rows.append(
                (
                    "Format",
                    "Matches original" if original_metadata.get("format") == output_metadata.get("format") else f"{original_metadata.get('format', '?')} -> {output_metadata.get('format', '?')}",
                )
            )
            rows.append(
                (
                    "Resolution",
                    "Matches original" if original_metadata.get("size") == output_metadata.get("size") else f"{original_metadata.get('size', '?')} -> {output_metadata.get('size', '?')}",
                )
            )
            rows.append(
                (
                    "Mip count",
                    "Matches original" if original_metadata.get("mips") == output_metadata.get("mips") else f"{original_metadata.get('mips', '?')} -> {output_metadata.get('mips', '?')}",
                )
            )
        if source_metadata.get("size") and output_metadata is not None:
            rows.append(
                (
                    "Edited source vs output",
                    "Same size" if source_metadata.get("size") == output_metadata.get("size") else f"{source_metadata.get('size', '?')} -> {output_metadata.get('size', '?')}",
                )
            )
        return rows

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            source_metadata = self._collect_source_metadata(self.item.source_path)
            original_metadata = self._collect_dds_metadata(self.item.original_dds_path)
            source_preview_path, source_meta, source_detail = build_replace_assistant_preview_assets(
                self.texconv_path,
                self.item.source_path,
            )
            source_image = None
            if source_preview_path and not self.stop_event.is_set():
                reader = QImageReader(source_preview_path)
                image = reader.read()
                if not image.isNull():
                    source_image = image
            output_result = build_compare_preview_pane_result(
                self.texconv_path,
                self.item.output_dds_path,
                "Rebuilt DDS not found.",
                stop_event=self.stop_event,
            )
            output_metadata = self._collect_dds_metadata(self.item.output_dds_path)
            output_image = None
            if output_result.preview_png_path and not self.stop_event.is_set():
                reader = QImageReader(output_result.preview_png_path)
                image = reader.read()
                if not image.isNull():
                    output_image = image
            payload = {
                "item": self.item,
                "source_preview_path": source_preview_path,
                "source_meta": source_meta,
                "source_detail": source_detail,
                "source_image": source_image,
                "source_metadata": source_metadata,
                "original_metadata": original_metadata,
                "output_result": output_result,
                "output_image": output_image,
                "output_metadata": output_metadata,
                "comparison_rows": self._build_comparison_rows(
                    source_metadata=source_metadata,
                    original_metadata=original_metadata,
                    output_metadata=output_metadata,
                ),
            }
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, payload)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, str(exc))
        finally:
            self.finished.emit()


class ReplaceAssistantUIConstraintWorker(QObject):
    completed = Signal(int, str, str)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request_id: int, entries: Sequence[ArchiveEntry], target_path: str) -> None:
        super().__init__()
        self.request_id = request_id
        self.entries = entries
        self.target_path = target_path
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            summary = summarize_ui_reference_constraints(self.entries, self.target_path, stop_event=self.stop_event)
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, self.target_path, str(summary.get("warning_text", "") or ""))
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, str(exc))
        finally:
            self.finished.emit()
