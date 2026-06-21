from __future__ import annotations

import dataclasses
import json
import platform
import sys
import time
import zipfile
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
from cdmw.core.chainner import analyze_chainner_chain_paths, format_chainner_analysis
from cdmw.models import AppConfig, ChainnerChainAnalysis, default_config
from cdmw.services.diagnostics_service import (
    diagnostic_report_index,
    format_issue_summary,
    latest_diagnostic_report_files,
)
from cdmw.services.workspace_layout import workspace_paths
from cdmw.ui.shell.settings_bridge import (
    decode_profile_setting_value as _decode_profile_setting_value,
    encode_profile_setting_value as _encode_profile_setting_value,
)
from cdmw.ui.themes import UI_THEME_SCHEMES


class ProfileControllerMixin:
    """Profile import/export and local diagnostic bundle actions for the shell window."""

    def _crash_reports_dir(self) -> Path:
        return workspace_paths(self.settings_file_path.parent)["crash_reports_dir"]

    def _collect_profile_payload(self) -> Dict[str, object]:
        settings_snapshot = self._collect_profile_settings_snapshot()
        return {
            "app": APP_TITLE,
            "profile_format": 3,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "theme": self.current_theme_key,
            "config": dataclasses.asdict(self.collect_config()),
            "settings": settings_snapshot,
            "settings_key_count": len(settings_snapshot),
        }

    def _collect_profile_settings_snapshot(self) -> Dict[str, object]:
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

    def _restore_profile_settings_snapshot(self, snapshot: object) -> int:
        if not isinstance(snapshot, dict):
            return 0
        restored = 0
        for raw_key, raw_value in snapshot.items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            try:
                self.settings.setValue(
                    key,
                    _decode_profile_setting_value(raw_value, qbytearray_type=QByteArray),
                )
                restored += 1
            except Exception:
                continue
        self.settings.sync()
        return restored

    def _profile_theme_from_payload(self, payload: object) -> str:
        if isinstance(payload, dict):
            settings_snapshot = payload.get("settings")
            if isinstance(settings_snapshot, dict):
                theme_value = _decode_profile_setting_value(settings_snapshot.get("appearance/theme"))
                theme_text = str(theme_value or "").strip()
                if theme_text in UI_THEME_SCHEMES:
                    return theme_text
            theme_value = payload.get("theme")
            theme_text = str(theme_value or "").strip()
            if theme_text in UI_THEME_SCHEMES:
                return theme_text
        return self.current_theme_key

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

    def _resolve_chainner_analysis(self) -> Tuple[Optional[ChainnerChainAnalysis], str]:
        chain_path_text = self.chainner_chain_path_edit.text().strip()
        if not chain_path_text:
            return None, "Select a .chn file to inspect and validate it."

        try:
            chain_path = Path(chain_path_text).expanduser().resolve()
        except OSError as exc:
            return None, f"Could not resolve chain path: {exc}"

        if not chain_path.exists() or not chain_path.is_file():
            return None, f"Chain file not found: {chain_path}"

        original_root_text = self.original_dds_edit.text().strip()
        staging_root_text = self.dds_staging_root_edit.text().strip()
        png_root_text = self.png_root_edit.text().strip()
        original_root = Path(original_root_text).expanduser().resolve() if original_root_text else None
        staging_root = Path(staging_root_text).expanduser().resolve() if staging_root_text else None
        png_root = Path(png_root_text).expanduser().resolve() if png_root_text else None

        analysis = analyze_chainner_chain_paths(
            chain_path,
            original_dds_root=original_root,
            staging_png_root=staging_root,
            png_root=png_root,
            chainner_override_json=self.chainner_override_edit.toPlainText(),
        )
        text = format_chainner_analysis(analysis)

        notes: List[str] = []
        if self.chainner_override_edit.toPlainText().strip():
            notes.append(
                "Override JSON is configured. Runtime overrides may replace some hardcoded chain paths shown above."
            )
        if original_root is None or png_root is None:
            notes.append(
                "Path-mismatch validation is limited until Original DDS root and PNG root are configured. DDS staging validation is also limited until DDS staging root is configured when staging is enabled."
            )
        if notes:
            text += "\n\nNotes:\n" + "\n".join(f"- {note}" for note in notes)

        return analysis, text

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
            target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
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
            payload = json.loads(source.read_text(encoding="utf-8"))
            raw_config = payload.get("config", payload) if isinstance(payload, dict) else payload
            if not isinstance(raw_config, dict):
                raise ValueError("Profile file is invalid. Expected a JSON object.")

            defaults = default_config()
            config_values = dataclasses.asdict(defaults)
            for key in list(config_values):
                if key in raw_config:
                    config_values[key] = raw_config[key]

            imported_config = AppConfig(**config_values)
            restored_settings = 0
            theme_text = self._profile_theme_from_payload(payload)
            if isinstance(payload, dict):
                restored_settings = self._restore_profile_settings_snapshot(payload.get("settings"))
            self._apply_profile_config(imported_config, theme_key=theme_text)
            if restored_settings:
                self._apply_profile_settings_snapshot_to_ui(theme_key=theme_text)
            message = f"Profile imported from {source}"
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

            analysis, analysis_text = self._resolve_chainner_analysis()
            cache_files: List[Dict[str, object]] = []
            if self.archive_cache_root.exists():
                for cache_file in sorted(self.archive_cache_root.glob("*")):
                    if not cache_file.is_file():
                        continue
                    try:
                        stat = cache_file.stat()
                    except OSError:
                        continue
                    cache_files.append(
                        {
                            "name": cache_file.name,
                            "size_bytes": stat.st_size,
                            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                        }
                    )

            diagnostics = {
                "app": APP_TITLE,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "platform": platform.platform(),
                "python_version": sys.version,
                "executable": sys.executable,
                "frozen": bool(getattr(sys, "frozen", False)),
                "theme": self.current_theme_key,
                "settings_file": str(self.settings_file_path),
                "archive_cache_root": str(self.archive_cache_root),
                "archive_cache_files": cache_files,
                "profile": self._collect_profile_payload(),
                "chainner_warning_count": len(analysis.warnings) if analysis is not None else None,
            }

            crash_reports_dir = self._crash_reports_dir()
            crash_report_candidates = latest_diagnostic_report_files(crash_reports_dir, limit=20)
            latest_log = next((path for path in crash_report_candidates if path.suffix.lower() == ".log"), None)
            issue_summary = format_issue_summary(
                app_title=APP_TITLE,
                app_version=APP_VERSION,
                report_path=latest_log,
                context=None if latest_log is not None else self._collect_crash_context(),
            )
            diagnostics_index = diagnostic_report_index(crash_report_candidates)
            readme_path = Path(__file__).resolve().parents[3] / "README.md"
            notices_path = Path(__file__).resolve().parents[3] / "THIRD_PARTY_NOTICES.md"
            license_path = Path(__file__).resolve().parents[3] / "LICENSE"

            target.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("diagnostics.json", json.dumps(diagnostics, indent=2))
                archive.writestr("issue_summary.txt", issue_summary)
                archive.writestr("diagnostics_index.json", json.dumps(diagnostics_index, indent=2))
                archive.writestr("chainner_analysis.txt", analysis_text)
                archive.writestr("live_log.txt", self.log_view.toPlainText())
                archive.writestr("archive_scan_log.txt", self.archive_log_view.toPlainText())
                if self.settings_file_path.exists():
                    archive.writestr(
                        self.settings_file_path.name,
                        self.settings_file_path.read_text(encoding="utf-8"),
                    )
                if readme_path.exists():
                    archive.writestr(readme_path.name, readme_path.read_text(encoding="utf-8"))
                if notices_path.exists():
                    archive.writestr(notices_path.name, notices_path.read_text(encoding="utf-8"))
                if license_path.exists():
                    archive.writestr(license_path.name, license_path.read_text(encoding="utf-8"))
                for crash_report in crash_report_candidates:
                    try:
                        archive.writestr(
                            f"crash_reports/{crash_report.name}",
                            crash_report.read_text(encoding="utf-8", errors="replace"),
                        )
                    except OSError:
                        pass
                for archive_name, archive_text in self.text_search_tab.diagnostic_entries().items():
                    archive.writestr(archive_name, archive_text)

            self.set_status_message(f"Diagnostic bundle exported to {target}")
            self.append_log(f"Diagnostic bundle exported: {target}")
        except Exception as exc:
            self.set_status_message(str(exc), error=True)
            self.append_log(f"ERROR: {exc}")

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
