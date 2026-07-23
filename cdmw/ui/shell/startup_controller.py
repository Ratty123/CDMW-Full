"""Shell startup phase coordinator."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from cdmw.services.archive_environment_service import (
    invalidate_archive_browser_cache,
    resolve_crimson_desert_executable,
    sha256_file,
)
from cdmw.services.diagnostics_service import timing_value as _timing_value
from cdmw.ui.shell.startup_splash import (
    ExternalStartupSplashAdapter,
    close_pyinstaller_boot_splash,
    create_startup_splash,
    format_startup_splash_detail,
    make_startup_splash_pump,
)


_ARCHIVE_FIRST_PAINT_FALLBACK_SECONDS = 1.0


class StartupController:
    def __init__(self, context: object | None = None) -> None:
        self.context = context


def queue_startup_archive_autoload(
    window: object,
    startup_splash: object,
    _write_heartbeat: Callable[[str], None],
) -> None:
    window._show_startup_archive_path_prompt_if_needed(startup_splash)
    if window._startup_archive_autoload_expected():
        if bool(getattr(window, "_startup_archive_path_prompt_accepted", False)):
            startup_splash.set_detail(
                "Building archive cache. First load can take a while; let it finish.",
                1,
                100,
            )
            QTimer.singleShot(0, window._maybe_autoload_archive_on_startup)
        else:
            startup_splash.set_detail("Loading Archive Browser...")
        _write_heartbeat("archive_autoload_queued")
    else:
        _write_heartbeat("running")
        window._release_startup_splash()


class StartupPromptMixin:
    """Startup and missing archive path prompts for the shell window."""

    def _record_startup_prompt_event(self, event: str, **fields: object) -> None:
        recorder = getattr(self, "_record_runtime_event", None)
        if callable(recorder):
            recorder(event, **fields)

    def attach_startup_splash(self, splash: Optional[object], *, hold_main_window: bool = False) -> None:
        self._startup_splash_window = splash
        self._startup_splash_holds_main_window = bool(hold_main_window)
        self._startup_splash_released = False
        self._startup_splash_release_pending = False
        self._startup_splash_finish_pending = False
        self._startup_splash_finish_after_paint_deadline = 0.0
        self._startup_splash_last_progress_at = 0.0
        self._update_startup_splash("Preparing application...")

    def _update_startup_splash(self, detail: str, current: int = 0, total: int = 0) -> None:
        splash = getattr(self, "_startup_splash_window", None)
        if splash is None:
            return
        normalized = str(detail or "").strip().lower()
        if (
            (
                getattr(self, "_startup_splash_release_pending", False)
                or getattr(self, "_startup_splash_released", False)
            )
            and not normalized.startswith("opening workspace")
            and not normalized.startswith("archive ready")
        ):
            return
        try:
            splash.set_detail(detail, current, total)
        except Exception:
            pass

    def _startup_splash_progress_detail(self, detail: str) -> str:
        text = str(detail or "Working...").strip() or "Working..."
        if bool(getattr(self, "archive_startup_hold_until_ready", False)):
            text = text.replace(" in the background", "")
            text = text.replace(" in background", "")
            text = text.replace(" while the archive list stays available", "")
            text = text.replace(" after the archive list opens", "")
        return text

    def _archive_startup_progress_work_active(self) -> bool:
        return bool(
            self.worker_thread is not None
            or self.archive_basic_index_thread is not None
            or self.archive_enhanced_index_thread is not None
            or self.archive_derived_cache_thread is not None
            or self.archive_deferred_basic_index_start_pending
            or self.archive_deferred_enhanced_index_start_pending
            or self.archive_deferred_derived_cache_write_pending
            or self.archive_derived_cache_write_pending
        )

    def _show_main_window_after_startup_splash(self) -> None:
        if getattr(self, "_shutting_down", False):
            return
        if not self.isVisible():
            self.show()
            self._record_startup_prompt_event("main_window_shown")
        try:
            self.raise_()
            self.activateWindow()
        except Exception:
            pass
        splash = getattr(self, "_startup_splash_window", None)
        if splash is not None:
            try:
                splash.raise_()
                splash.activateWindow()
            except Exception:
                pass

    def _finish_startup_splash_now(self) -> None:
        splash = getattr(self, "_startup_splash_window", None)
        self._startup_splash_window = None
        self._startup_splash_holds_main_window = False
        self._startup_splash_finish_pending = False
        self._startup_splash_finish_after_paint_deadline = 0.0
        if splash is not None:
            try:
                splash.finish()
            except Exception:
                pass
            self._record_startup_prompt_event("splash_finished")
        try:
            from cdmw.app.startup_splash import close_external_startup_splash

            close_external_startup_splash()
        except Exception:
            pass

    def _finish_startup_splash_before_modal(self) -> None:
        if getattr(self, "_startup_splash_window", None) is None:
            return
        self._startup_splash_released = True
        self._startup_splash_release_pending = False
        try:
            self._show_main_window_after_startup_splash()
        except Exception:
            pass
        self._finish_startup_splash_now()
        app = QApplication.instance()
        if app is not None:
            try:
                app.processEvents()
            except Exception:
                pass

    def _startup_archive_first_paint_needed(self) -> bool:
        return bool(
            getattr(self, "archive_entries", None)
            and self._is_tool_visible_or_current(self.archive_browser_tab)
            and not self.archive_browser_first_visible_paint_done
        )

    def _schedule_startup_splash_finish_after_main_window_paint(self, delay_ms: int = 120) -> None:
        if getattr(self, "_startup_splash_window", None) is None:
            return
        QTimer.singleShot(max(0, int(delay_ms)), self._finish_startup_splash_after_main_window_paint)

    def _finish_startup_splash_after_main_window_paint(self) -> None:
        if getattr(self, "_startup_splash_window", None) is None:
            return
        if (
            not bool(getattr(self, "_startup_splash_finish_pending", False))
            and float(getattr(self, "_startup_splash_finish_after_paint_deadline", 0.0) or 0.0) <= 0.0
        ):
            return
        if getattr(self, "_shutting_down", False):
            self._finish_startup_splash_now()
            return
        deadline = float(getattr(self, "_startup_splash_finish_after_paint_deadline", 0.0) or 0.0)
        if self._startup_archive_first_paint_needed() and time.monotonic() < deadline:
            self._update_startup_splash("Opening Archive Browser...", 0, 0)
            self._schedule_archive_browser_first_visible_paint_marker(80)
            self._schedule_startup_splash_finish_after_main_window_paint(140)
            return
        if self._startup_archive_first_paint_needed():
            self._record_startup_prompt_event("startup_splash_first_paint_timeout", surface="archive_browser")
            self.append_archive_log(
                "WARNING: Startup splash timed out waiting for first archive paint.",
                verbose=True,
            )
        self._finish_startup_splash_now()

    def _finish_startup_splash_and_show_main_window(self) -> None:
        self._update_startup_splash("Opening workspace...", 1, 1)
        self._show_main_window_after_startup_splash()
        self._startup_splash_holds_main_window = False
        self._startup_splash_finish_after_paint_deadline = (
            time.monotonic() + _ARCHIVE_FIRST_PAINT_FALLBACK_SECONDS
        )
        if (
            getattr(self, "archive_entries", None)
            and self._is_tool_visible_or_current(self.archive_browser_tab)
        ):
            self.archive_browser_first_visible_paint_done = False
            self.archive_browser_first_visible_started_at = time.perf_counter()
            self._schedule_archive_browser_first_visible_paint_marker(80)
        self._schedule_startup_splash_finish_after_main_window_paint(180)
        try:
            self.repaint()
            app = QApplication.instance()
            if app is not None:
                app.processEvents()
        except Exception:
            pass

    def _release_startup_splash(self) -> None:
        if getattr(self, "_startup_splash_released", False):
            return
        splash = getattr(self, "_startup_splash_window", None)
        if bool(getattr(self, "_startup_texture_preview_defer_env", False)):
            os.environ.pop("CDMW_DEFER_TEXTURE_PREVIEW", None)
            self._startup_texture_preview_defer_env = False
        self._startup_splash_released = True
        self._startup_splash_release_pending = False
        if self.archive_scan_worker is None and self.worker_thread is None:
            self.archive_startup_index_warmup_required = False
        self._record_startup_prompt_event("splash_released")
        if (
            getattr(self, "_startup_splash_holds_main_window", False)
            and not getattr(self, "_shutting_down", False)
        ):
            if splash is not None and not getattr(self, "_startup_splash_finish_pending", False):
                self._startup_splash_finish_pending = True
                QTimer.singleShot(0, self._finish_startup_splash_and_show_main_window)
                return
            self._finish_startup_splash_and_show_main_window()
            return
        self._finish_startup_splash_now()

    def _maybe_autoload_archive_on_startup(self) -> None:
        if bool(getattr(self, "_startup_archive_path_prompt_open", False)):
            QTimer.singleShot(250, self._maybe_autoload_archive_on_startup)
            return
        if self.show_quick_start_on_launch:
            self._write_heartbeat("running")
            self._release_startup_splash()
            return
        if bool(getattr(self, "_previous_session_unclean", False)) and not self._startup_benchmark_enabled():
            message = (
                "Startup archive auto-load skipped because the previous session did not shut down cleanly. "
                "Open Archive Browser manually after the window is responsive, or use Help > Export Diagnostics "
                "to share the crash context."
            )
            self.append_archive_log(message)
            self.set_status_message(message)
            self._write_heartbeat("running")
            self._release_startup_splash()
            return
        if self.worker_thread is not None or self.archive_entries:
            self._write_heartbeat("running")
            self._release_startup_splash()
            return

        package_root_text = self.archive_package_root_edit.text().strip()
        if not package_root_text:
            self._write_heartbeat("running")
            self._release_startup_splash()
            return
        package_root = Path(package_root_text).expanduser()
        if not package_root.exists():
            self.append_archive_log(f"Startup archive auto-load skipped: package root does not exist: {package_root}")
            self._write_heartbeat("running")
            self._release_startup_splash()
            return
        if bool(getattr(self, "_startup_archive_autoload_dispatched", False)):
            return
        self._startup_archive_autoload_dispatched = True

        self.append_archive_log("Startup Archive Browser preload is enabled.")
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        use_remote_backend = bool(remote_bridge is not None and remote_bridge.displays_v2)
        if not use_remote_backend:
            health_report = self._check_archive_cache_health(package_root_text)
            self._warn_if_archive_cache_stale(health_report, package_root_text)
        if bool(getattr(self, "_startup_archive_path_prompt_accepted", False)):
            if use_remote_backend:
                self.append_archive_log(
                    "Archive catalogue loading will continue in the background after CDMW opens."
                )
            else:
                self.append_archive_log(
                    "Building the first archive cache now. Keep CDMW open until the cache status reaches ready."
                )
                self._update_startup_splash(
                    "Building archive cache. First load can take a while; let it finish.",
                    1,
                    100,
                )
        else:
            self._update_startup_splash("Loading Archive Browser...")
        self.archive_startup_autoload_defer_preview = True
        self.archive_startup_hold_until_ready = not use_remote_backend
        self.archive_startup_index_warmup_required = not use_remote_backend
        self.archive_startup_saved_filter_state = {}
        self.archive_startup_saved_filter_apply_pending = False
        self.archive_startup_saved_filter_wait_logged = False
        self._apply_archive_filter_state(self._neutral_archive_filter_state())
        self.archive_filters_dirty = False
        self._update_archive_filter_button_state()
        self._record_runtime_event("startup_autoload_begin", package_root=str(package_root))
        force_refresh = not self._preference_bool("prefer_archive_cache_on_startup", True)
        if use_remote_backend:
            self._write_heartbeat("running")
            self._release_startup_splash()
            QTimer.singleShot(
                0,
                lambda: self.scan_archives(
                    force_refresh=force_refresh,
                    activate_archive_tab=False,
                ),
            )
            return
        self._write_heartbeat("archive_autoload")
        self.scan_archives(force_refresh=force_refresh, activate_archive_tab=False)

    def _load_game_executable_fingerprints(self) -> Dict[str, Dict[str, object]]:
        raw_value = self.settings.value("archive/game_executable_fingerprints", "{}")
        try:
            payload = json.loads(str(raw_value or "{}"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        records: Dict[str, Dict[str, object]] = {}
        for key, value in payload.items():
            if isinstance(value, dict):
                records[str(key)] = dict(value)
        return records

    def _save_game_executable_fingerprints(self, records: Mapping[str, Mapping[str, object]]) -> None:
        payload = {str(key): dict(value) for key, value in records.items()}
        self.settings.setValue(
            "archive/game_executable_fingerprints",
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
        )
        self.settings.sync()

    def _check_game_update_and_invalidate_archive_cache(self, package_root: Path) -> bool:
        executable_path = resolve_crimson_desert_executable(package_root)
        if executable_path is None:
            return False

        try:
            stat_result = executable_path.stat()
        except OSError as exc:
            self.append_archive_log(f"Game update check skipped: could not read {executable_path}: {exc}")
            return False

        executable_key = str(executable_path).strip().lower()
        current_size = int(stat_result.st_size)
        current_mtime_ns = int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000)))
        records = self._load_game_executable_fingerprints()
        previous_record = records.get(executable_key, {})
        previous_hash = str(previous_record.get("sha256", "") or "").strip()
        previous_size = int(previous_record.get("size", -1) or -1)
        previous_mtime_ns = int(previous_record.get("mtime_ns", -1) or -1)

        if (
            previous_hash
            and previous_size == current_size
            and previous_mtime_ns == current_mtime_ns
        ):
            return False

        try:
            current_hash = sha256_file(executable_path)
        except OSError as exc:
            self.append_archive_log(f"Game update check skipped: could not hash {executable_path}: {exc}")
            return False

        records[executable_key] = {
            "path": str(executable_path),
            "sha256": current_hash,
            "size": current_size,
            "mtime_ns": current_mtime_ns,
            "checked_at": time.time(),
        }
        self._save_game_executable_fingerprints(records)

        if not previous_hash:
            self.append_archive_log(f"Recorded CrimsonDesert.exe hash baseline: {executable_path}")
            return False
        if previous_hash == current_hash:
            return False

        deleted_paths = invalidate_archive_browser_cache(
            package_root,
            self.archive_cache_root,
            on_log=self.append_archive_log,
        )
        if deleted_paths:
            self.append_archive_log(
                "Game update detected via CrimsonDesert.exe hash. "
                f"Archive Browser cache invalidated ({len(deleted_paths):,} file(s))."
            )
            self.append_log("Game update detected via CrimsonDesert.exe hash. Archive Browser cache invalidated.")
            self.set_status_message("Game update detected. Archive Browser cache invalidated.")
        else:
            self.append_archive_log(
                "Game update detected via CrimsonDesert.exe hash. No existing Archive Browser cache file needed deletion."
            )
            self.append_log("Game update detected via CrimsonDesert.exe hash.")
            self.set_status_message("Game update detected.")
        return True

    def _startup_archive_autoload_expected(self) -> bool:
        if self._startup_benchmark_enabled():
            package_root_text = self.archive_package_root_edit.text().strip()
            return bool(package_root_text and Path(package_root_text).expanduser().exists())
        if self.show_quick_start_on_launch:
            return False
        if getattr(self, "_previous_session_unclean", False) and not self._startup_benchmark_enabled():
            return False
        package_root_text = self.archive_package_root_edit.text().strip()
        if not package_root_text:
            return False
        return Path(package_root_text).expanduser().exists()

    def _startup_benchmark_enabled(self) -> bool:
        return os.environ.get("CDMW_STARTUP_BENCHMARK", "").strip() == "1"

    def _startup_benchmark_search_text(self) -> str:
        return os.environ.get("CDMW_BENCHMARK_SEARCH_TEXT", "").strip()

    def _startup_benchmark_extension_filter(self) -> str:
        return os.environ.get("CDMW_BENCHMARK_EXTENSION_FILTER", "").strip() or "*"

    def _apply_startup_benchmark_overrides(self) -> None:
        if not self._startup_benchmark_enabled():
            return
        package_root_text = os.environ.get("CDMW_BENCHMARK_PACKAGE_ROOT", "").strip()
        if package_root_text:
            self.archive_package_root_edit.setText(package_root_text)
        self.show_quick_start_on_launch = False
        self.archive_startup_hold_until_ready = True
        self.archive_startup_saved_filter_apply_pending = False
        self.archive_startup_saved_filter_state = {}
        self._apply_archive_filter_state(self._neutral_archive_filter_state())
        self.archive_filters_dirty = False

    def _record_startup_benchmark_complete(
        self,
        *,
        reason: str,
        source: str,
        timings: Optional[Dict[str, float]] = None,
        timing_summary: str = "",
        search_elapsed_s: Optional[float] = None,
        search_count: Optional[int] = None,
    ) -> None:
        fields: Dict[str, object] = {
            "reason": str(reason or "archive_ready"),
            "source": str(source or "unknown"),
            "entry_count": len(getattr(self, "archive_entries", []) or []),
            "cache_root": str(getattr(self, "archive_cache_root", "")),
            "timing_summary": timing_summary,
            "total_s": _timing_value(timings, "total_s"),
            "archive_scan_s": _timing_value(timings, "archive_scan_s"),
            "cache_load_s": _timing_value(timings, "cache_load_s"),
            "cache_write_s": _timing_value(timings, "cache_write_s"),
            "scan_shard_load_s": _timing_value(timings, "scan_shard_load_s"),
            "scan_shard_write_s": _timing_value(timings, "scan_shard_write_s"),
        }
        if search_elapsed_s is not None:
            fields.update(
                {
                    "search_text": self._startup_benchmark_search_text(),
                    "search_extension_filter": self._startup_benchmark_extension_filter(),
                    "search_elapsed_s": max(0.0, float(search_elapsed_s)),
                    "search_count": int(search_count or 0),
                }
            )
        self._record_startup_prompt_event("startup_benchmark_complete", **fields)

    def _start_startup_benchmark_search(self) -> None:
        search_text = self._startup_benchmark_search_text()
        if not self._startup_benchmark_enabled() or not search_text:
            return
        self._startup_benchmark_search_pending = False
        if self._startup_benchmark_search_started_at > 0.0:
            return
        extension_filter = self._startup_benchmark_extension_filter()
        state = self._neutral_archive_filter_state()
        state["filter_text"] = search_text
        state["extension_filter"] = extension_filter
        self._apply_archive_filter_state(state)
        self.archive_filters_dirty = False
        self._startup_benchmark_search_started_at = time.perf_counter()
        self._record_startup_prompt_event(
            "startup_benchmark_search_begin",
            search_text=search_text,
            search_extension_filter=extension_filter,
        )
        self.append_archive_log(
            f"Startup benchmark search begin: extension={extension_filter}, text={search_text!r}."
        )
        self._apply_archive_filter()

    def _schedule_startup_benchmark_search_after_visible(self, delay_ms: int = 120) -> None:
        if not self._startup_benchmark_enabled() or self._startup_benchmark_finish_requested:
            return
        if not self._startup_benchmark_search_text() or self._startup_benchmark_search_started_at > 0.0:
            return
        if bool(getattr(self, "_startup_benchmark_search_pending", False)):
            return
        self._startup_benchmark_search_pending = True
        QTimer.singleShot(max(0, int(delay_ms)), self._try_start_startup_benchmark_search_after_visible)

    def _try_start_startup_benchmark_search_after_visible(self) -> None:
        self._startup_benchmark_search_pending = False
        if not self._startup_benchmark_enabled() or self._startup_benchmark_finish_requested:
            return
        if not self._startup_benchmark_search_text() or self._startup_benchmark_search_started_at > 0.0:
            return
        if (
            self.worker_thread is not None
            or getattr(self, "_startup_splash_window", None) is not None
            or not self.isVisible()
            or self._startup_archive_first_paint_needed()
        ):
            self._schedule_startup_benchmark_search_after_visible(160)
            return
        self._record_startup_prompt_event("startup_benchmark_search_ready_after_paint")
        self.append_archive_log("Startup benchmark search starts after visible archive paint.")
        QTimer.singleShot(250, self._start_startup_benchmark_search)

    def _finish_startup_benchmark_search_after_filter(self) -> None:
        if not self._startup_benchmark_enabled() or self._startup_benchmark_finish_requested:
            return
        started_at = float(getattr(self, "_startup_benchmark_search_started_at", 0.0) or 0.0)
        if started_at <= 0.0:
            return
        search_elapsed_s = max(0.0, time.perf_counter() - started_at)
        search_count = len(getattr(self, "archive_filtered_entries", []) or [])
        self._record_startup_prompt_event(
            "startup_benchmark_search_complete",
            search_text=self._startup_benchmark_search_text(),
            search_extension_filter=self._startup_benchmark_extension_filter(),
            search_elapsed_s=search_elapsed_s,
            search_count=search_count,
        )
        self._startup_benchmark_finish_requested = True
        self._record_startup_benchmark_complete(
            reason="search_complete",
            source=self._startup_benchmark_archive_source,
            timings=self._startup_benchmark_archive_timings,
            timing_summary=self._startup_benchmark_archive_timing_summary,
            search_elapsed_s=search_elapsed_s,
            search_count=search_count,
        )
        self.append_archive_log("Startup benchmark search complete; closing app.")
        QTimer.singleShot(700, self.close)

    def _finish_startup_benchmark_after_archive_ready(
        self,
        *,
        reason: str,
        source: str,
        timings: Optional[Dict[str, float]] = None,
        timing_summary: str = "",
    ) -> None:
        if not self._startup_benchmark_enabled() or self._startup_benchmark_finish_requested:
            return
        self._startup_benchmark_archive_source = str(source or "unknown")
        self._startup_benchmark_archive_timings = dict(timings or {})
        self._startup_benchmark_archive_timing_summary = str(timing_summary or "")
        search_text = self._startup_benchmark_search_text()
        if search_text and self._startup_benchmark_search_started_at <= 0.0:
            self._record_startup_prompt_event(
                "startup_benchmark_archive_ready",
                reason=str(reason or "archive_ready"),
                source=str(source or "unknown"),
                entry_count=len(getattr(self, "archive_entries", []) or []),
                total_s=_timing_value(timings, "total_s"),
                cache_load_s=_timing_value(timings, "cache_load_s"),
                cache_write_s=_timing_value(timings, "cache_write_s"),
            )
            self._schedule_startup_benchmark_search_after_visible(120)
            return
        self._startup_benchmark_finish_requested = True
        self._record_startup_benchmark_complete(
            reason=str(reason or "archive_ready"),
            source=str(source or "unknown"),
            timings=timings,
            timing_summary=timing_summary,
        )
        self.append_archive_log("Startup benchmark complete; closing app.")
        QTimer.singleShot(700, self.close)

    def _show_first_run_guide_if_needed(self) -> None:
        if not self.show_quick_start_on_launch:
            return
        if bool(getattr(self, "_startup_archive_path_prompt_handled", False)):
            return
        if not self.archive_package_root_edit.text().strip():
            if not self._prompt_for_archive_package_root_if_missing(
                reason="startup",
                after_autodetect=self._show_first_run_guide_if_needed,
            ):
                return
        self.show_quick_start_on_launch = False
        self.settings.setValue("ui/startup_setup_shown", True)
        self.settings.sync()
        self.focus_archive_locations()
        self.show_quick_start_dialog()

    def _startup_archive_path_prompt_needed(self) -> bool:
        if self._startup_benchmark_enabled() or os.environ.get("CDMW_GUI_STARTUP_SMOKE") == "1":
            return False
        if not self.show_quick_start_on_launch:
            return False
        return not bool(self.archive_package_root_edit.text().strip())

    def _show_startup_archive_path_prompt_if_needed(self, startup_splash: Optional[object] = None) -> bool:
        if not self._startup_archive_path_prompt_needed():
            return False
        self._startup_archive_path_prompt_handled = True
        self._update_startup_splash("Choose Crimson Desert path...")
        from cdmw.ui.shell.startup_dialogs import StartupArchivePathDialog

        dialog = StartupArchivePathDialog(
            theme_key=self.current_theme_key,
            initial_path=self.archive_package_root_edit.text().strip(),
            startup_splash=startup_splash,
        )
        if not self.windowIcon().isNull():
            dialog.setWindowIcon(self.windowIcon())
        dialog.center_on_screen()
        self._startup_archive_path_prompt_open = True
        try:
            accepted = dialog.exec() == QDialog.Accepted
            selected_path = dialog.selected_path().strip() if accepted else ""
        finally:
            self._startup_archive_path_prompt_open = False
            dialog.deleteLater()
        if not selected_path:
            self._startup_archive_path_prompt_accepted = False
            self.set_status_message("Crimson Desert path setup skipped; archive cache build was not started.")
            self._record_startup_prompt_event("startup_path_prompt_skipped")
            return False

        self.archive_package_root_edit.setText(selected_path)
        self.show_quick_start_on_launch = False
        self._startup_archive_path_prompt_accepted = True
        self.settings.setValue("ui/startup_setup_shown", True)
        self.settings.setValue("archive/package_root", selected_path)
        self.flush_settings_save()
        self.settings.sync()
        self.set_status_message(f"Crimson Desert path set: {selected_path}")
        self.append_log(f"Startup setup selected Crimson Desert package root: {selected_path}")
        self.append_archive_log(
            "Startup setup selected a Crimson Desert path. First archive cache build can take a while; let it finish before closing the app."
        )
        self._startup_texture_preview_defer_env = True
        os.environ["CDMW_DEFER_TEXTURE_PREVIEW"] = "1"
        self._update_startup_splash(
            "Building archive cache. First load can take a while; let it finish.",
            1,
            100,
        )
        self._record_startup_prompt_event("startup_path_prompt_accepted", package_root=selected_path)
        return True

    def _prompt_for_archive_package_root_if_missing(
        self,
        *,
        reason: str,
        after_autodetect: Optional[Callable[[], None]] = None,
    ) -> bool:
        if self.archive_package_root_edit.text().strip():
            return True

        self.focus_archive_locations()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Crimson Desert Path Required")
        box.setText("Crimson Desert game/package path is not set.")
        action_text = "scan archives" if reason in {"scan", "refresh"} else "use archive workflows"
        box.setInformativeText(
            f"Set the Game / Package path before you {action_text}. "
            "Choose Auto-detect to search common install locations, or Browse to select the folder manually."
        )
        autodetect_button = box.addButton("Auto-detect", QMessageBox.AcceptRole)
        browse_button = box.addButton("Browse...", QMessageBox.ActionRole)
        settings_button = box.addButton("Open Archive Locations", QMessageBox.ActionRole)
        cancel_button = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(autodetect_button)
        box.exec()

        clicked = box.clickedButton()
        if clicked is autodetect_button:
            self.autodetect_archive_package_root(after_success=after_autodetect)
            return False
        if clicked is browse_button:
            selected = QFileDialog.getExistingDirectory(
                self,
                "Select Archive Package Root",
                self._pick_existing_directory(self.archive_package_root_edit.text()),
            )
            if selected:
                self.archive_package_root_edit.setText(selected)
                self.flush_settings_save()
                self.set_status_message(f"Archive package root set: {selected}")
                return True
            self.set_status_message("Archive package root selection cancelled.", error=True)
            return False
        if clicked is settings_button:
            self.focus_archive_locations()
            self.set_status_message("Set the Crimson Desert game/package path before scanning.", error=True)
            return False
        if clicked is cancel_button:
            self.set_status_message("Archive package root is required before scanning.", error=True)
        return False


__all__ = [
    "ExternalStartupSplashAdapter",
    "StartupController",
    "StartupPromptMixin",
    "close_pyinstaller_boot_splash",
    "create_startup_splash",
    "format_startup_splash_detail",
    "make_startup_splash_pump",
    "queue_startup_archive_autoload",
]
