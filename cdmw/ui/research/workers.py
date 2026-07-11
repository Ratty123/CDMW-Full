"""Background workers for the Research tab."""

from __future__ import annotations

import dataclasses
import threading
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QImageReader

from cdmw.domain.research.contracts import (
    MipAnalysisRow,
    NormalValidationRow,
)
from cdmw.models import AppConfig, ArchiveEntry, ArchivePreviewResult
from cdmw.services.research_service import research_service

__all__ = [
    "ReferenceResolveWorker",
    "ResearchRefreshWorker",
    "UIConstraintRefreshWorker",
    "UnknownResolverPreviewWorker",
]


def shutdown_thread(thread: Optional[QThread], *, grace_ms: int = 2000, force_ms: int = 2000) -> None:
    del grace_ms, force_ms
    if thread is None:
        return
    try:
        thread.requestInterruption()
    except Exception:
        pass
    thread.quit()


class ResearchRefreshWorker(QObject):
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        *,
        archive_entries: Sequence[object],
        filtered_archive_entries: Sequence[object],
        sidecar_source_entries: Sequence[object],
        original_root: Optional[Path],
        output_root: Optional[Path],
        texconv_path: Optional[Path],
        app_config: Optional[AppConfig] = None,
        archive_snapshot_payload: Optional[Dict[str, object]] = None,
        ui_constraint_related_paths: Sequence[str] = (),
    ) -> None:
        super().__init__()
        self.archive_entries = archive_entries
        self.filtered_archive_entries = filtered_archive_entries
        self.sidecar_source_entries = sidecar_source_entries
        self.original_root = original_root
        self.output_root = output_root
        self.texconv_path = texconv_path
        self.app_config = app_config
        self.archive_snapshot_payload = dict(archive_snapshot_payload or {})
        self.ui_constraint_related_paths = [str(path) for path in ui_constraint_related_paths if isinstance(path, str)]
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            working_entries = self.filtered_archive_entries or self.archive_entries
            payload: Dict[str, object] = {}
            progress_total = 100

            def emit_snapshot_progress(current: int, total: int, detail: str) -> None:
                if total <= 0:
                    self.progress_changed.emit(0, progress_total, detail)
                    return
                mapped = int((min(max(current, 0), total) / total) * 65)
                self.progress_changed.emit(mapped, progress_total, detail)

            self.progress_changed.emit(0, progress_total, "Building archive research snapshot...")
            if self.archive_snapshot_payload:
                payload.update(self.archive_snapshot_payload)
            else:
                payload.update(
                    research_service.archive.build_snapshot(
                        working_entries,
                        sidecar_source_entries=self.sidecar_source_entries,
                        stop_event=self.stop_event,
                        on_progress=emit_snapshot_progress,
                    )
                )

            if self.stop_event.is_set():
                raise RuntimeError("Research refresh cancelled.")
            self.progress_changed.emit(66, progress_total, "Comparing original vs rebuilt mip behavior...")
            mip_rows: List[MipAnalysisRow] = []
            processing_plan_lookup: Dict[str, object] = {}
            if self.app_config is not None and self.original_root is not None and self.original_root.exists():
                try:
                    processing_plan_lookup = research_service.texture_analysis.processing_plan_lookup(
                        self.app_config,
                        original_root_override=self.original_root,
                        stop_event=self.stop_event,
                    )
                except Exception:
                    processing_plan_lookup = {}
            if self.original_root is not None and self.output_root is not None:
                if self.original_root.exists() and self.output_root.exists():
                    mip_family_members_by_path = research_service.texture_analysis.mip_family_members(
                        self.original_root,
                        self.output_root,
                        stop_event=self.stop_event,
                    )
                    mip_rows = research_service.texture_analysis.analyze_mips(
                        self.original_root,
                        self.output_root,
                        texconv_path=self.texconv_path,
                        processing_plan_lookup=processing_plan_lookup,
                        stop_event=self.stop_event,
                        family_members_by_path=mip_family_members_by_path,
                    )
                    payload["mip_detail_family_members_by_path"] = mip_family_members_by_path
            payload["mip_rows"] = mip_rows

            if self.stop_event.is_set():
                raise RuntimeError("Research refresh cancelled.")
            self.progress_changed.emit(82, progress_total, "Validating normal maps...")
            normal_rows: List[NormalValidationRow] = []
            if self.original_root is not None and self.original_root.exists():
                normal_rows.extend(
                    research_service.texture_analysis.validate_normals(
                        self.original_root,
                        root_label="Original DDS root",
                        texconv_path=self.texconv_path,
                        processing_plan_lookup=processing_plan_lookup,
                        stop_event=self.stop_event,
                    )
                )
            if self.output_root is not None and self.output_root.exists() and self.output_root != self.original_root:
                normal_rows.extend(
                    research_service.texture_analysis.validate_normals(
                        self.output_root,
                        root_label="Output root",
                        texconv_path=self.texconv_path,
                        processing_plan_lookup=processing_plan_lookup,
                        stop_event=self.stop_event,
                    )
                )
            normal_rows.sort(key=lambda row: (-row.issue_count, row.path))
            payload["normal_rows"] = normal_rows[:1500]

            if self.stop_event.is_set():
                raise RuntimeError("Research refresh cancelled.")
            self.progress_changed.emit(92, progress_total, "Building budget and residency risk analysis...")
            budget_payload: Dict[str, object] = {
                "budget_rows": [],
                "budget_class_rows": [],
                "budget_group_rows": [],
                "budget_profile": None,
            }
            if self.original_root is not None and self.output_root is not None:
                if self.original_root.exists() and self.output_root.exists():
                    budget_payload = research_service.texture_analysis.texture_budget(
                        self.original_root,
                        self.output_root,
                        processing_plan_lookup=processing_plan_lookup,
                        ui_constraint_related_paths=self.ui_constraint_related_paths,
                        stop_event=self.stop_event,
                    )
            payload.update(budget_payload)

            self.progress_changed.emit(progress_total, progress_total, "Research refresh complete.")
            self.completed.emit(payload)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class ReferenceResolveWorker(QObject):
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        *,
        archive_entries: Sequence[object],
        target_path: str,
    ) -> None:
        super().__init__()
        self.archive_entries = list(archive_entries)
        self.target_path = target_path
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            rows, stats = research_service.references.resolve_material_references(
                self.archive_entries,
                self.target_path,
                on_progress=self.progress_changed.emit,
                stop_event=self.stop_event,
            )
            if self.stop_event.is_set():
                raise RuntimeError("Reference resolve cancelled.")
            self.progress_changed.emit(1, 1, "Discovering archive sidecars...")
            sidecar_rows = research_service.references.discover_sidecars(
                self.archive_entries,
                self.target_path,
                stop_event=self.stop_event,
            )
            extract_paths = {self.target_path.strip().replace("\\", "/").strip("/")}
            for row in rows:
                if row.source_path:
                    extract_paths.add(row.source_path)
                if row.related_path:
                    extract_paths.add(row.related_path)
            for row in sidecar_rows:
                if row.related_path:
                    extract_paths.add(row.related_path)
            self.completed.emit(
                {
                    "target_path": self.target_path,
                    "reference_rows": rows,
                    "reference_stats": stats,
                    "sidecar_rows": sidecar_rows,
                    "extract_paths": sorted(path for path in extract_paths if path),
                }
            )
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class UIConstraintRefreshWorker(QObject):
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        *,
        archive_entries: Sequence[object],
    ) -> None:
        super().__init__()
        self.archive_entries = archive_entries
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            archive_entries = [entry for entry in self.archive_entries if isinstance(entry, ArchiveEntry)]
            rows = research_service.references.build_ui_constraint_rows(
                archive_entries,
                stop_event=self.stop_event,
                on_progress=self.progress_changed.emit,
            )
            if self.stop_event.is_set():
                raise RuntimeError("UI rect scan cancelled.")
            self.progress_changed.emit(1, 1, "UI rect scan complete.")
            self.completed.emit(rows)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class UnknownResolverPreviewWorker(QObject):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        texconv_path: Optional[Path],
        entry: Optional[ArchiveEntry],
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.texconv_path = texconv_path
        self.entry = entry
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            payload = research_service.preview.build_archive_preview(
                self.texconv_path,
                self.entry,
                stop_event=self.stop_event,
            )
            if self.stop_event.is_set():
                return
            payload = self._attach_loaded_images(payload)
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, payload)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, str(exc))
        finally:
            self.finished.emit()

    def _attach_loaded_images(self, result: ArchivePreviewResult) -> ArchivePreviewResult:
        preview_image = self._load_image(result.preview_image_path)
        if preview_image is None:
            return result
        return dataclasses.replace(result, preview_image=preview_image)

    def _load_image(self, image_path: str) -> object:
        if self.stop_event.is_set() or not image_path:
            return None
        reader = QImageReader(image_path)
        image = reader.read()
        if self.stop_event.is_set() or image.isNull():
            return None
        return image
