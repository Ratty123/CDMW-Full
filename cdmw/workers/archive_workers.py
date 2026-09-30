"""Archive worker extraction point."""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Dict, List, Tuple

from PySide6.QtCore import QObject, Signal, Slot, Qt
from PySide6.QtGui import QImage, QImageReader

from cdmw.core.archive import (
    ensure_archive_preview_source,
    load_archive_item_icon_thumbnail_cache,
    save_archive_item_icon_thumbnail_cache,
)
from cdmw.core.texture_native import native_texture_backend_identity
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.models import ArchiveEntry


def _archive_item_icon_converter_cache_key() -> str:
    return native_texture_backend_identity()


class ArchiveItemIconWarmupWorker(QObject):
    icon_prepared = Signal(int, object, str, str, object)
    finished = Signal(int)

    def __init__(
        self,
        generation: int,
        rows: Sequence[Mapping[str, object]],
        entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]],
        entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
        package_root: Path,
        cache_root: Path,
        *,
        thumbnail_converter_key: str = "",
        max_dimension: int = 120,
    ) -> None:
        super().__init__()
        self.generation = int(generation)
        self.rows = [dict(row) for row in rows if isinstance(row, Mapping)]
        self.entries_by_normalized_path = entries_by_normalized_path
        self.entries_by_basename = entries_by_basename
        self.package_root = package_root
        self.cache_root = cache_root
        self.thumbnail_converter_key = str(thumbnail_converter_key or "")
        self.max_dimension = max(32, int(max_dimension or 120))
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @staticmethod
    def _row_values(row: Mapping[str, object], key: str) -> Tuple[str, ...]:
        raw = row.get(key)
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            return tuple(str(value) for value in raw if str(value or "").strip())
        return ()

    def _path_candidates(self, value: str) -> List[ArchiveEntry]:
        normalized = str(value or "").replace("\\", "/").strip()
        if not normalized:
            return []
        candidates: List[ArchiveEntry] = []
        seen: set[Tuple[str, str, int]] = set()

        def add_entry(entry: ArchiveEntry) -> None:
            key = (entry.path.lower(), str(entry.pamt_path).lower(), int(entry.offset))
            if key not in seen:
                seen.add(key)
                candidates.append(entry)

        def add_candidate(candidate: str) -> None:
            candidate = str(candidate or "").replace("\\", "/").strip()
            if not candidate:
                return
            candidate_lower = candidate.lower()
            for entry in self.entries_by_normalized_path.get(candidate_lower, ()):
                add_entry(entry)
            basename = PurePosixPath(candidate).name.strip().lower()
            if basename:
                for entry in self.entries_by_basename.get(basename, ()):
                    add_entry(entry)

        add_candidate(normalized)
        if not PurePosixPath(normalized).suffix:
            add_candidate(f"{normalized}.dds")
            add_candidate(f"{normalized}.png")
        return candidates

    def _decoded_preview_image(self, path: Path) -> QImage:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        source_size = reader.size()
        if source_size.isValid() and max(source_size.width(), source_size.height()) > self.max_dimension:
            reader.setScaledSize(
                source_size.scaled(
                    self.max_dimension,
                    self.max_dimension,
                    Qt.KeepAspectRatio,
                )
            )
        image = reader.read()
        if image.isNull():
            return image
        if max(image.width(), image.height()) > self.max_dimension:
            image = image.scaled(
                self.max_dimension,
                self.max_dimension,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        return image

    def _emit_prepared(
        self,
        prepared_key: Tuple[Tuple[str, ...], str],
        preview_path: Path,
        note: str,
        emitted_keys: set[Tuple[Tuple[str, ...], str]],
    ) -> bool:
        if prepared_key in emitted_keys:
            return True
        if self.stop_event.is_set():
            return False
        image = self._decoded_preview_image(preview_path)
        if image.isNull() or self.stop_event.is_set():
            return False
        emitted_keys.add(prepared_key)
        self.icon_prepared.emit(self.generation, prepared_key, str(preview_path), note, image)
        return True

    def _emit_missing(
        self,
        prepared_key: Tuple[Tuple[str, ...], str],
        note: str,
        emitted_keys: set[Tuple[Tuple[str, ...], str]],
    ) -> None:
        if prepared_key in emitted_keys or self.stop_event.is_set():
            return
        emitted_keys.add(prepared_key)
        self.icon_prepared.emit(self.generation, prepared_key, "", note, QImage())

    def _collect_icon_sources(
        self,
        converter_key: str,
        emitted_keys: set[Tuple[Tuple[str, ...], str]],
    ) -> List[Tuple[Tuple[Tuple[str, ...], str], ArchiveEntry, Path]]:
        pending_dds: List[Tuple[Tuple[Tuple[str, ...], str], ArchiveEntry, Path]] = []
        pending_dds_keys: set[Tuple[Tuple[str, ...], str]] = set()
        for row in self.rows:
            if self.stop_event.is_set():
                break
            icon_paths = self._row_values(row, "icon_paths")
            if not icon_paths:
                continue
            prepared_key = (icon_paths, native_texture_backend_identity())
            prepared_note = ""
            for icon_path in icon_paths:
                if self.stop_event.is_set():
                    break
                for entry in self._path_candidates(icon_path)[:4]:
                    if self.stop_event.is_set():
                        break
                    cached = load_archive_item_icon_thumbnail_cache(
                        self.package_root,
                        self.cache_root,
                        icon_paths,
                        entry,
                        size=self.max_dimension,
                        converter_key=converter_key,
                    )
                    if cached is not None and self._emit_prepared(
                        prepared_key,
                        cached[0],
                        cached[1],
                        emitted_keys,
                    ):
                        break
                    try:
                        source_path, _note = ensure_archive_preview_source(entry, stop_event=self.stop_event)
                    except Exception as exc:
                        if self.stop_event.is_set():
                            break
                        prepared_note = f"Recovered icon source could not be prepared: {exc}"
                        continue
                    if entry.extension == ".dds":
                        pending_dds.append((prepared_key, entry, source_path))
                        pending_dds_keys.add(prepared_key)
                        break
                    if source_path.exists():
                        prepared_note = f"Recovered inventory icon: {entry.path}"
                        try:
                            preview_path = save_archive_item_icon_thumbnail_cache(
                                self.package_root,
                                self.cache_root,
                                icon_paths,
                                entry,
                                source_path,
                                size=self.max_dimension,
                                converter_key=converter_key,
                                note=prepared_note,
                            )
                        except Exception:
                            preview_path = source_path
                        if self._emit_prepared(prepared_key, preview_path, prepared_note, emitted_keys):
                            break
                if prepared_key in emitted_keys:
                    break
            if prepared_key not in emitted_keys and prepared_key not in pending_dds_keys:
                self._emit_missing(
                    prepared_key,
                    prepared_note or "Recovered icon path could not be resolved in the loaded archive index.",
                    emitted_keys,
                )
        return pending_dds

    def _prepare_dds_icons(
        self,
        pending_dds: Sequence[Tuple[Tuple[Tuple[str, ...], str], ArchiveEntry, Path]],
        converter_key: str,
        emitted_keys: set[Tuple[Tuple[str, ...], str]],
    ) -> None:
        try:
            from cdmw.core.texture_native import ensure_directxtex_dds_preview_pngs
        except Exception:
            ensure_directxtex_dds_preview_pngs = None
        jobs = [
            {"dds_path": str(path), "max_dimension": self.max_dimension, "slot_kind": "base"}
            for _key, _entry, path in pending_dds
        ]
        batch_results: Dict[str, Path] = {}
        if ensure_directxtex_dds_preview_pngs is not None:
            try:
                batch_results = ensure_directxtex_dds_preview_pngs(
                    jobs,
                    stop_event=self.stop_event,
                )
            except Exception:
                batch_results = {}
        failed_notes: Dict[Tuple[Tuple[str, ...], str], str] = {}
        for prepared_key, entry, source_path in pending_dds:
            if self.stop_event.is_set():
                return
            if prepared_key in emitted_keys:
                continue
            try:
                batch_key = str(source_path.expanduser().resolve())
            except OSError:
                batch_key = str(source_path)
            preview_path = batch_results.get(batch_key)
            if preview_path is None:
                try:
                    preview_path = ensure_dds_display_preview_png(
                        source_path,
                        max_dimension=self.max_dimension,
                        slot_kind="base",
                        stop_event=self.stop_event,
                    )
                except Exception as exc:
                    if self.stop_event.is_set():
                        return
                    failed_notes.setdefault(
                        prepared_key,
                        f"Recovered icon DDS found, but thumbnail conversion failed: {exc}",
                    )
                    continue
            if not preview_path.exists():
                failed_notes.setdefault(
                    prepared_key,
                    "Recovered icon DDS found, but thumbnail conversion did not produce a preview.",
                )
                continue
            note = f"Recovered inventory icon: {entry.path}"
            try:
                cached_path = save_archive_item_icon_thumbnail_cache(
                    self.package_root,
                    self.cache_root,
                    prepared_key[0],
                    entry,
                    preview_path,
                    size=self.max_dimension,
                    converter_key=converter_key,
                    note=note,
                )
            except Exception:
                cached_path = preview_path
            if not self._emit_prepared(prepared_key, cached_path, note, emitted_keys):
                failed_notes.setdefault(prepared_key, "Recovered icon thumbnail could not be decoded.")
        for prepared_key, _entry, _source_path in pending_dds:
            if prepared_key not in emitted_keys:
                self._emit_missing(
                    prepared_key,
                    failed_notes.get(
                        prepared_key,
                        "Recovered icon path could not be resolved in the loaded archive index.",
                    ),
                    emitted_keys,
                )

    @Slot()
    def run(self) -> None:
        try:
            converter_key = self.thumbnail_converter_key or _archive_item_icon_converter_cache_key()
            emitted_keys: set[Tuple[Tuple[str, ...], str]] = set()
            pending_dds = self._collect_icon_sources(converter_key, emitted_keys)
            if pending_dds and not self.stop_event.is_set():
                self._prepare_dds_icons(pending_dds, converter_key, emitted_keys)
        finally:
            self.finished.emit(self.generation)


__all__ = [
    "ArchiveItemIconWarmupWorker",
]
