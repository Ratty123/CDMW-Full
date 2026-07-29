from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSettings, Qt
from PySide6.QtGui import QAction, QFontMetrics, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QStatusBar,
    QTableView,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import cdmw.ui.localization as localization_module
from cdmw.domain.localization import (
    BUILTIN_LANGUAGES,
    canonical_language_code,
    plural_category,
)
from cdmw.services.localization_file_service import (
    coerce_translation_payload,
    write_language_file,
)
from cdmw.services.startup_localization_service import load_startup_localizer
from cdmw.ui.localization import UiLocalizer
from cdmw.ui.localization_catalogs_v2 import (
    BUILTIN_LANGUAGES as BUILTIN_CATALOGS,
    SOURCE_STRING_CATALOGUE,
)
from cdmw.ui.shell.language_controller import LanguageControllerMixin
from cdmw.ui.panel_widgets import EmptyStateTreeWidget
from cdmw.ui.shell.theme_controller import _resolved_app_fonts
from cdmw.workers.localization_workers import (
    LanguageImportResult,
    LanguageImportRequest,
    run_language_import,
)
from scripts.generate_ui_localization_manifest import build_manifest
from scripts.validate_ui_localization_catalogs import (
    _has_encoding_damage,
    _preserves_layout_whitespace,
    validate_catalogs,
)


EXPECTED_LANGUAGES = (
    ("en", "English"),
    ("de", "Deutsch"),
    ("es-ES", "Español (España)"),
    ("es-419", "Español (Latinoamérica)"),
    ("fr", "Français"),
    ("it", "Italiano"),
    ("pt-BR", "Português (Brasil)"),
    ("pl", "Polski"),
    ("ru", "Русский"),
    ("tr", "Türkçe"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("zh-Hans", "简体中文"),
    ("zh-Hant", "繁體中文"),
)


def test_catalog_encoding_damage_detection_distinguishes_real_punctuation() -> None:
    assert _has_encoding_damage("{count} files", "{count} plik?w")
    assert _has_encoding_damage("{count} files", "{count} ?????")
    assert _has_encoding_damage("Planner", "plannerâ€™s")
    assert not _has_encoding_damage("Why", "¿Por qué?")
    assert _preserves_layout_whitespace(
        "\n\nBackup: {value_0}",
        "\n\nSicherung: {value_0}",
    )
    assert not _preserves_layout_whitespace(
        "\n\nBackup: {value_0}",
        "Sicherung: {value_0}",
    )


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_builtin_selector_order_names_and_catalog_key_parity() -> None:
    assert tuple(
        (language.code, language.display_name)
        for language in BUILTIN_LANGUAGES
    ) == EXPECTED_LANGUAGES
    assert tuple(BUILTIN_CATALOGS) == tuple(code for code, _name in EXPECTED_LANGUAGES)
    expected_keys = set(SOURCE_STRING_CATALOGUE)
    assert expected_keys
    for code, payload in BUILTIN_CATALOGS.items():
        translations = payload["translations"]
        assert isinstance(translations, dict)
        assert set(translations) == expected_keys, code
        assert all(
            (
                isinstance(value, str)
                and bool(value.strip())
            )
            or (
                isinstance(value, dict)
                and bool(value)
                and all(bool(branch.strip()) for branch in value.values())
            )
            for value in translations.values()
        ), code


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("EN", "en"),
        ("es", "es-ES"),
        ("ES_es", "es-ES"),
        ("es_419", "es-419"),
        ("PT_br", "pt-BR"),
        ("zh_cn", "zh-Hans"),
        ("ZH_hans", "zh-Hans"),
        ("zh_TW", "zh-Hant"),
        ("zh-hk", "zh-Hant"),
        ("Custom_Language", "custom-language"),
    ),
)
def test_locale_normalization_and_legacy_aliases(raw: str, expected: str) -> None:
    assert canonical_language_code(raw) == expected


