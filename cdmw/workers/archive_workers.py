"""Archive worker extraction point."""

from __future__ import annotations

import gc
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal, Slot, Qt
from PySide6.QtGui import QImage, QImageReader

from cdmw.core.archive import (
    ArchiveNameSearchIndex,
    build_archive_name_search_index,
    ensure_archive_preview_source,
    build_archive_structure_children_map,
    load_archive_derived_index_cache,
    load_archive_item_icon_thumbnail_cache,
    load_or_update_archive_basic_index_shards,
    load_or_update_archive_name_search_shards,
    save_archive_basic_index_cache,
    save_archive_derived_index_cache,
    save_archive_item_icon_thumbnail_cache,
)
from cdmw.core.archive_accelerator import build_archive_basic_indexes_accelerated
from cdmw.core.item_index import build_archive_item_search_index
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.models import ArchiveEntry, RunCancelled


def _archive_item_icon_converter_cache_key(texconv_key: str) -> str:
    parts = [f"texconv={str(texconv_key or '')}"]
    try:
        from cdmw.core.texture_native import find_directxtex_texture_binary

        binary = find_directxtex_texture_binary()
    except Exception:
        binary = None
    if binary is None:
        parts.append("directxtex=missing")
    else:
        try:
            stat = binary.stat()
            parts.append(f"directxtex={binary.resolve()}:{stat.st_size}:{stat.st_mtime_ns}")
        except OSError:
            parts.append(f"directxtex={binary}:missing")
    return "|".join(parts)


def _normalize_shard_entry_signatures(value: object) -> Dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items() if str(key)}


def _normalize_shard_entry_counts(value: object) -> Dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    counts: Dict[str, int] = {}
    for key, item in value.items():
        key_text = str(key)
        if not key_text:
            continue
        try:
            counts[key_text] = int(item)
        except (TypeError, ValueError):
            continue
    return counts


class ArchiveDerivedIndexCacheWriteWorker(QObject):
    log_message = Signal(str)
    finished = Signal()

    def __init__(
        self,
        package_root: Path,
        cache_root: Path,
        entries: Sequence[ArchiveEntry],
        *,
        item_search_aliases: Optional[Mapping[str, str]] = None,
        item_display_names: Optional[Mapping[str, str]] = None,
        item_exact_display_names: Optional[Mapping[str, str]] = None,
        item_related_display_names: Optional[Mapping[str, str]] = None,
        item_asset_catalog: Optional[Sequence[Mapping[str, object]]] = None,
        archive_name_search_index: Optional[ArchiveNameSearchIndex] = None,
        entry_metadata_signature: str = "",
        entry_metadata_sources: Sequence[Tuple[object, object, object]] = (),
    ):
        super().__init__()
        self.package_root = package_root
        self.cache_root = cache_root
        self.entries = entries
        self.item_search_aliases = dict(item_search_aliases or {})
        self.item_display_names = dict(item_display_names or {})
        self.item_exact_display_names = dict(item_exact_display_names or {})
        self.item_related_display_names = dict(item_related_display_names or {})
        self.item_asset_catalog = [dict(row) for row in (item_asset_catalog or []) if isinstance(row, Mapping)]
        self.archive_name_search_index = archive_name_search_index
        self.entry_metadata_signature = str(entry_metadata_signature or "").strip()
        self.entry_metadata_sources = tuple(
            tuple(row)
            for row in (entry_metadata_sources or ())
            if isinstance(row, (list, tuple)) and len(row) == 3
        )
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        gc_was_enabled = gc.isenabled()
        if gc_was_enabled:
            gc.disable()
        try:
            if self.stop_event.is_set():
                return
            self.log_message.emit("Saving archive search cache...")
            timings: Dict[str, float] = {}
            save_archive_derived_index_cache(
                self.package_root,
                self.cache_root,
                self.entries,
                item_search_aliases=self.item_search_aliases,
                item_display_names=self.item_display_names,
                item_exact_display_names=self.item_exact_display_names,
                item_related_display_names=self.item_related_display_names,
                item_asset_catalog=self.item_asset_catalog,
                archive_name_search_index=self.archive_name_search_index,
                entry_metadata_signature=self.entry_metadata_signature or None,
                entry_metadata_sources=self.entry_metadata_sources or None,
                on_log=self.log_message.emit,
                timings=timings,
            )
            elapsed = float(timings.get("derived_cache_write_s", 0.0) or 0.0)
            self.log_message.emit(f"Archive search cache saved in {elapsed:.2f}s.")
        except Exception as exc:
            self.log_message.emit(f"Warning: archive search cache could not be saved: {exc}")
        finally:
            if gc_was_enabled:
                gc.enable()
            self.finished.emit()

