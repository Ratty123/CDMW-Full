from __future__ import annotations

import dataclasses
import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QByteArray, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from cdmw.constants import (
    APP_TITLE,
    APP_VERSION,
    ARCHIVE_BROWSER_VIEW_MODE,
    ARCHIVE_EXCLUDE_COMMON_TECHNICAL_SUFFIXES,
    DEFAULT_UPSCALE_POST_CORRECTION,
    DEFAULT_UPSCALE_TEXTURE_PRESET,
    ENABLE_AUTOMATIC_TEXTURE_RULES,
    ENABLE_MOD_READY_LOOSE_EXPORT,
    ENABLE_UNSAFE_TECHNICAL_OVERRIDE,
    MOD_READY_CREATE_NO_ENCRYPT,
    MOD_READY_PACKAGE_AUTHOR,
    MOD_READY_PACKAGE_DESCRIPTION,
    MOD_READY_PACKAGE_NEXUS_URL,
    MOD_READY_PACKAGE_TITLE,
    MOD_READY_PACKAGE_VERSION,
    REALESRGAN_NCNN_SCALE,
    REALESRGAN_NCNN_TILE_SIZE,
    RETRY_SMALLER_TILE_ON_FAILURE,
    UPSCALE_BACKEND_CHAINNER,
    UPSCALE_BACKEND_NONE,
)
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.atomic_file_service import atomic_write_text
from cdmw.models import AppConfig, ChainnerChainAnalysis, default_config
from cdmw.services.diagnostic_bundle_service import (
    ChainnerDiagnosticSnapshot,
    DiagnosticBundleRequest,
    DiagnosticBundleResult,
    build_diagnostic_bundle,
    resolve_chainner_diagnostic,
)
from cdmw.services.diagnostics_service import (
    format_issue_summary,
    latest_diagnostic_report_files,
)
from cdmw.services.workspace_layout import workspace_paths
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.ui.shell.settings_bridge import (
    decode_profile_setting_value as _decode_profile_setting_value,
    encode_profile_setting_value as _encode_profile_setting_value,
)
from cdmw.ui.themes import UI_THEME_SCHEMES


def _coerce_profile_config_value(key: str, value: object, default: object) -> object:
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in {0, 1}:
            return bool(value)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Profile setting '{key}' must be a boolean.")
    if isinstance(default, int):
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Profile setting '{key}' must be an integer.") from exc
    if isinstance(default, str):
        if isinstance(value, (dict, list, tuple)):
            raise ValueError(f"Profile setting '{key}' must be text.")
        return str(value)
    return value


def _profile_config_from_payload(raw_config: object) -> AppConfig:
    if not isinstance(raw_config, dict):
        raise ValueError("Profile file is invalid. Expected a JSON object.")
    config_values = dataclasses.asdict(default_config())
    for key, default_value in tuple(config_values.items()):
        if key in raw_config:
            config_values[key] = _coerce_profile_config_value(key, raw_config[key], default_value)
    return AppConfig(**config_values)


def _decoded_profile_settings_snapshot(snapshot: object) -> Dict[str, object]:
    if not isinstance(snapshot, dict):
        raise ValueError("Profile settings must be a JSON object.")
    decoded: Dict[str, object] = {}
    for raw_key, raw_value in snapshot.items():
        key = str(raw_key or "").strip()
        if not key:
            raise ValueError("Profile settings contain an empty key.")
        decoded[key] = _decode_profile_setting_value(raw_value, qbytearray_type=QByteArray)
    return decoded


PROFILE_IMPORT_MAX_BYTES = 16 * 1024 * 1024


@dataclasses.dataclass(frozen=True, slots=True)
class ProfileImportDocument:
    source: Path
    config: AppConfig
    decoded_settings: Optional[Tuple[Tuple[str, object], ...]]
    theme_key: str


def _profile_theme_from_document(payload: object, current_theme_key: str) -> str:
    if isinstance(payload, dict):
        settings_snapshot = payload.get("settings")
        if isinstance(settings_snapshot, dict):
            theme_value = _decode_profile_setting_value(settings_snapshot.get("appearance/theme"))
            theme_text = str(theme_value or "").strip()
            if theme_text in UI_THEME_SCHEMES:
                return theme_text
        theme_text = str(payload.get("theme") or "").strip()
        if theme_text in UI_THEME_SCHEMES:
            return theme_text
    return current_theme_key