def test_language_change_persists_the_canonical_code_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_path = tmp_path / "settings.ini"
    settings = QSettings(str(settings_path), QSettings.IniFormat)
    localizer = UiLocalizer(
        language_dir=tmp_path / "languages",
        language_code="en",
    )
    applied: list[str] = []
    statuses: list[str] = []
    shell = type(
        "_Shell",
        (),
        {
            "ui_localizer": localizer,
            "settings": settings,
            "_apply_ui_language": lambda self: applied.append(
                self.ui_localizer.language_code
            ),
            "set_status_message": lambda _self, message: statuses.append(message),
        },
    )()
    monkeypatch.setattr(
        "cdmw.ui.shell.language_controller.apply_app_fonts",
        lambda *_args, **_kwargs: None,
    )

    LanguageControllerMixin._handle_language_changed(shell, "ES_es")

    assert localizer.language_code == "es-ES"
    assert applied == ["es-ES"]
    assert statuses
    reopened = QSettings(str(settings_path), QSettings.IniFormat)
    assert reopened.value("appearance/language") == "es-ES"


def test_imported_cjk_overlay_applies_font_fallback_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    localizer = UiLocalizer(
        language_dir=tmp_path / "languages",
        language_code="en",
    )
    applied: list[str] = []
    font_languages: list[str] = []
    target_path = tmp_path / "languages" / "zh-Hans.json"
    result = LanguageImportResult(
        1,
        "zh-Hans",
        "简体中文",
        target_path,
        (("Language", "语言"),),
    )

    class _Controller:
        def start(self, _request: object, _worker: object, **callbacks: object) -> bool:
            callbacks["on_complete"](result)  # type: ignore[index,operator]
            return True

    shell = type(
        "_Shell",
        (),
        {
            "ui_localizer": localizer,
            "settings": settings,
            "language_dir": tmp_path / "languages",
            "settings_file_path": tmp_path / "settings.ini",
            "_apply_ui_language": lambda self: applied.append(
                self.ui_localizer.language_code
            ),
        },
    )()
    monkeypatch.setattr(
        "cdmw.ui.shell.language_controller.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(tmp_path / "import.json"), ""),
    )
    monkeypatch.setattr(
        "cdmw.ui.shell.language_controller.request_task_controller_for_guard",
        lambda *_args, **_kwargs: _Controller(),
    )
    monkeypatch.setattr(
        "cdmw.ui.shell.language_controller.apply_app_fonts",
        lambda *_args, **_kwargs: font_languages.append(localizer.language_code),
    )
    monkeypatch.setattr(
        "cdmw.ui.shell.language_controller.QMessageBox.information",
        lambda *_args, **_kwargs: None,
    )

    LanguageControllerMixin._import_language_file(shell)

    assert QApplication.instance() is app
    assert localizer.language_code == "zh-Hans"
    assert applied == ["zh-Hans"]
    assert font_languages == ["zh-Hans"]
    assert settings.value("appearance/language") == "zh-Hans"


@pytest.mark.parametrize(
    ("code", "counts_and_categories"),
    (
        ("en", ((1, "one"), (2, "other"), (1.5, "other"))),
        ("fr", ((0, "one"), (1, "one"), (1.5, "one"), (2, "other"), (1_000_000, "many"))),
        ("es-ES", ((1, "one"), (1.0, "one"), (2, "other"), (1_000_000, "many"))),
        ("it", ((1, "one"), (1.0, "other"), (2, "other"), (1_000_000, "many"))),
        ("pt-BR", ((0, "one"), (0.5, "one"), (1, "one"), (2, "other"))),
        (
            "pl",
            ((1, "one"), (2, "few"), (5, "many"), (12, "many"), (22, "few"), (1.2, "other")),
        ),
        (
            "ru",
            ((1, "one"), (2, "few"), (5, "many"), (11, "many"), (21, "one"), (1.2, "other")),
        ),
        ("tr", ((0, "other"), (1, "other"), (2, "other"))),
        ("ja", ((0, "other"), (1, "other"), (2, "other"))),
        ("ko", ((0, "other"), (1, "other"), (2, "other"))),
        ("zh-Hans", ((0, "other"), (1, "other"), (2, "other"))),
        ("zh-Hant", ((0, "other"), (1, "other"), (2, "other"))),
    ),
)
def test_cldr_plural_rule_boundaries(
    code: str,
    counts_and_categories: tuple[tuple[float, str], ...],
) -> None:
    assert tuple(
        plural_category(code, count)
        for count, _category in counts_and_categories
    ) == tuple(category for _count, category in counts_and_categories)