class ArchiveBasicIndexWorker(QObject):
    log_message = Signal(str)
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        package_root: Path,
        cache_root: Path,
        entries: Sequence[ArchiveEntry],
        *,
        native_archive_acceleration: bool,
        request_id: int = 0,
        entry_metadata_signature: str = "",
        entry_metadata_sources: Sequence[Tuple[object, object, object]] = (),
        shard_entry_signatures: Optional[Mapping[str, str]] = None,
        shard_entry_counts: Optional[Mapping[str, int]] = None,
    ) -> None:
        super().__init__()
        self.package_root = package_root
        self.cache_root = cache_root
        self.entries = entries
        self.native_archive_acceleration = bool(native_archive_acceleration)
        self.request_id = int(request_id)
        self.entry_metadata_signature = str(entry_metadata_signature or "").strip()
        self.entry_metadata_sources = tuple(
            tuple(row)
            for row in (entry_metadata_sources or ())
            if isinstance(row, (list, tuple)) and len(row) == 3
        )
        self.shard_entry_signatures = _normalize_shard_entry_signatures(shard_entry_signatures)
        self.shard_entry_counts = _normalize_shard_entry_counts(shard_entry_counts)
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        started_at = time.perf_counter()
        try:
            self.log_message.emit("Checking archive path lookup cache in background...")
            self.progress_changed.emit(0, 0, "Checking archive path lookup cache in background...")
            try:
                basic_cache = load_or_update_archive_basic_index_shards(
                    self.package_root,
                    self.cache_root,
                    self.entries,
                    shard_entry_signatures=self.shard_entry_signatures,
                    shard_entry_counts=self.shard_entry_counts,
                    on_progress=self.progress_changed.emit,
                    on_log=self.log_message.emit,
                    stop_event=self.stop_event,
                )
            except Exception as exc:
                self.log_message.emit(f"Archive path lookup shard cache could not be used: {exc}")
                basic_cache = None
            if isinstance(basic_cache, Mapping):
                cached_path_index = basic_cache.get("path_index")
                cached_basename_index = basic_cache.get("basename_index")
                cached_extension_index = basic_cache.get("extension_index")
                cached_role_index = basic_cache.get("role_index")
                if (
                    isinstance(cached_path_index, Mapping)
                    and isinstance(cached_basename_index, Mapping)
                    and isinstance(cached_extension_index, Mapping)
                    and isinstance(cached_role_index, Mapping)
                ):
                    elapsed = max(0.0, float(time.perf_counter() - started_at))
                    self.completed.emit(
                        {
                            "path_index": cached_path_index,
                            "basename_index": cached_basename_index,
                            "extension_index": cached_extension_index,
                            "role_index": cached_role_index,
                            "native_used": False,
                            "cache_loaded": bool(basic_cache.get("cache_loaded", True)),
                            "cache_path": str(basic_cache.get("cache_path") or ""),
                            "elapsed_s": elapsed,
                            "request_id": self.request_id,
                        }
                    )
                    return
            self.log_message.emit("Building path lookup in background...")
            self.progress_changed.emit(0, 0, "Building path lookup in background...")
            path_index, basename_index, extension_index, role_index, native_used = build_archive_basic_indexes_accelerated(
                self.entries,
                native_enabled=self.native_archive_acceleration,
                on_progress=self.progress_changed.emit,
                stop_event=self.stop_event,
            )
            cache_path_text = ""
            try:
                cache_path = save_archive_basic_index_cache(
                    self.package_root,
                    self.cache_root,
                    self.entries,
                    path_index=path_index,
                    basename_index=basename_index,
                    extension_index=extension_index,
                    role_index=role_index,
                    entry_metadata_signature=self.entry_metadata_signature or None,
                    entry_metadata_sources=self.entry_metadata_sources or None,
                    on_log=self.log_message.emit,
                )
                cache_path_text = str(cache_path)
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.log_message.emit(f"Warning: path lookup cache could not be written: {exc}")
            elapsed = max(0.0, float(time.perf_counter() - started_at))
            self.completed.emit(
                {
                    "path_index": path_index,
                    "basename_index": basename_index,
                    "extension_index": extension_index,
                    "role_index": role_index,
                    "native_used": bool(native_used),
                    "cache_loaded": False,
                    "cache_path": cache_path_text,
                    "elapsed_s": elapsed,
                    "request_id": self.request_id,
                }
            )
        except RunCancelled as exc:
            if not self.stop_event.is_set():
                self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()

