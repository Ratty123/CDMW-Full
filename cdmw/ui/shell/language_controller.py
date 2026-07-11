from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from cdmw.ui.localization import (
    LANGUAGE_WARNING,
    bundled_translatable_source_strings,
    language_name_for_code,
)
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.ui.shell.request_task_controller import request_task_controller_for_guard
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
        self.settings_tab.set_language_options(
            self.ui_localizer.available_languages(),
            current_code=self.ui_localizer.language_code,
        )
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
        self._update_ncnn_preset_hint()
        self._schedule_column_autofit()

    def _handle_language_changed(self, language_code: str) -> None:
        try:
            self.ui_localizer.load_language(language_code)
        except Exception as exc:
            QMessageBox.warning(self, "Language", f"Could not load language:\n{exc}")
            self.ui_localizer.load_language("en")
        self.settings.setValue("appearance/language", self.ui_localizer.language_code)
        self.settings.sync()
        self._apply_ui_language()
        self.set_status_message(f"Language changed to {self.ui_localizer.language_name}.")

    def _export_language_file(self) -> None:
        language_code = self.ui_localizer.language_code or "en"
        language_name = self.ui_localizer.language_name or language_name_for_code(language_code)
        default_name = self.settings_file_path.parent / f"{language_code}_language.json"
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Language File",
            str(default_name),
            "JSON Files (*.json);;All Files (*)",
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
                tuple(sorted(translations.items())),
            ),
            run_language_export,
            status_message=f"Exporting language file {Path(selected).name}...",
            on_complete=lambda result: QMessageBox.information(
                self,
                "Export Language File",
                f"Exported language file:\n{result.output_path}\n\n{LANGUAGE_WARNING}",
            )
            if isinstance(result, LanguageExportResult)
            else None,
            on_error=lambda message: QMessageBox.warning(
                self,
                "Export Language File",
                f"Could not export language file:\n{message}",
            ),
        )

    def _import_language_file(self) -> None:
        selected, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import Language File",
            str(self.language_dir if self.language_dir.exists() else self.settings_file_path.parent),
            "JSON Files (*.json);;All Files (*)",
        )
        if not selected:
            return

        def _complete(result: object) -> None:
            if not isinstance(result, LanguageImportResult):
                QMessageBox.warning(self, "Import Language File", "Language importer returned an unexpected result.")
                return
            self.ui_localizer.install_imported_language(
                result.language_code,
                result.language_name,
                dict(result.translations),
                result.target_path,
            )
            self.settings.setValue("appearance/language", result.language_code)
            self.settings.sync()
            self._apply_ui_language()
            QMessageBox.information(
                self,
                "Import Language File",
                f"Imported language: {result.language_name} ({result.language_code})\nStored at:\n{result.target_path}\n\n{LANGUAGE_WARNING}",
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
            status_message=f"Importing language file {Path(selected).name}...",
            on_complete=_complete,
            on_error=lambda message: QMessageBox.warning(
                self,
                "Import Language File",
                f"Could not import language file:\n{message}",
            ),
        )
