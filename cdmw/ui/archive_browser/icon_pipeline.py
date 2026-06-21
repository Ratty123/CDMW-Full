"""Archive browser icon warmup pipeline boundary."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QRectF, Qt, QThread, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

from cdmw.core.archive import load_archive_item_icon_thumbnail_cache
from cdmw.workers.archive_workers import ArchiveItemIconWarmupWorker

@dataclass(frozen=True, slots=True)
class VisibleIconWarmupRequest:
    first_row: int
    last_row: int


class ArchiveIconPipelineMixin:
    """Item Finder icon cache, preload, and background warmup orchestration."""

    def _build_archive_asset_catalog_icon(self, category: str, label: str = "") -> QIcon:
        key = str(category or "Item").strip().lower()
        letter = (str(label or category or "I").strip()[:1] or "I").upper()
        cache_key = (key, letter)
        cached_icon = self.archive_asset_catalog_fallback_icon_cache.get(cache_key)
        if cached_icon is not None:
            self.archive_asset_catalog_fallback_icon_cache.move_to_end(cache_key)
            return cached_icon
        colors = {
            "weapon": ("#ff9f43", "#3b2412"),
            "armor": ("#4aa3ff", "#122538"),
            "accessory": ("#f6c177", "#35260f"),
            "mount / pet": ("#6bd17d", "#142d1a"),
            "material": ("#c5a3ff", "#251939"),
            "consumable": ("#7ee787", "#112b1a"),
            "crafting / recipe": ("#8bd3dd", "#102b32"),
            "tool": ("#ffd166", "#3b3214"),
            "character customization": ("#ffb3c6", "#351620"),
            "gimmick / interactive": ("#ff7b72", "#351514"),
            "housing / prop": ("#a7c957", "#23300f"),
            "quest / document": ("#f28482", "#351919"),
            "progression / reward": ("#d0bfff", "#251a3a"),
            "item": ("#9fb3c8", "#17212b"),
        }
        fg, bg = colors.get(key, colors["item"])
        pixmap = QPixmap(34, 34)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(fg), 1.4))
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(2, 2, 30, 30, 6, 6)
        painter.setBrush(QColor(fg))
        if key == "weapon":
            path = QPainterPath()
            path.moveTo(23, 6)
            path.lineTo(28, 11)
            path.lineTo(13, 26)
            path.lineTo(9, 22)
            path.closeSubpath()
            painter.drawPath(path)
            painter.drawRect(7, 23, 10, 3)
        elif key == "armor":
            path = QPainterPath()
            path.moveTo(17, 7)
            path.lineTo(26, 11)
            path.lineTo(23, 27)
            path.lineTo(11, 27)
            path.lineTo(8, 11)
            path.closeSubpath()
            painter.drawPath(path)
        elif key == "mount / pet":
            painter.drawEllipse(QRectF(8, 11, 18, 13))
            painter.drawEllipse(QRectF(20, 8, 7, 7))
            painter.drawRect(9, 22, 4, 6)
            painter.drawRect(20, 22, 4, 6)
        elif key == "material":
            painter.drawEllipse(QRectF(8, 8, 18, 18))
            painter.setBrush(QColor(bg))
            painter.drawEllipse(QRectF(13, 13, 8, 8))
        elif key == "tool":
            painter.drawRect(9, 21, 17, 4)
            painter.drawRect(20, 8, 4, 17)
        elif key == "quest / document":
            painter.drawRect(10, 7, 15, 20)
            painter.setPen(QPen(QColor(bg), 1.2))
            painter.drawLine(13, 13, 22, 13)
            painter.drawLine(13, 18, 22, 18)
        else:
            painter.setPen(QColor(fg))
            font = QFont(painter.font())
            font.setBold(True)
            font.setPointSize(13)
            painter.setFont(font)
            painter.drawText(QRectF(2, 2, 30, 30), Qt.AlignCenter, letter)
        painter.end()
        icon = QIcon(pixmap)
        self.archive_asset_catalog_fallback_icon_cache[cache_key] = icon
        self.archive_asset_catalog_fallback_icon_cache.move_to_end(cache_key)
        while len(self.archive_asset_catalog_fallback_icon_cache) > 128:
            self.archive_asset_catalog_fallback_icon_cache.popitem(last=False)
        return icon

    def _archive_asset_catalog_icon_cache_key(
        self,
        row: Mapping[str, object],
        size: int,
    ) -> Tuple[Tuple[str, ...], int, str]:
        icon_paths = tuple(self._archive_asset_catalog_row_values(row, "icon_paths"))
        texconv_key = self.texconv_path_edit.text().strip()
        return icon_paths, max(1, int(size)), texconv_key

    def _archive_asset_catalog_prepared_icon_cache_key(
        self,
        row: Mapping[str, object],
    ) -> Tuple[Tuple[str, ...], str]:
        icon_paths = tuple(self._archive_asset_catalog_row_values(row, "icon_paths"))
        texconv_key = self.texconv_path_edit.text().strip()
        return icon_paths, texconv_key

    def _current_archive_package_root(self) -> Path:
        text = str(self.archive_package_root_edit.text() or "").strip()
        return Path(text).expanduser() if text else Path.cwd()

    def _archive_item_icon_converter_cache_key(self) -> str:
        texconv_text = self.texconv_path_edit.text().strip()
        parts = [f"texconv={texconv_text}"]
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

    def _prime_archive_asset_catalog_icon_prepared_cache_from_persistent(
        self,
        row: Mapping[str, object],
        *,
        size: int = 120,
    ) -> bool:
        prepared_key = self._archive_asset_catalog_prepared_icon_cache_key(row)
        icon_paths, _texconv_key = prepared_key
        if not icon_paths:
            return False
        prepared = self.archive_item_icon_prepared_path_cache.get(prepared_key)
        if prepared is not None:
            preview_path_text, _prepared_note = prepared
            try:
                if Path(preview_path_text).is_file() and Path(preview_path_text).stat().st_size > 0:
                    return True
            except OSError:
                pass
            self.archive_item_icon_prepared_path_cache.pop(prepared_key, None)
        if self._archive_item_icon_lookup_index_missing():
            return False
        package_root = self._current_archive_package_root()
        converter_key = self._archive_item_icon_converter_cache_key()
        for icon_path in icon_paths:
            entries = self._resolve_archive_asset_catalog_path_candidates(
                icon_path,
                fallback_extensions=(".dds", ".png"),
            )
            for entry in entries[:4]:
                cached = load_archive_item_icon_thumbnail_cache(
                    package_root,
                    self.archive_cache_root,
                    icon_paths,
                    entry,
                    size=size,
                    converter_key=converter_key,
                )
                if cached is None:
                    continue
                preview_path, note = cached
                self.archive_item_icon_prepared_path_cache[prepared_key] = (str(preview_path), str(note or "Recovered inventory icon"))
                self.archive_item_icon_prepared_path_cache.move_to_end(prepared_key)
                while len(self.archive_item_icon_prepared_path_cache) > self.archive_item_icon_prepared_cache_limit:
                    self.archive_item_icon_prepared_path_cache.popitem(last=False)
                self.archive_item_icon_negative_cache.pop(prepared_key, None)
                return True
        return False

    def _archive_item_icon_negative_note(
        self,
        prepared_key: Tuple[Tuple[str, ...], str],
    ) -> str:
        cached = self.archive_item_icon_negative_cache.get(prepared_key)
        if cached is None:
            return ""
        recorded_at, note = cached
        if time.monotonic() - float(recorded_at or 0.0) > 300.0:
            self.archive_item_icon_negative_cache.pop(prepared_key, None)
            return ""
        self.archive_item_icon_negative_cache.move_to_end(prepared_key)
        return str(note or "Icon preview could not be prepared.")

    def _remember_archive_item_icon_negative(
        self,
        prepared_key: Tuple[Tuple[str, ...], str],
        note: str,
    ) -> None:
        self._forget_archive_item_icon_pixmap_cache(prepared_key)
        self.archive_item_icon_negative_cache[prepared_key] = (
            time.monotonic(),
            str(note or "Icon preview could not be prepared."),
        )
        self.archive_item_icon_negative_cache.move_to_end(prepared_key)
        while len(self.archive_item_icon_negative_cache) > self.archive_item_icon_prepared_cache_limit:
            self.archive_item_icon_negative_cache.popitem(last=False)

    def _forget_archive_item_icon_pixmap_cache(
        self,
        prepared_key: Tuple[Tuple[str, ...], str],
    ) -> None:
        icon_paths, texconv_key = prepared_key
        stale_keys = [
            cache_key
            for cache_key in self.archive_item_icon_pixmap_cache
            if cache_key[0] == icon_paths and cache_key[2] == texconv_key
        ]
        for cache_key in stale_keys:
            self.archive_item_icon_pixmap_cache.pop(cache_key, None)

    def _clear_archive_asset_catalog_icon_cache(self) -> None:
        self.archive_item_icon_warmup_generation += 1
        self.archive_item_icon_preload_timer.stop()
        self.archive_item_icon_preload_queue.clear()
        self.archive_item_icon_preload_next_index = 0
        self.archive_item_icon_visible_warmup_remaining = 0
        self.archive_item_icon_warmup_user_visible = False
        self.archive_item_icon_priority_queue.clear()
        if self.archive_item_icon_warmup_worker is not None:
            try:
                self.archive_item_icon_warmup_worker.stop()
            except Exception:
                pass
        if self.archive_item_icon_priority_worker is not None:
            try:
                self.archive_item_icon_priority_worker.stop()
            except Exception:
                pass
        self.archive_item_icon_pixmap_cache.clear()
        self.archive_item_icon_prepared_path_cache.clear()
        self.archive_item_icon_negative_cache.clear()

    def _cached_archive_asset_catalog_inventory_icon_pixmap(
        self,
        row: Mapping[str, object],
        size: int = 48,
        *,
        allow_sync_prepare: bool = False,
    ) -> Tuple[Optional[QPixmap], str]:
        cache_key = self._archive_asset_catalog_icon_cache_key(row, size)
        icon_paths, requested_size, texconv_key = cache_key
        if not icon_paths:
            return None, "No recovered inventory icon could be resolved for this row."
        cached = self.archive_item_icon_pixmap_cache.get(cache_key)
        if cached is not None:
            cached_pixmap, _cached_note = cached
            if cached_pixmap is None or cached_pixmap.isNull():
                self.archive_item_icon_pixmap_cache.pop(cache_key, None)
            else:
                self.archive_item_icon_pixmap_cache.move_to_end(cache_key)
                return cached
        prepared_key = (icon_paths, texconv_key)
        prepared = self.archive_item_icon_prepared_path_cache.get(prepared_key)
        if prepared is not None:
            self.archive_item_icon_prepared_path_cache.move_to_end(prepared_key)
            preview_path_text, prepared_note = prepared
            preview_path = Path(preview_path_text)
            try:
                prepared_exists = preview_path.is_file() and preview_path.stat().st_size > 0
            except OSError:
                prepared_exists = False
            if prepared_exists:
                pixmap = QPixmap(str(preview_path))
                if not pixmap.isNull():
                    scaled_value = (
                        pixmap.scaled(requested_size, requested_size, Qt.KeepAspectRatio, Qt.SmoothTransformation),
                        prepared_note,
                    )
                    self.archive_item_icon_pixmap_cache[cache_key] = scaled_value
                    self.archive_item_icon_pixmap_cache.move_to_end(cache_key)
                    while len(self.archive_item_icon_pixmap_cache) > self.archive_item_icon_pixmap_cache_limit:
                        self.archive_item_icon_pixmap_cache.popitem(last=False)
                    return scaled_value
            self.archive_item_icon_prepared_path_cache.pop(prepared_key, None)
        for (cached_icon_paths, _cached_size, cached_texconv_key), cached_value in reversed(
            list(self.archive_item_icon_pixmap_cache.items())
        ):
            if cached_icon_paths != icon_paths or cached_texconv_key != texconv_key:
                continue
            cached_pixmap, cached_note = cached_value
            if cached_pixmap is None or cached_pixmap.isNull():
                self.archive_item_icon_pixmap_cache.pop((cached_icon_paths, _cached_size, cached_texconv_key), None)
                continue
            scaled_value = (
                cached_pixmap.scaled(requested_size, requested_size, Qt.KeepAspectRatio, Qt.SmoothTransformation),
                cached_note,
            )
            self.archive_item_icon_pixmap_cache[cache_key] = scaled_value
            self.archive_item_icon_pixmap_cache.move_to_end(cache_key)
            while len(self.archive_item_icon_pixmap_cache) > self.archive_item_icon_pixmap_cache_limit:
                self.archive_item_icon_pixmap_cache.popitem(last=False)
            return scaled_value
        if self._prime_archive_asset_catalog_icon_prepared_cache_from_persistent(row, size=120):
            return self._cached_archive_asset_catalog_inventory_icon_pixmap(
                row,
                requested_size,
                allow_sync_prepare=allow_sync_prepare,
            )
        negative_note = self._archive_item_icon_negative_note(prepared_key)
        if negative_note:
            return None, negative_note
        if not allow_sync_prepare:
            return None, "Icon preview is warming in the background."
        result = self._archive_asset_catalog_inventory_icon_pixmap(row, requested_size)
        pixmap, _note = result
        if pixmap is not None and not pixmap.isNull():
            self.archive_item_icon_pixmap_cache[cache_key] = result
            self.archive_item_icon_pixmap_cache.move_to_end(cache_key)
            while len(self.archive_item_icon_pixmap_cache) > self.archive_item_icon_pixmap_cache_limit:
                self.archive_item_icon_pixmap_cache.popitem(last=False)
        return result

    def _archive_item_icon_lookup_index_missing(self) -> bool:
        return bool(
            self.archive_entries
            and self.archive_item_asset_catalog
            and not (
                self.archive_entries_by_normalized_path
                and self.archive_entries_by_basename
            )
        )

    def _schedule_archive_asset_catalog_icon_preload(self, delay_ms: int = 900) -> None:
        if not self._archive_browser_background_work_allowed():
            self.archive_item_icon_preload_pending_after_ready = bool(self.archive_item_asset_catalog)
            return
        if self._archive_item_icon_lookup_index_missing():
            self.archive_item_icon_preload_pending_after_ready = bool(self.archive_item_asset_catalog)
            self._ensure_archive_basic_index_worker_started()
            return
        self.archive_item_icon_preload_pending_after_ready = False
        self.archive_item_icon_preload_timer.stop()
        self.archive_item_icon_preload_queue.clear()
        self.archive_item_icon_preload_next_index = 0
        if not self.archive_item_asset_catalog:
            return
        rows: List[Mapping[str, object]] = []
        for row in self.archive_item_asset_catalog:
            if not isinstance(row, Mapping):
                continue
            if not self._archive_asset_catalog_row_values(row, "icon_paths"):
                continue
            prepared_key = self._archive_asset_catalog_prepared_icon_cache_key(row)
            prepared = self.archive_item_icon_prepared_path_cache.get(prepared_key)
            if prepared is not None:
                preview_path_text, _prepared_note = prepared
                preview_path = Path(preview_path_text)
                try:
                    if preview_path.is_file() and preview_path.stat().st_size > 0:
                        continue
                except OSError:
                    pass
                self.archive_item_icon_prepared_path_cache.pop(prepared_key, None)
            if self._archive_item_icon_negative_note(prepared_key):
                continue
            rows.append(row)
            if len(rows) >= self.archive_item_icon_preload_limit:
                break
        self._queue_archive_asset_catalog_icon_warmup_rows(rows, replace=True, delay_ms=delay_ms)

    def _queue_archive_asset_catalog_icon_warmup_rows(
        self,
        rows: Sequence[Mapping[str, object]],
        *,
        replace: bool = False,
        front: bool = False,
        user_visible: bool = False,
        delay_ms: int = 0,
    ) -> None:
        if replace:
            self.archive_item_icon_preload_timer.stop()
            self.archive_item_icon_preload_queue.clear()
            self.archive_item_icon_preload_next_index = 0
            self.archive_item_icon_visible_warmup_remaining = 0
        if not rows:
            return
        lookup_missing = self._archive_item_icon_lookup_index_missing()
        visible_request = bool(front or user_visible)
        existing_keys = {
            self._archive_asset_catalog_prepared_icon_cache_key(row)
            for row in self.archive_item_icon_preload_queue
            if isinstance(row, Mapping)
        }
        queued_rows: List[Dict[str, object]] = []
        requested_keys: List[Tuple[Tuple[str, ...], str]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            prepared_key = self._archive_asset_catalog_prepared_icon_cache_key(row)
            icon_paths, _texconv_key = prepared_key
            if not icon_paths:
                continue
            prepared = self.archive_item_icon_prepared_path_cache.get(prepared_key)
            if prepared is not None:
                preview_path_text, _prepared_note = prepared
                preview_path = Path(preview_path_text)
                try:
                    if preview_path.is_file() and preview_path.stat().st_size > 0:
                        continue
                except OSError:
                    pass
                self.archive_item_icon_prepared_path_cache.pop(prepared_key, None)
            if not lookup_missing and self._archive_item_icon_negative_note(prepared_key):
                continue
            requested_keys.append(prepared_key)
            if prepared_key in existing_keys:
                continue
            existing_keys.add(prepared_key)
            queued_rows.append(dict(row))
        if visible_request and requested_keys:
            self.archive_item_icon_visible_warmup_remaining = max(
                int(getattr(self, "archive_item_icon_visible_warmup_remaining", 0) or 0),
                min(240, len(requested_keys)),
            )
            if (
                self.archive_item_icon_warmup_thread is not None
                and not bool(getattr(self, "archive_item_icon_warmup_user_visible", False))
                and self.archive_item_icon_warmup_worker is not None
            ):
                try:
                    self.archive_item_icon_warmup_worker.stop()
                except Exception:
                    pass
        promoted_rows: List[Dict[str, object]] = []
        if front and requested_keys and self.archive_item_icon_preload_queue:
            requested_key_set = set(requested_keys)
            retained_queue: List[Dict[str, object]] = []
            for queued_row in self.archive_item_icon_preload_queue:
                queued_key = self._archive_asset_catalog_prepared_icon_cache_key(queued_row)
                if queued_key in requested_key_set:
                    promoted_rows.append(queued_row)
                else:
                    retained_queue.append(queued_row)
            self.archive_item_icon_preload_queue[:] = retained_queue
        if visible_request and (queued_rows or promoted_rows):
            priority_rows = queued_rows + promoted_rows if front else promoted_rows + queued_rows
            self._queue_archive_asset_catalog_priority_icon_warmup_rows(priority_rows, front=True)
            if lookup_missing:
                self.archive_item_icon_preload_pending_after_ready = True
                self._ensure_archive_basic_index_worker_started()
                return
            return
        if not queued_rows:
            if promoted_rows:
                self.archive_item_icon_preload_queue[0:0] = promoted_rows
            if lookup_missing and requested_keys:
                self.archive_item_icon_preload_pending_after_ready = True
                self._ensure_archive_basic_index_worker_started()
                return
            if (
                visible_request
                and (promoted_rows or self.archive_item_icon_preload_queue)
                and not self.archive_item_icon_preload_timer.isActive()
                and self.archive_item_icon_warmup_thread is None
            ):
                self.archive_item_icon_preload_timer.start(max(0, int(delay_ms)))
            return
        if front:
            self.archive_item_icon_preload_queue[0:0] = queued_rows + promoted_rows
        else:
            self.archive_item_icon_preload_queue.extend(queued_rows)
        if lookup_missing:
            self.archive_item_icon_preload_pending_after_ready = True
            self._ensure_archive_basic_index_worker_started()
            return
        if not self.archive_item_icon_preload_timer.isActive() and self.archive_item_icon_warmup_thread is None:
            self.archive_item_icon_preload_timer.start(max(0, int(delay_ms)))

    def _queue_archive_asset_catalog_priority_icon_warmup_rows(
        self,
        rows: Sequence[Mapping[str, object]],
        *,
        front: bool = True,
    ) -> None:
        if not rows:
            return
        existing_keys = {
            self._archive_asset_catalog_prepared_icon_cache_key(row)
            for row in self.archive_item_icon_priority_queue
            if isinstance(row, Mapping)
        }
        priority_rows: List[Dict[str, object]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            prepared_key = self._archive_asset_catalog_prepared_icon_cache_key(row)
            icon_paths, _texconv_key = prepared_key
            if not icon_paths or prepared_key in existing_keys:
                continue
            prepared = self.archive_item_icon_prepared_path_cache.get(prepared_key)
            if prepared is not None:
                preview_path_text, _prepared_note = prepared
                preview_path = Path(preview_path_text)
                try:
                    if preview_path.is_file() and preview_path.stat().st_size > 0:
                        continue
                except OSError:
                    pass
                self.archive_item_icon_prepared_path_cache.pop(prepared_key, None)
            if not self._archive_item_icon_lookup_index_missing() and self._archive_item_icon_negative_note(prepared_key):
                continue
            existing_keys.add(prepared_key)
            priority_rows.append(dict(row))
        if not priority_rows:
            if self.archive_item_icon_priority_queue:
                self._start_archive_item_icon_priority_warmup()
            return
        if front:
            self.archive_item_icon_priority_queue[0:0] = priority_rows
        else:
            self.archive_item_icon_priority_queue.extend(priority_rows)
        self._start_archive_item_icon_priority_warmup()

    def _start_archive_item_icon_priority_warmup(self) -> None:
        if self._shutting_down or not self.archive_item_icon_priority_queue:
            return
        if self._archive_item_icon_lookup_index_missing():
            self.archive_item_icon_preload_pending_after_ready = True
            self._ensure_archive_basic_index_worker_started()
            return
        if self.archive_item_icon_priority_thread is not None:
            return
        batch = self.archive_item_icon_priority_queue[:16]
        del self.archive_item_icon_priority_queue[:16]
        texconv_text = self.texconv_path_edit.text().strip()
        texconv_path = Path(texconv_text).expanduser() if texconv_text else None
        if texconv_path is not None and not texconv_path.exists():
            texconv_path = None
        package_root = self._current_archive_package_root()
        converter_key = self._archive_item_icon_converter_cache_key()
        generation = self.archive_item_icon_warmup_generation
        worker = ArchiveItemIconWarmupWorker(
            generation,
            batch,
            self.archive_entries_by_normalized_path,
            self.archive_entries_by_basename,
            package_root,
            self.archive_cache_root,
            texconv_key=texconv_text,
            thumbnail_converter_key=converter_key,
            texconv_path=texconv_path,
            max_dimension=120,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.icon_prepared.connect(self._handle_archive_item_icon_prepared)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda generation=generation: self._cleanup_archive_item_icon_priority_refs(generation))
        self.archive_item_icon_priority_thread = thread
        self.archive_item_icon_priority_worker = worker
        try:
            thread.start(QThread.LowPriority)
        except Exception:
            thread.start()

    def _continue_archive_asset_catalog_icon_preload(self) -> None:
        if not self.archive_item_icon_preload_queue:
            return
        if self._archive_item_icon_lookup_index_missing():
            self.archive_item_icon_preload_pending_after_ready = True
            self._ensure_archive_basic_index_worker_started()
            return
        visible_remaining = int(getattr(self, "archive_item_icon_visible_warmup_remaining", 0) or 0)
        if not self._archive_browser_background_work_allowed() and visible_remaining <= 0:
            self.archive_item_icon_preload_pending_after_ready = True
            self.archive_item_icon_preload_timer.start(600)
            return
        if self.worker_thread is not None:
            self.archive_item_icon_preload_timer.start(600)
            return
        if self.archive_item_icon_warmup_thread is not None:
            return
        batch_size = 12 if visible_remaining > 0 else 8
        batch = self.archive_item_icon_preload_queue[:batch_size]
        del self.archive_item_icon_preload_queue[:batch_size]
        self.archive_item_icon_preload_next_index += len(batch)
        if visible_remaining > 0:
            self.archive_item_icon_visible_warmup_remaining = max(0, visible_remaining - len(batch))
        texconv_text = self.texconv_path_edit.text().strip()
        texconv_path = Path(texconv_text).expanduser() if texconv_text else None
        if texconv_path is not None and not texconv_path.exists():
            texconv_path = None
        package_root = self._current_archive_package_root()
        converter_key = self._archive_item_icon_converter_cache_key()
        generation = self.archive_item_icon_warmup_generation
        self.archive_item_icon_warmup_user_visible = visible_remaining > 0
        worker = ArchiveItemIconWarmupWorker(
            generation,
            batch,
            self.archive_entries_by_normalized_path,
            self.archive_entries_by_basename,
            package_root,
            self.archive_cache_root,
            texconv_key=texconv_text,
            thumbnail_converter_key=converter_key,
            texconv_path=texconv_path,
            max_dimension=120,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.icon_prepared.connect(self._handle_archive_item_icon_prepared)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda generation=generation: self._cleanup_archive_item_icon_warmup_refs(generation))
        self.archive_item_icon_warmup_thread = thread
        self.archive_item_icon_warmup_worker = worker
        try:
            thread.start(QThread.LowPriority)
        except Exception:
            thread.start()

    def _handle_archive_item_icon_prepared(
        self,
        generation: int,
        prepared_key: object,
        preview_path: str,
        note: str,
    ) -> None:
        if int(generation) != int(getattr(self, "archive_item_icon_warmup_generation", -1)):
            return
        if not isinstance(prepared_key, tuple) or len(prepared_key) != 2:
            return
        icon_paths_raw, texconv_key_raw = prepared_key
        if not isinstance(icon_paths_raw, tuple):
            return
        cache_key = (tuple(str(value) for value in icon_paths_raw), str(texconv_key_raw or ""))
        if not preview_path:
            self._remember_archive_item_icon_negative(cache_key, note)
            for callback in tuple(getattr(self, "archive_item_icon_prepared_callbacks", ()) or ()):
                try:
                    callback(cache_key)
                except Exception:
                    pass
            return
        self._forget_archive_item_icon_pixmap_cache(cache_key)
        self.archive_item_icon_prepared_path_cache[cache_key] = (str(preview_path), str(note or "Recovered inventory icon"))
        self.archive_item_icon_prepared_path_cache.move_to_end(cache_key)
        while len(self.archive_item_icon_prepared_path_cache) > self.archive_item_icon_prepared_cache_limit:
            self.archive_item_icon_prepared_path_cache.popitem(last=False)
        self.archive_item_icon_negative_cache.pop(cache_key, None)
        for callback in tuple(getattr(self, "archive_item_icon_prepared_callbacks", ()) or ()):
            try:
                callback(cache_key)
            except Exception:
                pass

    def _cleanup_archive_item_icon_warmup_refs(self, generation: int) -> None:
        self.archive_item_icon_warmup_thread = None
        self.archive_item_icon_warmup_worker = None
        self.archive_item_icon_warmup_user_visible = False
        if int(generation) == int(getattr(self, "archive_item_icon_warmup_generation", -1)):
            if self.archive_item_icon_preload_queue and not self._shutting_down:
                self.archive_item_icon_preload_timer.start(40)

    def _cleanup_archive_item_icon_priority_refs(self, generation: int) -> None:
        self.archive_item_icon_priority_thread = None
        self.archive_item_icon_priority_worker = None
        if int(generation) == int(getattr(self, "archive_item_icon_warmup_generation", -1)):
            if self.archive_item_icon_priority_queue and not self._shutting_down:
                QTimer.singleShot(0, self._start_archive_item_icon_priority_warmup)

    def _handle_archive_item_icon_inputs_changed(self, *_args: object) -> None:
        self._clear_archive_asset_catalog_icon_cache()
        if self.archive_item_asset_catalog:
            self._schedule_archive_asset_catalog_icon_preload(delay_ms=700)


__all__ = ["ArchiveIconPipelineMixin", "VisibleIconWarmupRequest"]
