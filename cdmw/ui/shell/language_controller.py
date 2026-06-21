from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from cdmw.ui.localization import (
    LANGUAGE_WARNING,
    collect_translatable_source_strings,
    language_name_for_code,
    write_language_file,
)


class LanguageControllerMixin:
    """Language switching and translation file import/export for the shell window."""

    def _apply_ui_language(self) -> None:
        self.settings_tab.set_language_options(
            self.ui_localizer.available_languages(),
            current_code=self.ui_localizer.language_code,
        )
        if hasattr(self, "texture_editor_tab"):
            self.texture_editor_tab.set_ui_translator(self.ui_localizer.translate)
        self.ui_localizer.apply(self)
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
        try:
            source_roots = (
                Path(__file__).resolve().parents[2],
            )
            translations = collect_translatable_source_strings(source_roots)
            translations.update(self.ui_localizer.collect_source_strings(self))
            for key in list(translations):
                translations[key] = self.ui_localizer.translations.get(key, translations.get(key, ""))
            write_language_file(
                Path(selected),
                language_code=language_code,
                language_name=language_name,
                translations=translations,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Export Language File", f"Could not export language file:\n{exc}")
            return
        QMessageBox.information(
            self,
            "Export Language File",
            f"Exported language file:\n{selected}\n\n{LANGUAGE_WARNING}",
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
        try:
            language_code, language_name, target_path = self.ui_localizer.import_language_file(Path(selected))
        except Exception as exc:
            QMessageBox.warning(self, "Import Language File", f"Could not import language file:\n{exc}")
            return
        self.settings.setValue("appearance/language", language_code)
        self.settings.sync()
        self._apply_ui_language()
        QMessageBox.information(
            self,
            "Import Language File",
            f"Imported language: {language_name} ({language_code})\nStored at:\n{target_path}\n\n{LANGUAGE_WARNING}",
        )