def test_version_1_and_version_2_custom_pack_contracts() -> None:
    code, name, v1 = coerce_translation_payload(
        {
            "language_code": "sv",
            "language_name": "Svenska",
            "translations": {"Language": "Språk"},
        }
    )
    assert (code, name, v1) == ("sv", "Svenska", {"Language": "Språk"})

    with pytest.raises(ValueError, match="placeholders"):
        coerce_translation_payload(
            {
                "schema_version": 1,
                "language_code": "sv",
                "translations": {
                    "Saved {count} files": "Sparade filer",
                },
            }
        )

    _code, _name, v2 = coerce_translation_payload(
        {
            "schema_version": 2,
            "language_code": "pl",
            "language_name": "Polski custom",
            "translations": {
                "{count} files": {
                    "one": "{count} plik niestandardowy",
                }
            },
        }
    )
    assert v2["{count} files"] == {"one": "{count} plik niestandardowy"}

    with pytest.raises(ValueError, match="placeholders"):
        coerce_translation_payload(
            {
                "schema_version": 2,
                "language_code": "sv",
                "translations": {
                    "Found {count} items": {"other": "Hittade objekt"}
                },
            }
        )
    with pytest.raises(ValueError, match="Unknown plural category"):
        coerce_translation_payload(
            {
                "schema_version": 2,
                "language_code": "sv",
                "translations": {
                    "{count} files": {"several": "{count} filer"}
                },
            }
        )
    with pytest.raises(ValueError, match="Version-1 translation"):
        coerce_translation_payload(
            {
                "language_code": "sv",
                "translations": {"Language": {"other": "Språk"}},
            }
        )


def test_partial_custom_plural_falls_back_to_builtin_and_scalar_applies_to_all(
    tmp_path: Path,
) -> None:
    language_dir = tmp_path / "languages"
    write_language_file(
        language_dir / "sv.json",
        language_code="sv",
        language_name="Svenska",
        translations={
            "Language": "Språk",
            "{count} files": {"one": "{count} fil"},
        },
    )
    localizer = UiLocalizer(language_dir=language_dir, language_code="sv")
    assert localizer.translate("Language") == "Språk"
    assert localizer.translate("Settings") == "Settings"
    assert localizer.format_plural("{count} files", 1) == "1 fil"
    assert localizer.format_plural("{count} files", 2) == "2 files"

    write_language_file(
        language_dir / "no.json",
        language_code="no",
        language_name="Norsk",
        translations={"{count} files": "{count} filer"},
    )
    scalar = UiLocalizer(language_dir=language_dir, language_code="no")
    assert scalar.format_plural("{count} files", 1) == "1 filer"
    assert scalar.format_plural("{count} files", 7) == "7 filer"


def test_canonical_custom_pack_wins_alias_duplicate_and_reports_it(
    tmp_path: Path,
) -> None:
    language_dir = tmp_path / "languages"
    write_language_file(
        language_dir / "es.json",
        language_code="es",
        language_name="Alias Spanish",
        translations={"Language": "ALIAS"},
    )
    write_language_file(
        language_dir / "es-ES.json",
        language_code="es-ES",
        language_name="Canonical Spanish",
        translations={"Language": "CANONICAL"},
    )
    localizer = UiLocalizer(language_dir=language_dir, language_code="es")
    assert localizer.language_code == "es-ES"
    assert localizer.translate("Language") == "CANONICAL"
    assert any("Ignored duplicate language pack es.json" in warning for warning in localizer.language_warnings)
    assert (language_dir / "es.json").is_file()
    assert (language_dir / "es-ES.json").is_file()


def test_invalid_import_never_replaces_existing_canonical_pack(tmp_path: Path) -> None:
    language_dir = tmp_path / "languages"
    target = language_dir / "sv.json"
    target.parent.mkdir()
    target.write_bytes(b"existing")
    source = tmp_path / "invalid.json"
    source.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "language_code": "sv",
                "translations": {
                    "Found {count} items": {"other": "Hittade objekt"}
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="placeholders"):
        run_language_import(LanguageImportRequest(source, language_dir))
    assert target.read_bytes() == b"existing"
    assert not tuple(language_dir.glob(".*.tmp"))


