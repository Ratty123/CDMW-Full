from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from cdmw.domain.localization import freeze_translation_entry
from cdmw.ui.localization import (
    LANGUAGE_WARNING,
    bundled_translatable_source_strings,
    language_name_for_code,
)
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.ui.shell.request_task_controller import request_task_controller_for_guard
from cdmw.ui.shell.theme_controller import apply_app_fonts
from cdmw.workers.localization_workers import (
    LanguageExportRequest,
    LanguageExportResult,
    LanguageImportRequest,
    LanguageImportResult,
    run_language_export,
    run_language_import,
)


class LanguageControllerMixin:
    """Language switching and translation file import/export for the shell window."""

    def _apply_ui_language(self) -> None:
        activate_tracking = getattr(self.ui_localizer, "activate_runtime_tracking", None)
        if callable(activate_tracking):
            activate_tracking(self)
        self.settings_tab.set_language_options(
            self.ui_localizer.available_languages(),
            current_code=self.ui_localizer.language_code,
        )
        language_combo = getattr(self.settings_tab, "language_combo", None)
        if language_combo is not None:
            language_combo.setProperty("_i18n_skip_combo_items", True)
        texture_editor_tab = created_tool_widget(getattr(self, "texture_editor_tab", None))
        if texture_editor_tab is not None:
            texture_editor_tab.set_ui_translator(self.ui_localizer.translate)
        # A newly constructed English UI already contains its source strings.
        # Walking the whole widget tree only becomes necessary after a real
        # translation has been applied (including when switching back to
        # English).
        translation_applied = bool(getattr(self, "_ui_translation_applied", False))
        if self.ui_localizer.language_code != "en" or translation_applied:
            self.ui_localizer.apply(self)
            self._ui_translation_applied = True
        else:
            mark_source_tree_current = getattr(
                self.ui_localizer,
                "mark_source_tree_current",
                None,
            )
            if callable(mark_source_tree_current):
                mark_source_tree_current(self)
        refresh_settings_navigation = getattr(
            self.settings_tab,
            "_apply_section_nav_style",
            None,
        )
        if callable(refresh_settings_navigation):
            refresh_settings_navigation()
        self._update_ncnn_preset_hint()
        self._schedule_column_autofit()

    def _handle_language_changed(self, language_code: str) -> None:
        try:
            self.ui_localizer.load_language(language_code)
        except Exception as exc:
            QMessageBox.warning(
                self,
                self.ui_localizer.translate("Language"),
                self.ui_localizer.translate_rendered(f"Could not load language:\n{exc}"),
            )
            self.ui_localizer.load_language("en")
        self.settings.setValue("appearance/language", self.ui_localizer.language_code)
        self.settings.sync()
        app = QApplication.instance()
        if app is not None:
            apply_app_fonts(app, self.settings)
        self._apply_ui_language()
        self.set_status_message(
            self.ui_localizer.translate_rendered(
                f"Language changed to {self.ui_localizer.language_name}."
            )
        )

    def _export_language_file(self) -> None:
        language_code = self.ui_localizer.language_code or "en"
        language_name = self.ui_localizer.language_name or language_name_for_code(language_code)
        default_name = self.settings_file_path.parent / f"{language_code}_language.json"
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self,
            self.ui_localizer.translate("Export Language File"),
            str(default_name),
            self.ui_localizer.translate("JSON Files (*.json);;All Files (*)"),
        )
        if not selected:
            return
        translations = bundled_translatable_source_strings()
        translations.update(self.ui_localizer.collect_source_strings(self))
        for key in list(translations):
            translations[key] = self.ui_localizer.translations.get(key, translations.get(key, ""))
        controller = request_task_controller_for_guard(
            self,
            self,
            attribute="_language_task_controller",
            worker_label="language_io",
        )
        controller.start(
            LanguageExportRequest(
                Path(selected),
                language_code,
                language_name,
                tuple(
                    (source, freeze_translation_entry(entry))
                    for source, entry in sorted(translations.items())
                ),
            ),
            run_language_export,
            status_message=self.ui_localizer.translate_rendered(
                f"Exporting language file {Path(selected).name}..."
            ),
            on_complete=lambda result: QMessageBox.information(
                self,
                self.ui_localizer.translate("Export Language File"),
                self.ui_localizer.translate_rendered(
                    f"Exported language file:\n{result.output_path}\n\n"
                    f"{self.ui_localizer.translate(LANGUAGE_WARNING)}"
                ),
            )
            if isinstance(result, LanguageExportResult)
            else None,
            on_error=lambda message: QMessageBox.warning(
                self,
                self.ui_localizer.translate("Export Language File"),
                self.ui_localizer.translate_rendered(
                    f"Could not export language file:\n{message}"
                ),
            ),
        )

    def _import_language_file(self) -> None:
        selected, _selected_filter = QFileDialog.getOpenFileName(
            self,
            self.ui_localizer.translate("Import Language File"),
            str(self.language_dir if self.language_dir.exists() else self.settings_file_path.parent),
            self.ui_localizer.translate("JSON Files (*.json);;All Files (*)"),
        )
        if not selected:
            return

        def _complete(result: object) -> None:
            if not isinstance(result, LanguageImportResult):
                QMessageBox.warning(
                    self,
                    self.ui_localizer.translate("Import Language File"),
                    self.ui_localizer.translate(
                        "Language importer returned an unexpected result."
                    ),
                )
                return
            self.ui_localizer.install_imported_language(
                result.language_code,
                result.language_name,
                dict(result.translations),
                result.target_path,
            )
            self.settings.setValue("appearance/language", result.language_code)
            self.settings.sync()
            app = QApplication.instance()
            if app is not None:
                apply_app_fonts(app, self.settings)
            self._apply_ui_language()
            QMessageBox.information(
                self,
                self.ui_localizer.translate("Import Language File"),
                self.ui_localizer.translate_rendered(
                    f"Imported language: {result.language_name} ({result.language_code})\n"
                    f"Stored at:\n{result.target_path}\n\n"
                    f"{self.ui_localizer.translate(LANGUAGE_WARNING)}"
                ),
            )

        controller = request_task_controller_for_guard(
            self,
            self,
            attribute="_language_task_controller",
            worker_label="language_io",
        )
        controller.start(
            LanguageImportRequest(Path(selected), self.language_dir),
            run_language_import,
            status_message=self.ui_localizer.translate_rendered(
                f"Importing language file {Path(selected).name}..."
            ),
            on_complete=_complete,
            on_error=lambda message: QMessageBox.warning(
                self,
                self.ui_localizer.translate("Import Language File"),
                self.ui_localizer.translate_rendered(
                    f"Could not import language file:\n{message}"
                ),
            ),
        )