class ArchiveEnhancedIndexWorker(QObject):
    log_message = Signal(str)
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        package_root: Path,
        cache_root: Path,
        entries: Sequence[ArchiveEntry],
        *,
        request_id: int = 0,
        entry_metadata_signature: str = "",
        entry_metadata_sources: Sequence[Tuple[object, object, object]] = (),
        shard_entry_signatures: Optional[Mapping[str, str]] = None,
        shard_entry_counts: Optional[Mapping[str, int]] = None,
    ):
        super().__init__()
        self.package_root = package_root
        self.cache_root = cache_root
        self.entries = entries
        self.request_id = int(request_id)
        self.entry_metadata_signature = str(entry_metadata_signature or "").strip()
        self.entry_metadata_sources = tuple(
            tuple(row)
            for row in (entry_metadata_sources or ())
            if isinstance(row, (list, tuple)) and len(row) == 3
        )
        self.shard_entry_signatures = _normalize_shard_entry_signatures(shard_entry_signatures)
        self.shard_entry_counts = _normalize_shard_entry_counts(shard_entry_counts)
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        gc_was_enabled = gc.isenabled()
        if gc_was_enabled:
            gc.disable()
        try:
            self.log_message.emit("Loading archive search cache...")
            self.progress_changed.emit(0, 0, "Loading archive search cache...")
            derived_cache = load_archive_derived_index_cache(
                self.package_root,
                self.cache_root,
                self.entries,
                entry_metadata_signature=self.entry_metadata_signature or None,
                current_sources=self.entry_metadata_sources or None,
                load_name_search_index=True,
                shard_entry_signatures=self.shard_entry_signatures,
                shard_entry_counts=self.shard_entry_counts,
                on_progress=self.progress_changed.emit,
                on_log=self.log_message.emit,
            )
            if isinstance(derived_cache, Mapping) and isinstance(
                derived_cache.get("name_search_index"),
                ArchiveNameSearchIndex,
            ):
                self.completed.emit(
                    {
                        "item_search_aliases": dict(derived_cache.get("item_search_aliases", {}) or {}),
                        "item_display_names": dict(derived_cache.get("item_display_names", {}) or {}),
                        "item_exact_display_names": dict(derived_cache.get("item_exact_display_names", {}) or {}),
                        "item_related_display_names": dict(derived_cache.get("item_related_display_names", {}) or {}),
                        "item_asset_catalog": [
                            dict(row)
                            for row in (derived_cache.get("item_asset_catalog", []) or [])
                            if isinstance(row, Mapping)
                        ],
                        "name_search_index": derived_cache.get("name_search_index"),
                        "cache_loaded": True,
                        "request_id": self.request_id,
                    }
                )
                return
            self.log_message.emit("Preparing archive search cache (1/3): item links...")
            self.progress_changed.emit(0, 0, "Preparing archive search cache (1/3): item links...")
            item_index = build_archive_item_search_index(
                self.entries,
                on_log=self.log_message.emit,
                on_progress=self.progress_changed.emit,
                stop_event=self.stop_event,
            )
            item_search_aliases = dict(item_index.model_base_aliases)
            item_display_names = dict(getattr(item_index, "model_base_display_names", {}) or {})
            item_exact_display_names = dict(getattr(item_index, "model_base_exact_display_names", {}) or {})
            item_related_display_names = dict(getattr(item_index, "model_base_related_display_names", {}) or {})
            item_asset_catalog = [
                row.to_cache_dict()
                for row in getattr(item_index, "asset_catalog", [])
                if hasattr(row, "to_cache_dict")
            ]
            self.log_message.emit("Preparing archive search cache (2/3): path/name index...")
            name_search_index = load_or_update_archive_name_search_shards(
                self.package_root,
                self.cache_root,
                self.entries,
                item_search_aliases,
                load_name_search_index=True,
                shard_entry_signatures=self.shard_entry_signatures,
                shard_entry_counts=self.shard_entry_counts,
                on_progress=self.progress_changed.emit,
                on_log=self.log_message.emit,
                stop_event=self.stop_event,
            )
            if not isinstance(name_search_index, ArchiveNameSearchIndex):
                name_search_index = build_archive_name_search_index(
                    self.entries,
                    item_search_aliases=item_search_aliases,
                    on_progress=self.progress_changed.emit,
                    stop_event=self.stop_event,
                )
            self.completed.emit(
                {
                    "item_search_aliases": item_search_aliases,
                    "item_display_names": item_display_names,
                    "item_exact_display_names": item_exact_display_names,
                    "item_related_display_names": item_related_display_names,
                    "item_asset_catalog": item_asset_catalog,
                    "name_search_index": name_search_index,
                    "cache_loaded": False,
                    "request_id": self.request_id,
                }
            )
        except RunCancelled as exc:
            if not self.stop_event.is_set():
                self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if gc_was_enabled:
                gc.enable()
            self.finished.emit()