def test_live_cycle_preserves_state_and_localizes_late_and_model_backed_text(
    tmp_path: Path,
) -> None:
    app = _app()
    root = QMainWindow()
    root.resize(720, 480)
    root.setWindowTitle("Settings")
    central = QWidget(root)
    layout = QVBoxLayout(central)
    label = QLabel("Language", central)
    label.setToolTip("Settings")
    label.setAccessibleName("Language")
    layout.addWidget(label)
    combo = QComboBox(central)
    combo.addItem("Language", "language")
    combo.addItem("Settings", "settings")
    combo.setCurrentIndex(1)
    layout.addWidget(combo)
    tabs = QTabWidget(central)
    tabs.addTab(QWidget(), "Settings")
    tabs.addTab(QWidget(), "Language")
    tabs.setTabToolTip(1, "Settings")
    tabs.setCurrentIndex(1)
    layout.addWidget(tabs)
    browser = QTextBrowser(central)
    browser.setHtml("<p><b>Language</b><br><i>Settings</i></p>")
    layout.addWidget(browser)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok
        | QDialogButtonBox.StandardButton.Cancel,
        parent=central,
    )
    layout.addWidget(buttons)
    model = QStandardItemModel(1, 1, central)
    model.setHorizontalHeaderLabels(["Settings"])
    model.setItem(0, 0, QStandardItem("Language"))
    table = QTableView(central)
    table.setModel(model)
    table.setColumnWidth(0, 173)
    table.selectRow(0)
    layout.addWidget(table)
    root.setCentralWidget(central)
    action = QAction("Settings", root)
    action.setToolTip("Language")
    action.setStatusTip("Settings")
    action.setWhatsThis("Language")
    root.addAction(action)

    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code="en")
    revisions: list[tuple[str, int]] = []
    localizer.language_changed.connect(lambda code, revision: revisions.append((code, revision)))
    localizer.activate_runtime_tracking(root, application=app)
    initial_geometry = root.geometry()
    initial_combo_index = combo.currentIndex()
    initial_tab_index = tabs.currentIndex()
    initial_selection = table.selectionModel().selectedRows()[0].row()

    for code, _name in EXPECTED_LANGUAGES:
        localizer.load_language(code)
        localizer.apply_registered_roots()
        assert label.text() == localizer.translate("Language")
        assert label.toolTip() == localizer.translate("Settings")
        assert label.accessibleName() == localizer.translate("Language")
        assert combo.currentIndex() == initial_combo_index
        assert tabs.currentIndex() == initial_tab_index
        assert table.selectionModel().selectedRows()[0].row() == initial_selection
        assert table.columnWidth(0) == 173
        assert root.geometry() == initial_geometry
        assert model.item(0, 0).text() == localizer.translate("Language")
        assert model.headerData(0, Qt.Orientation.Horizontal) == localizer.translate("Settings")
        assert action.text() == localizer.translate("Settings")
        assert action.statusTip() == localizer.translate("Settings")
        assert action.whatsThis() == localizer.translate("Language")
        assert tabs.tabToolTip(1) == localizer.translate("Settings")
        assert (
            buttons.button(QDialogButtonBox.StandardButton.Ok).text()
            == localizer.translate("OK")
        )
        assert (
            buttons.button(QDialogButtonBox.StandardButton.Cancel).text()
            == localizer.translate("Cancel")
        )
        assert browser.toPlainText().splitlines() == [
            localizer.translate("Language"),
            localizer.translate("Settings"),
        ]

    late = QLabel("Settings", central)
    layout.addWidget(late)
    late.show()
    app.processEvents()
    assert late.text() == localizer.translate("Settings")

    label.setText("Ready")
    localizer.apply(label)
    assert label.text() == localizer.translate("Ready")

    localizer.load_language("en")
    localizer.apply_registered_roots()
    assert label.text() == "Ready"
    assert late.text() == "Settings"
    assert revisions[-1] == ("en", localizer.revision)
    localizer.shutdown()
    root.deleteLater()
    app.processEvents()