def load_profile_import_document(
    source: Path,
    *,
    current_theme_key: str,
    stop_event: Optional[threading.Event] = None,
) -> ProfileImportDocument:
    source = Path(source).expanduser()
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise ValueError(f"Could not read profile file: {exc}") from exc
    if size > PROFILE_IMPORT_MAX_BYTES:
        raise ValueError(
            f"Profile file is too large ({size:,} bytes; maximum {PROFILE_IMPORT_MAX_BYTES:,})."
        )
    chunks: List[bytes] = []
    total = 0
    with source.open("rb") as handle:
        while True:
            raise_if_cancelled(stop_event, "Profile import cancelled.")
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > PROFILE_IMPORT_MAX_BYTES:
                raise ValueError(f"Profile file exceeds the {PROFILE_IMPORT_MAX_BYTES:,}-byte limit.")
            chunks.append(chunk)
    raise_if_cancelled(stop_event, "Profile import cancelled.")
    try:
        payload = json.loads(b"".join(chunks).decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("Profile file is not valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Profile file is invalid. Expected a JSON object.")
    config = _profile_config_from_payload(payload.get("config", payload))
    decoded = _decoded_profile_settings_snapshot(payload["settings"]) if "settings" in payload else None
    raise_if_cancelled(stop_event, "Profile import cancelled.")
    return ProfileImportDocument(
        source=source,
        config=config,
        decoded_settings=tuple(decoded.items()) if decoded is not None else None,
        theme_key=_profile_theme_from_document(payload, current_theme_key),
    )


class ProfileControllerMixin:
    """Profile import/export and local diagnostic bundle actions for the shell window."""

    def _crash_reports_dir(self) -> Path:
        return workspace_paths(self.settings_file_path.parent)["crash_reports_dir"]

    def _collect_profile_payload(self, *, flush: bool = True) -> Dict[str, object]:
        settings_snapshot = self._collect_profile_settings_snapshot(flush=flush)
        return {
            "app": APP_TITLE,
            "profile_format": 3,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "theme": self.current_theme_key,
            "config": dataclasses.asdict(self.collect_config()),
            "settings": settings_snapshot,
            "settings_key_count": len(settings_snapshot),
        }

    def _collect_profile_settings_snapshot(self, *, flush: bool = True) -> Dict[str, object]:
        if flush:
            try:
                self.flush_settings_save()
                self.settings_tab.flush_settings_save()
                self.replace_assistant_tab.flush_settings_save()
                self.texture_editor_tab.flush_settings_save()
                self._save_detached_tool_geometries()
                self.settings.setValue("window/geometry", self.saveGeometry())
                self.settings.sync()
            except Exception:
                pass
        snapshot: Dict[str, object] = {}
        try:
            keys = sorted(str(key) for key in self.settings.allKeys())
        except Exception:
            keys = []
        for key in keys:
            try:
                snapshot[key] = _encode_profile_setting_value(self.settings.value(key))
            except Exception:
                continue
        return snapshot

    def _apply_decoded_profile_settings(self, values: Dict[str, object], *, replace: bool) -> int:
        if replace:
            self.settings.clear()
        for key, value in values.items():
            self.settings.setValue(key, value)
        self.settings.sync()
        return len(values)

    def _restore_profile_settings_snapshot(self, snapshot: object, *, replace: bool = False) -> int:
        return self._apply_decoded_profile_settings(
            _decoded_profile_settings_snapshot(snapshot),
            replace=replace,
        )

    def _profile_theme_from_payload(self, payload: object) -> str:
        return _profile_theme_from_document(payload, self.current_theme_key)

    def _apply_profile_settings_snapshot_to_ui(self, *, theme_key: str) -> None:
        if hasattr(self, "_load_settings"):
            self._load_settings()
        if theme_key in UI_THEME_SCHEMES:
            self.current_theme_key = theme_key
            self._handle_theme_changed(theme_key)
        if hasattr(self.settings_tab, "_load_settings"):
            self.settings_tab._load_settings(theme_key)
            self.settings_tab.sync_archive_performance_controls()
        if hasattr(self.replace_assistant_tab, "_load_settings"):
            self.replace_assistant_tab._load_settings()
        if hasattr(self.texture_editor_tab, "_load_settings"):
            self.texture_editor_tab._load_settings()
        language_code = str(self.settings.value("appearance/language", self.ui_localizer.language_code) or "en")
        try:
            self.ui_localizer.load_language(language_code)
        except Exception:
            self.ui_localizer.load_language("en")
        self._apply_ui_language()

    def _apply_profile_import_transaction(
        self,
        imported_config: AppConfig,
        *,
        theme_key: str,
        decoded_settings: Optional[Dict[str, object]],
    ) -> int:
        previous_config = self.collect_config()
        previous_theme = self.current_theme_key
        previous_settings = _decoded_profile_settings_snapshot(self._collect_profile_settings_snapshot())
        try:
            restored_settings = 0
            if decoded_settings is not None:
                restored_settings = self._apply_decoded_profile_settings(decoded_settings, replace=True)
            self._apply_profile_config(imported_config, theme_key=theme_key)
            if decoded_settings is not None:
                self._apply_profile_settings_snapshot_to_ui(theme_key=theme_key)
            return restored_settings
        except Exception:
            self._apply_decoded_profile_settings(previous_settings, replace=True)
            self._apply_profile_config(previous_config, theme_key=previous_theme)
            self._apply_profile_settings_snapshot_to_ui(theme_key=previous_theme)
            raise

    def _resolve_chainner_analysis(self) -> Tuple[Optional[ChainnerChainAnalysis], str]:
        return resolve_chainner_diagnostic(self._chainner_diagnostic_snapshot())

    def _chainner_diagnostic_snapshot(self) -> ChainnerDiagnosticSnapshot:
        return ChainnerDiagnosticSnapshot(
            chain_path=self.chainner_chain_path_edit.text().strip(),
            original_dds_root=self.original_dds_edit.text().strip(),
            staging_png_root=self.dds_staging_root_edit.text().strip(),
            png_root=self.png_root_edit.text().strip(),
            override_json=self.chainner_override_edit.toPlainText(),
        )

    def _apply_profile_config(self, config: AppConfig, *, theme_key: Optional[str] = None) -> None:
        previous_ready = self._settings_ready
        self._settings_ready = False
        try:
            self.original_dds_edit.setText(config.original_dds_root)
            self.png_root_edit.setText(config.png_root)
            self.texture_editor_png_root_edit.setText(getattr(config, "texture_editor_png_root", ""))
            self.dds_staging_root_edit.setText(config.dds_staging_root)
            self.output_root_edit.setText(config.output_root)
            self.texconv_path_edit.setText(config.texconv_path)
            self._set_combo_by_value(self.dds_format_mode_combo, config.dds_format_mode)
            self._set_combo_by_value(self.dds_custom_format_combo, config.dds_custom_format)
            self._set_combo_by_value(self.dds_size_mode_combo, config.dds_size_mode)
            self.dds_custom_width_spin.setValue(int(config.dds_custom_width))
            self.dds_custom_height_spin.setValue(int(config.dds_custom_height))
            self._set_combo_by_value(self.dds_mip_mode_combo, config.dds_mip_mode)
            self.dds_custom_mip_spin.setValue(int(config.dds_custom_mip_count))
            self.enable_dds_staging_checkbox.setChecked(bool(config.enable_dds_staging))
            self.enable_incremental_resume_checkbox.setChecked(bool(config.enable_incremental_resume))
            self.dry_run_checkbox.setChecked(bool(config.dry_run))
            self.csv_log_enabled_checkbox.setChecked(bool(config.csv_log_enabled))
            self.csv_log_path_edit.setText(config.csv_log_path)
            self.unique_basename_checkbox.setChecked(bool(config.allow_unique_basename_fallback))
            self.overwrite_existing_checkbox.setChecked(bool(config.overwrite_existing_dds))
            self.filters_edit.setPlainText(config.include_filters)
            self._set_combo_by_value(
                self.upscale_backend_combo,
                getattr(
                    config,
                    "upscale_backend",
                    UPSCALE_BACKEND_CHAINNER if config.enable_chainner else UPSCALE_BACKEND_NONE,
                ),
            )
            self.chainner_exe_path_edit.setText(config.chainner_exe_path)
            self.chainner_chain_path_edit.setText(config.chainner_chain_path)
            self.chainner_override_edit.setPlainText(config.chainner_override_json)
            self.ncnn_exe_path_edit.setText(getattr(config, "ncnn_exe_path", ""))
            self.ncnn_model_dir_edit.setText(getattr(config, "ncnn_model_dir", ""))
            self.ncnn_extra_args_edit.setText(getattr(config, "ncnn_extra_args", ""))
            self.ncnn_scale_spin.setValue(int(getattr(config, "ncnn_scale", REALESRGAN_NCNN_SCALE)))
            self.ncnn_tile_size_spin.setValue(int(getattr(config, "ncnn_tile_size", REALESRGAN_NCNN_TILE_SIZE)))
            self._set_combo_by_value(
                self.upscale_post_correction_combo,
                getattr(config, "upscale_post_correction_mode", DEFAULT_UPSCALE_POST_CORRECTION),
            )
            self._set_combo_by_value(
                self.upscale_texture_preset_combo,
                getattr(config, "upscale_texture_preset", DEFAULT_UPSCALE_TEXTURE_PRESET),
            )
            self.enable_automatic_texture_rules_checkbox.setChecked(
                bool(getattr(config, "enable_automatic_texture_rules", ENABLE_AUTOMATIC_TEXTURE_RULES))
            )
            self.enable_unsafe_technical_override_checkbox.setChecked(
                bool(getattr(config, "enable_unsafe_technical_override", ENABLE_UNSAFE_TECHNICAL_OVERRIDE))
            )
            self.retry_smaller_tile_checkbox.setChecked(
                bool(getattr(config, "retry_smaller_tile_on_failure", RETRY_SMALLER_TILE_ON_FAILURE))
            )
            self.enable_mod_ready_loose_export_checkbox.setChecked(
                bool(getattr(config, "enable_mod_ready_loose_export", ENABLE_MOD_READY_LOOSE_EXPORT))
            )
            self.mod_ready_export_root_edit.setText(getattr(config, "mod_ready_export_root", ""))
            self.mod_ready_create_no_encrypt_checkbox.setChecked(
                bool(getattr(config, "mod_ready_create_no_encrypt_file", MOD_READY_CREATE_NO_ENCRYPT))
            )
            self.mod_ready_package_title_edit.setText(getattr(config, "mod_ready_package_title", MOD_READY_PACKAGE_TITLE))
            self.mod_ready_package_version_edit.setText(getattr(config, "mod_ready_package_version", MOD_READY_PACKAGE_VERSION))
            self.mod_ready_package_author_edit.setText(getattr(config, "mod_ready_package_author", MOD_READY_PACKAGE_AUTHOR))
            self.mod_ready_package_description_edit.setText(
                getattr(config, "mod_ready_package_description", MOD_READY_PACKAGE_DESCRIPTION)
            )
            self.mod_ready_package_nexus_url_edit.setText(
                getattr(config, "mod_ready_package_nexus_url", MOD_READY_PACKAGE_NEXUS_URL)
            )
            self._refresh_ncnn_model_picker(preferred_name=getattr(config, "ncnn_model_name", ""))
            self.archive_package_root_edit.setText(config.archive_package_root)
            self.archive_extract_root_edit.setText(config.archive_extract_root)
            self.archive_filter_edit.setText(config.archive_filter_text)
            self.archive_exclude_filter_edit.setText(getattr(config, "archive_exclude_filter_text", ""))
            self._rebuild_archive_extension_filter_choices(config.archive_extension_filter)
            self._set_combo_by_value(self.archive_extension_filter_combo, config.archive_extension_filter)
            self.archive_package_filter_edit.setText(config.archive_package_filter_text)
            self.archive_structure_filter_pending_value = config.archive_structure_filter
            self._set_combo_by_value(self.archive_role_filter_combo, config.archive_role_filter)
            self.archive_exclude_common_technical_checkbox.setChecked(
                bool(getattr(config, "archive_exclude_common_technical_suffixes", ARCHIVE_EXCLUDE_COMMON_TECHNICAL_SUFFIXES))
            )
            self.archive_min_size_spin.setValue(int(config.archive_min_size_kb))
            self.archive_previewable_only_checkbox.setChecked(bool(config.archive_previewable_only))
            self._set_combo_by_value(
                self.archive_browser_view_mode_combo,
                str(getattr(config, "archive_browser_view_mode", ARCHIVE_BROWSER_VIEW_MODE) or ARCHIVE_BROWSER_VIEW_MODE),
            )
            self._apply_workflow_state_from_config(config)
        finally:
            self._settings_ready = previous_ready

        self._apply_csv_log_enabled_state()
        self._apply_upscale_backend_state()
        self._apply_mod_ready_export_state()
        self._apply_dds_staging_enabled_state()
        self._apply_dds_output_state()
        self._refresh_chainner_chain_info()
        self._schedule_workflow_match_refresh()
        if theme_key and theme_key in UI_THEME_SCHEMES:
            self._handle_theme_changed(theme_key)
        self.flush_settings_save()

    def export_profile(self) -> None:
        try:
            default_name = self.settings_file_path.parent / "cdmw_profile.cdmwprofile.json"
            selected, _ = QFileDialog.getSaveFileName(
                self,
                "Export Profile",
                str(default_name),
                "Crimson Desert Mod Workbench profile (*.cdmwprofile.json);;Legacy CFT profile (*.ctfprofile.json);;JSON files (*.json);;All files (*.*)",
            )
            if not selected:
                return

            target = Path(selected).expanduser()
            if not target.suffix:
                target = target.with_suffix(".cdmwprofile.json")

            payload = self._collect_profile_payload()
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target, json.dumps(payload, indent=2))
            self.set_status_message(f"Profile exported to {target}")
            self.append_log(f"Profile exported: {target}")
        except Exception as exc:
            self.set_status_message(str(exc), error=True)
            self.append_log(f"ERROR: {exc}")

    def import_profile(self) -> None:
        try:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Import Profile",
                str(self.settings_file_path.parent),
                "Crimson Desert Mod Workbench profile (*.cdmwprofile.json *.ctfprofile.json *.json);;All files (*.*)",
            )
            if not selected:
                return

            answer = QMessageBox.question(
                self,
                "Import Profile",
                "Importing a profile will replace current workflow paths, package settings, appearance, startup, preview, window/layout, Texture Replacer, and Texture Editor preferences. Continue?",
            )
            if answer != QMessageBox.Yes:
                return

            source = Path(selected).expanduser()
            request_id = int(getattr(self, "_profile_import_request_id", 0) or 0) + 1
            self._profile_import_request_id = request_id
            current_theme_key = self.current_theme_key
            self._run_utility_task(
                status_message="Reading profile...",
                task=lambda _log, stop_event: load_profile_import_document(
                    source,
                    current_theme_key=current_theme_key,
                    stop_event=stop_event,
                ),
                on_complete=lambda result: self._handle_profile_import_document(request_id, result),
                task_accepts_cancel=True,
            )
        except Exception as exc:
            self.set_status_message(str(exc), error=True)
            self.append_log(f"ERROR: {exc}")

    def _handle_profile_import_document(self, request_id: int, result: object) -> None:
        if request_id != int(getattr(self, "_profile_import_request_id", 0) or 0):
            return
        if not isinstance(result, ProfileImportDocument):
            self.set_status_message("Profile worker returned an invalid document.", error=True)
            return
        try:
            restored_settings = self._apply_profile_import_transaction(
                result.config,
                theme_key=result.theme_key,
                decoded_settings=(dict(result.decoded_settings) if result.decoded_settings is not None else None),
            )
            message = f"Profile imported from {result.source}"
            if restored_settings:
                message += f" ({restored_settings} app settings restored)"
            self.set_status_message(message)
            self.append_log(message)
        except Exception as exc:
            self.set_status_message(str(exc), error=True)
            self.append_log(f"ERROR: {exc}")

    def export_diagnostic_bundle(self) -> None:
        try:
            default_name = self.settings_file_path.parent / "cdmw_diagnostics.zip"
            selected, _ = QFileDialog.getSaveFileName(
                self,
                "Export Diagnostic Bundle",
                str(default_name),
                "ZIP archive (*.zip);;All files (*.*)",
            )
            if not selected:
                return

            target = Path(selected).expanduser()
            if not target.suffix:
                target = target.with_suffix(".zip")
            request_id = int(getattr(self, "_diagnostic_bundle_request_id", 0) or 0) + 1
            self._diagnostic_bundle_request_id = request_id
            request = self._diagnostic_bundle_request(target)

            self._run_utility_task(
                status_message="Exporting diagnostic bundle...",
                task=lambda _log, stop_event: build_diagnostic_bundle(
                    request,
                    stop_event=stop_event,
                ),
                on_complete=lambda result: self._handle_diagnostic_bundle_complete(request_id, result),
                task_accepts_cancel=True,
            )
        except Exception as exc:
            self.set_status_message(str(exc), error=True)
            self.append_log(f"ERROR: {exc}")

    def _diagnostic_bundle_request(self, target: Path) -> DiagnosticBundleRequest:
        text_search_entries: tuple[tuple[str, str], ...] = ()
        text_search_tab = created_tool_widget(getattr(self, "text_search_tab", None))
        if text_search_tab is not None:
            text_search_entries = tuple(text_search_tab.diagnostic_entries().items())
        project_root = Path(__file__).parents[3]
        return DiagnosticBundleRequest(
            target=target,
            app_title=APP_TITLE,
            app_version=APP_VERSION,
            theme=self.current_theme_key,
            settings_file_path=Path(self.settings_file_path),
            archive_cache_root=Path(self.archive_cache_root),
            crash_reports_dir=self._crash_reports_dir(),
            profile_json=json.dumps(self._collect_profile_payload(flush=False), indent=2),
            chainner=self._chainner_diagnostic_snapshot(),
            live_log=self.log_view.toPlainText(),
            archive_scan_log=self.archive_log_view.toPlainText(),
            crash_context_json=json.dumps(self._diagnostic_context_snapshot(), default=str),
            text_search_entries=text_search_entries,
            documentation_files=(
                project_root / "README.md",
                project_root / "THIRD_PARTY_NOTICES.md",
                project_root / "LICENSE",
            ),
        )

    def _diagnostic_context_snapshot(self) -> Dict[str, object]:
        """Capture UI-only context; filesystem/process inspection stays in the worker."""

        context: Dict[str, object] = {}
        try:
            index = self.main_tabs.currentIndex()
            if index >= 0:
                context["current_tab"] = self.main_tabs.tabText(index)
        except Exception:
            pass
        try:
            entry = self._current_archive_entry()
            if entry is not None:
                context["selected_archive_path"] = entry.path
                context["selected_archive_package"] = str(entry.pamt_path)
        except Exception:
            pass
        try:
            context["last_active_operation"] = dict(getattr(self, "_last_active_operation", {}) or {})
        except Exception:
            pass
        return context

    def _handle_diagnostic_bundle_complete(self, request_id: int, result: object) -> None:
        if request_id != int(getattr(self, "_diagnostic_bundle_request_id", 0) or 0):
            return
        if not isinstance(result, DiagnosticBundleResult):
            self.set_status_message("Diagnostic bundle worker returned an invalid result.", error=True)
            return
        self.set_status_message(f"Diagnostic bundle exported to {result.target}")
        self.append_log(f"Diagnostic bundle exported: {result.target}")

    def open_crash_reports_folder(self) -> None:
        try:
            crash_reports_dir = self._crash_reports_dir()
            crash_reports_dir.mkdir(parents=True, exist_ok=True)
            if QDesktopServices.openUrl(QUrl.fromLocalFile(str(crash_reports_dir.resolve()))):
                self.set_status_message(f"Opened crash reports folder: {crash_reports_dir}")
                return
            self.set_status_message(f"Could not open crash reports folder: {crash_reports_dir}", error=True)
        except Exception as exc:
            self.set_status_message(str(exc), error=True)
            self.append_log(f"ERROR: {exc}")

    def copy_latest_problem_summary(self) -> None:
        try:
            crash_reports_dir = self._crash_reports_dir()
            latest_log = next(
                (
                    path
                    for path in latest_diagnostic_report_files(
                        crash_reports_dir,
                        limit=20,
                        suffixes=frozenset({".log"}),
                    )
                ),
                None,
            )
            summary = format_issue_summary(
                app_title=APP_TITLE,
                app_version=APP_VERSION,
                report_path=latest_log,
                context=None if latest_log is not None else self._collect_crash_context(),
            )
            QApplication.clipboard().setText(summary)
            report_label = latest_log.name if latest_log is not None else "current app state"
            self.set_status_message(f"Copied problem summary from {report_label}.")
        except Exception as exc:
            self.set_status_message(str(exc), error=True)
            self.append_log(f"ERROR: {exc}")

    def validate_chainner_chain(self) -> None:
        analysis, text = self._resolve_chainner_analysis()
        self.chainner_chain_info_view.setPlainText(text)
        if analysis is None:
            self.set_status_message(text, error=True)
            return
        if analysis.warnings:
            self.set_status_message(
                f"chaiNNer chain validation found {len(analysis.warnings)} issue(s).",
                error=True,
            )
            self.append_log(f"chaiNNer validation warnings: {len(analysis.warnings)} issue(s) found.")
            for warning in analysis.warnings:
                self.append_log(f"chaiNNer validation: {warning}")
        else:
            self.set_status_message("chaiNNer chain validation passed.")
            self.append_log("chaiNNer validation: no obvious issues detected.")