class ArchiveStructureFilterWorker(QObject):
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(self, entries: Sequence[ArchiveEntry]):
        super().__init__()
        self.entries = entries
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            structure_children = build_archive_structure_children_map(self.entries)
            if self.stop_event.is_set():
                return
            self.completed.emit({"structure_children": structure_children})
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(str(exc))
        finally:
            self.finished.emit()

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
        texconv_key: str = "",
        thumbnail_converter_key: str = "",
        texconv_path: Optional[Path] = None,
        max_dimension: int = 120,
    ) -> None:
        super().__init__()
        self.generation = int(generation)
        self.rows = [dict(row) for row in rows if isinstance(row, Mapping)]
        self.entries_by_normalized_path = entries_by_normalized_path
        self.entries_by_basename = entries_by_basename
        self.package_root = package_root
        self.cache_root = cache_root
        self.texconv_key = str(texconv_key or "")
        self.thumbnail_converter_key = str(thumbnail_converter_key or "")
        self.texconv_path = texconv_path
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
            prepared_key = (icon_paths, self.texconv_key)
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
                    timeout_seconds=45.0,
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
                        self.texconv_path,
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
            converter_key = self.thumbnail_converter_key or _archive_item_icon_converter_cache_key(self.texconv_key)
            emitted_keys: set[Tuple[Tuple[str, ...], str]] = set()
            pending_dds = self._collect_icon_sources(converter_key, emitted_keys)
            if pending_dds and not self.stop_event.is_set():
                self._prepare_dds_icons(pending_dds, converter_key, emitted_keys)
        finally:
            self.finished.emit(self.generation)



__all__ = [
    "ArchiveBasicIndexWorker",
    "ArchiveDerivedIndexCacheWriteWorker",
    "ArchiveEnhancedIndexWorker",
    "ArchiveItemIconWarmupWorker",
    "ArchiveStructureFilterWorker",
]