def test_real_main_window_honors_saved_non_english_locale_offscreen(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "saved-german.ini"
    script = "\n".join(
        (
            "import os, sys",
            "from pathlib import Path",
            "os.environ['QT_QPA_PLATFORM'] = 'offscreen'",
            "os.environ['CDMW_GUI_STARTUP_SMOKE'] = '1'",
            "from PySide6.QtWidgets import QApplication",
            "from cdmw.app.events import AppEventBus",
            "from cdmw.services.service_container import ServiceContainer",
            "from cdmw.services.settings_service import create_settings",
            "from cdmw.ui.main_window import MainWindow",
            "from cdmw.ui.shell.app_context import AppContext",
            "app = QApplication.instance() or QApplication([])",
            f"settings = create_settings(settings_file_path=Path({str(settings_path)!r}))",
            "settings.setValue('appearance/language', 'de')",
            "settings.sync()",
            "context = AppContext(settings, ServiceContainer.create_default(settings=settings), AppEventBus())",
            "window = MainWindow(app_context=context)",
            "assert window.ui_localizer.language_code == 'de'",
            "assets_index = window.main_tabs.indexOf(window.assets_tabs)",
            "assert window.main_tabs.tabText(assets_index) == window.ui_localizer.translate('Assets')",
            "assert window.settings_tab.export_language_button.text() == window.ui_localizer.translate('Export Language File...')",
            "window.reset_progress(1234)",
            "assert window.total_files_value.text() == window.ui_localizer.format_number(1234)",
            "window._handle_language_changed('fr')",
            "assert window.total_files_value.text() == window.ui_localizer.format_number(1234)",
            "window._finalize_close()",
            "assert app.property('_cdmw_ui_localizer') is None",
            "window.deleteLater()",
            "app.processEvents()",
            "sys.stdout.flush(); sys.stderr.flush(); os._exit(0)",
        )
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "CDMW_GUI_STARTUP_SMOKE": "1",
        },
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    assert result.returncode == 0, (
        "Saved-locale production construction failed.\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def test_readonly_plain_and_rich_text_switch_back_to_english_and_shutdown_clears_owner(
    tmp_path: Path,
) -> None:
    app = _app()
    root = QWidget()
    plain = QPlainTextEdit("Save", root)
    plain.setReadOnly(True)
    rich = QTextEdit("Save", root)
    rich.setReadOnly(True)
    localizer = UiLocalizer(
        language_dir=tmp_path / "languages",
        language_code="de",
    )
    localizer.activate_runtime_tracking(root, application=app)
    localizer.apply(root)

    assert plain.toPlainText() == "Speichern"
    assert rich.toPlainText() == "Speichern"

    localizer.load_language("en")
    localizer.apply_registered_roots()
    assert plain.toPlainText() == "Save"
    assert rich.toPlainText() == "Save"

    assert app.property("_cdmw_ui_localizer") is localizer
    localizer.shutdown()
    assert app.property("_cdmw_ui_localizer") is None
    root.deleteLater()


def test_locale_aware_presentation_formatters_use_selected_locale(tmp_path: Path) -> None:
    app = _app()
    english = UiLocalizer(language_dir=tmp_path / "languages", language_code="en")
    german = UiLocalizer(language_dir=tmp_path / "languages", language_code="de")
    assert english.format_number(1234.5, decimal_places=1) != german.format_number(
        1234.5,
        decimal_places=1,
    )
    assert german.format_file_size(1536).endswith(" KiB")
    assert german.format_duration(65).endswith(" min 5 s")
    assert german.format_date(date(2026, 7, 29))
    assert german.format_time(time(13, 45, 12))
    assert german.format_datetime(datetime(2026, 7, 29, 13, 45, 12))
    assert "1.234" in german.format_plural("{count} files", 1234)
    assert "1.234" in german.translate_rendered("All items (1,234)")
    assert "1.234" in german.translate_rendered(
        "Found 1234 DDS files. Processing..."
    )
    assert german.translate_rendered("Part (ID 1234)").endswith("(ID 1234)")
    assert german.format(
        "Modified: {when}",
        when=date(2026, 7, 29),
    ).endswith(german.format_date(date(2026, 7, 29)))
    count_label = QLabel()
    german.set_number_text(count_label, 1234)
    assert count_label.text() == german.format_number(1234)
    german.load_language("fr")
    german.apply(count_label)
    assert count_label.text() == german.format_number(1234)
    count_label.deleteLater()
    app.processEvents()


@pytest.mark.parametrize(
    ("code", "representative"),
    (
        ("ja", "日"),
        ("ko", "한"),
        ("zh-Hans", "汉"),
        ("zh-Hant", "繁"),
    ),
)
def test_pyside_cjk_font_resolution_has_real_glyph_coverage(
    code: str,
    representative: str,
    tmp_path: Path,
) -> None:
    app = _app()
    settings = QSettings(str(tmp_path / f"{code}.ini"), QSettings.IniFormat)
    settings.setValue("appearance/language", code)
    settings.setValue("appearance/ui_font_family", "Arial")
    ui_font, _data_font, _density, _scale = _resolved_app_fonts(
        app,
        settings,
        screen_width=1920,
        screen_height=1080,
    )
    assert QFontMetrics(ui_font).inFontUcs4(ord(representative)), (
        code,
        ui_font.family(),
    )


def test_language_selector_size_hint_fits_every_native_label(tmp_path: Path) -> None:
    app = _app()
    settings = QSettings(str(tmp_path / "selector.ini"), QSettings.IniFormat)
    settings.setValue("appearance/language", "zh-Hans")
    settings.setValue("appearance/ui_font_family", "Arial")
    ui_font, _data_font, _density, _scale = _resolved_app_fonts(
        app,
        settings,
        screen_width=1920,
        screen_height=1080,
    )
    combo = QComboBox()
    combo.setFont(ui_font)
    for code, label in EXPECTED_LANGUAGES:
        combo.addItem(label, code)
    combo.ensurePolished()
    longest = max(
        QFontMetrics(combo.font()).horizontalAdvance(label)
        for _code, label in EXPECTED_LANGUAGES
    )
    assert combo.sizeHint().width() >= longest + 24
    combo.deleteLater()


def test_installed_file_dialog_wrapper_localizes_segments_and_restores_selected_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    root = QWidget()
    localizer = UiLocalizer(
        language_dir=tmp_path / "languages",
        language_code="de",
    )
    localizer.activate_runtime_tracking(root, application=app)
    captured: dict[str, tuple[object, ...]] = {}

    def fake_get_open_file_name(*args: object, **_kwargs: object) -> tuple[str, str]:
        captured["args"] = args
        return ("chosen.json", str(args[4]))

    monkeypatch.setitem(
        localization_module._FILE_DIALOG_ORIGINALS,
        "getOpenFileName",
        fake_get_open_file_name,
    )
    selected, selected_filter = QFileDialog.getOpenFileName(
        root,
        "Export Language File",
        "",
        "JSON Files (*.json);;All Files (*)",
        "All Files (*)",
    )

    forwarded = captured["args"]
    assert forwarded[1] == localizer.translate("Export Language File")
    assert forwarded[3] == "JSON-Dateien (*.json);;Alle Dateien (*)"
    assert forwarded[4] == "Alle Dateien (*)"
    assert selected == "chosen.json"
    assert selected_filter == "All Files (*)"
    localizer.shutdown()
    root.deleteLater()


def test_static_dialog_status_log_and_custom_empty_state_are_live_localized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RevisionPaintWidget(QWidget):
        def __init__(self, parent: QWidget) -> None:
            super().__init__(parent)
            self.update_calls = 0

        def update(self, *args: object) -> None:
            self.update_calls = getattr(self, "update_calls", 0) + 1
            super().update(*args)

    app = _app()
    root = QWidget()
    localizer = UiLocalizer(
        language_dir=tmp_path / "languages",
        language_code="de",
    )
    localizer.activate_runtime_tracking(root, application=app)
    message_args: list[object] = []
    item_args: list[object] = []

    def fake_information(*args: object, **_kwargs: object) -> object:
        message_args.extend(args)
        return QMessageBox.StandardButton.Ok

    def fake_get_item(*args: object, **_kwargs: object) -> tuple[str, bool]:
        item_args.extend(args)
        return (str(args[3][1]), True)

    monkeypatch.setitem(
        localization_module._STATIC_DIALOG_ORIGINALS,
        ("QMessageBox", "information"),
        fake_information,
    )
    monkeypatch.setitem(
        localization_module._STATIC_DIALOG_ORIGINALS,
        ("QInputDialog", "getItem"),
        fake_get_item,
    )

    QMessageBox.information(root, "Settings", "Language")
    selected, accepted = QInputDialog.getItem(
        root,
        "Settings",
        "Language",
        ["Language", "Settings"],
        0,
        False,
    )
    assert message_args[1:] == [
        localizer.translate("Settings"),
        localizer.translate("Language"),
    ]
    assert item_args[1] == localizer.translate("Settings")
    assert item_args[2] == localizer.translate("Language")
    assert item_args[3] == [
        localizer.translate("Language"),
        localizer.translate("Settings"),
    ]
    assert (selected, accepted) == ("Settings", True)

    status = QStatusBar(root)
    status.showMessage("Language")
    assert status.currentMessage() == localizer.translate("Language")
    custom_buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok,
        root,
    )
    custom_buttons.button(
        QDialogButtonBox.StandardButton.Ok
    ).setText("Create")
    localizer.apply(custom_buttons)
    assert custom_buttons.button(
        QDialogButtonBox.StandardButton.Ok
    ).text() == localizer.translate("Create")
    log = QPlainTextEdit(root)
    log.setReadOnly(True)
    log.appendPlainText("[12:34:56] Language")
    assert log.toPlainText() == (
        "[12:34:56] " + localizer.translate("Language")
    )
    empty = EmptyStateTreeWidget("Language", "Settings", root)
    localizer.apply(empty)
    assert empty.empty_title == localizer.translate("Language")
    assert empty.empty_detail == localizer.translate("Settings")
    empty.set_empty_state("Settings", "Language")
    assert empty.empty_title == localizer.translate("Settings")
    assert empty.empty_detail == localizer.translate("Language")
    painted = RevisionPaintWidget(root)
    localizer.apply(root)
    translated_revision_updates = painted.update_calls

    localizer.load_language("en")
    localizer.apply_registered_roots()
    assert painted.update_calls > translated_revision_updates
    assert status.currentMessage() == "Language"
    assert custom_buttons.button(
        QDialogButtonBox.StandardButton.Ok
    ).text() == "Create"
    assert log.toPlainText() == "[12:34:56] Language"
    assert empty.empty_title == "Settings"
    assert empty.empty_detail == "Language"
    localizer.shutdown()
    root.deleteLater()


def test_readonly_python_model_presentation_roles_translate_without_mutation(
    tmp_path: Path,
) -> None:
    class ReadOnlyPresentationModel(QAbstractTableModel):
        def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
            return 1

        def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
            return 1

        def data(
            self,
            index: QModelIndex,
            role: int = Qt.ItemDataRole.DisplayRole,
        ) -> object:
            if not index.isValid():
                return None
            if role == Qt.ItemDataRole.DisplayRole:
                return "Language"
            if role == Qt.ItemDataRole.ToolTipRole:
                return "Settings"
            return None

        def headerData(  # noqa: N802
            self,
            section: int,
            orientation: Qt.Orientation,
            role: int = Qt.ItemDataRole.DisplayRole,
        ) -> object:
            if (
                section == 0
                and orientation == Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole
            ):
                return "Settings"
            return None

    app = _app()
    root = QWidget()
    table = QTableView(root)
    model = ReadOnlyPresentationModel(table)
    table.setModel(model)
    localizer = UiLocalizer(
        language_dir=tmp_path / "languages",
        language_code="de",
    )
    localizer.activate_runtime_tracking(root, application=app)
    localizer.apply(root)
    index = model.index(0, 0)
    assert model.data(index) == localizer.translate("Language")
    assert model.data(index, Qt.ItemDataRole.ToolTipRole) == localizer.translate(
        "Settings"
    )
    assert model.headerData(
        0,
        Qt.Orientation.Horizontal,
    ) == localizer.translate("Settings")

    localizer.load_language("en")
    localizer.apply_registered_roots()
    assert model.data(index) == "Language"
    assert model.data(index, Qt.ItemDataRole.ToolTipRole) == "Settings"
    assert model.headerData(0, Qt.Orientation.Horizontal) == "Settings"
    localizer.shutdown()
    root.deleteLater()


def test_rich_text_translation_preserves_non_text_blocks() -> None:
    source = "<style>p { color: red; }</style><p>Language</p>"
    translated = localization_module._translate_html_text(
        source,
        lambda value: "Sprache" if value == "Language" else value,
    )
    assert "<style>p { color: red; }</style>" in translated
    assert "<p>Sprache</p>" in translated


def test_pre_qt_startup_localizer_uses_saved_custom_overlay(tmp_path: Path) -> None:
    settings_path = tmp_path / "CrimsonDesertModWorkbench.cfg"
    settings_path.write_text("[appearance]\nlanguage=sv\n", encoding="utf-8")
    write_language_file(
        tmp_path / "languages" / "sv.json",
        language_code="sv",
        language_name="Svenska",
        translations={"Starting application...": "Startar programmet..."},
    )
    localizer = load_startup_localizer(settings_path=settings_path)
    assert localizer.language_code == "sv"
    assert localizer.resolve_message("Starting application...").rendered == "Startar programmet..."
    assert localizer.resolve_message("Opening workspace...").rendered == "Opening workspace..."
    assert len(
        json.dumps(
            localizer.protocol_translations(),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ) < 48 * 1024


def test_generated_manifest_and_catalog_validation_are_current() -> None:
    packaged = json.loads(
        Path("cdmw/resources/localization/source_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert packaged == build_manifest()
    keys = {entry["key"] for entry in packaged["entries"]}
    assert {
        "Workers",
        "Preview Caches",
        "Reset Colour",
        "Finish Edit Mesh",
        "Save Edited Package",
        "Front",
        "Back",
        "Top",
        "Bottom",
        "Orbit",
        "Morph & Refit",
        "SCENE",
        "SELECTION",
        "DDS",
        "X",
        "Archive Mod Sources",
        "JSON Files",
        "Find matches: {value_0} / {value_1}",
        "Choose Material Color",
        "Sidecar: Ready",
        "Renderer ready, waiting for first frame | Backend: {value_0}",
        "FPS {value_0} | Interval {value_1} ms | P95 {value_2} ms",
        "No asset family",
        "Replacement source:",
        "Anthropic (Claude)",
        "No unapplied source-part changes.",
        "Preparing Archive Browser View",
        "Disabled - WIP. Placement swap/package flow is paused.",
        "No skeleton loaded",
        "Partial",
        "AES",
        "pending",
        "Average FPS",
        "Active/hover color",
        "Click anywhere on the body to create a socket at that spot.",
        "socket in use",
        "Updating app colors and preview panes...",
        " Placement workspace has {value_0} prefab/socket chain(s).",
        (
            "Build a loose mod package for edited prefab?\n\n"
            "{value_0}\n\n"
            "Original game archives will not be modified."
        ),
    } <= keys
    entries = {entry["key"]: entry for entry in packaged["entries"]}
    assert any(
        origin["sink"] == "python-return:_preview_match_status_text"
        for origin in entries["Find matches: {value_0} / {value_1}"]["origins"]
    )
    assert any(
        origin["sink"] == "python-return:material_sidecar_choose_color_dialog_title"
        for origin in entries["Choose Material Color"]["origins"]
    )
    assert any(
        origin["sink"] == "csharp:csharp-return:RendererMetricsText"
        for origin in entries[
            "FPS {value_0} | Interval {value_1} ms | P95 {value_2} ms"
        ]["origins"]
    )
    assert any(
        origin["sink"] == "EmptyStateTreeWidget"
        for origin in entries["No asset family"]["origins"]
    )
    assert any(
        origin["sink"] == "setData"
        for origin in entries["Replacement source:"]["origins"]
    )
    assert any(
        origin["sink"] == "ProviderPreset"
        for origin in entries["Anthropic (Claude)"]["origins"]
    )
    assert any(
        origin["sink"] == "SourcePartsPendingPresentation"
        for origin in entries["No unapplied source-part changes."]["origins"]
    )
    assert any(
        origin["sink"] == "_set_archive_warmup_overlay"
        for origin in entries["Preparing Archive Browser View"]["origins"]
    )
    assert any(
        origin["sink"] == "setItemData"
        for origin in entries[
            "Disabled - WIP. Placement swap/package flow is paused."
        ]["origins"]
    )
    assert any(
        origin["sink"] == "translate_active_ui_text"
        for origin in entries["No skeleton loaded"]["origins"]
    )
    assert entries["Partial"]["manual"] is True
    assert entries["AES"]["manual"] is True
    assert entries["pending"]["manual"] is True
    assert any(
        origin["sink"] == "QTreeWidgetItem"
        for origin in entries["Average FPS"]["origins"]
    )
    assert any(
        origin["sink"] == "addRow"
        for origin in entries["Active/hover color"]["origins"]
    )
    assert any(
        origin["sink"] == "setItemData"
        for origin in entries[
            "Click anywhere on the body to create a socket at that spot."
        ]["origins"]
    )
    assert any(
        origin["sink"] == "translate_active_ui_text"
        for origin in entries["socket in use"]["origins"]
    )
    assert entries["Updating app colors and preview panes..."]["manual"] is True
    assert validate_catalogs() == (14, len(SOURCE_STRING_CATALOGUE))
