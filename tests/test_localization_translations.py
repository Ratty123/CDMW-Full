import json
import os
from pathlib import Path
import re
import time
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

from cdmw.ui.localization import UiLocalizer, collect_translatable_source_strings
from cdmw.ui.shell.language_controller import LanguageControllerMixin
from cdmw.ui.shell.utility_controller import UtilityControllerMixin


class _LanguageWindow(UtilityControllerMixin, QMainWindow):
    def __init__(self) -> None:
        QMainWindow.__init__(self)
        self.worker_thread = None
        self.utility_worker = None
        self._utility_completion_handler = None
        self._utility_error_handler = None
        self._utility_updates_archive_progress = False

    def _background_task_active(self) -> bool:
        return self.worker_thread is not None

    def set_status_message(self, *_args: object, **_kwargs: object) -> None:
        pass

    def append_log(self, *_args: object, **_kwargs: object) -> None:
        pass

    def set_busy(self, *_args: object, **_kwargs: object) -> None:
        pass

    def _handle_utility_log_message(self, _message: str) -> None:
        pass

    def _handle_utility_progress_changed(self, _current: int, _total: int, _detail: str) -> None:
        pass

    def _handle_worker_error(self, message: str) -> None:
        if self._utility_error_handler is not None:
            self._utility_error_handler(message)

    def _cleanup_worker_refs(self) -> None:
        self.worker_thread = None
        self.utility_worker = None
        self._utility_completion_handler = None
        self._utility_error_handler = None


def _wait_for(app: QApplication, predicate: object, timeout: float = 5.0) -> bool:
    deadline = perf_counter() + timeout
    while perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def _source(*paths: str) -> str:
    return "\n".join(Path(path).read_text(encoding="utf-8") for path in paths)


def _about_documentation_source() -> str:
    return _source(
        "cdmw/ui/shell/about_controller.py",
        "cdmw/ui/shell/about_documentation.py",
        "cdmw/ui/shell/about_documentation_en.py",
        "cdmw/ui/shell/about_documentation_es.py",
        "cdmw/ui/shell/about_documentation_de.py",
    )


def test_packaged_language_catalogue_contains_known_key_without_source_tree() -> None:
    with patch.object(Path, "rglob", side_effect=AssertionError("runtime source scan")):
        translations = collect_translatable_source_strings((Path("missing-packaged-source"),))

    assert "Apply Suggested Overrides..." in translations
    assert translations["Apply Suggested Overrides..."] == ""


def test_initial_english_language_apply_skips_widget_tree_walk() -> None:
    class _Localizer:
        language_code = "en"
        apply_calls: list[object] = []

        @staticmethod
        def available_languages() -> tuple[tuple[str, str], ...]:
            return (("en", "English"), ("es", "Spanish"))

        def apply(self, root: object) -> None:
            self.apply_calls.append(root)

        @staticmethod
        def translate(value: str) -> str:
            return value

    localizer = _Localizer()
    window = SimpleNamespace(
        settings_tab=SimpleNamespace(set_language_options=lambda *_args, **_kwargs: None),
        texture_editor_tab=None,
        ui_localizer=localizer,
        _update_ncnn_preset_hint=lambda: None,
        _schedule_column_autofit=lambda: None,
    )

    LanguageControllerMixin._apply_ui_language(window)  # type: ignore[arg-type]
    assert localizer.apply_calls == []

    localizer.language_code = "es"
    LanguageControllerMixin._apply_ui_language(window)  # type: ignore[arg-type]
    localizer.language_code = "en"
    LanguageControllerMixin._apply_ui_language(window)  # type: ignore[arg-type]

    assert localizer.apply_calls == [window, window]


def test_language_export_handler_stays_fast_and_includes_live_widget_strings(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = _LanguageWindow()
    QLabel("Live instantiated widget string", window)
    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code="es")
    localizer.translations["Live instantiated widget string"] = "Cadena de widget activa"
    window.ui_localizer = localizer  # type: ignore[attr-defined]
    window.settings_file_path = tmp_path / "settings.ini"  # type: ignore[attr-defined]
    output_path = tmp_path / "es_language.json"

    with (
        patch.object(Path, "rglob", side_effect=AssertionError("runtime source scan")),
        patch(
            "cdmw.ui.shell.language_controller.QFileDialog.getSaveFileName",
            return_value=(str(output_path), "JSON Files (*.json)"),
        ),
        patch("cdmw.ui.shell.language_controller.QMessageBox.warning") as warning,
        patch("cdmw.ui.shell.language_controller.QMessageBox.information") as information,
    ):
        started = perf_counter()
        LanguageControllerMixin._export_language_file(window)  # type: ignore[arg-type]
        elapsed = perf_counter() - started
        assert _wait_for(
            app,
            lambda: output_path.exists() and window.worker_thread is None and information.called,
        )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert elapsed < 0.05
    assert payload["language_code"] == "es"
    assert payload["translations"]["Apply Suggested Overrides..."]
    assert payload["translations"]["Live instantiated widget string"] == "Cadena de widget activa"
    warning.assert_not_called()
    assert window.worker_thread is None
    window.deleteLater()
    app.processEvents()


def test_reviewed_gui_translations_are_available_for_spanish_and_german() -> None:
    spanish = UiLocalizer(language_dir=Path("__unused__"), language_code="es")
    german = UiLocalizer(language_dir=Path("__unused__"), language_code="de")

    assert spanish.translate("Apply Suggested Overrides...") == "Aplicar anulaciones sugeridas..."
    assert german.translate("Apply Suggested Overrides...") == "Vorgeschlagene Overrides anwenden..."
    assert spanish.translate("Advanced: Apply Suggested Overrides...") == "Avanzado: aplicar anulaciones sugeridas..."
    assert german.translate("Advanced: Apply Suggested Overrides...") == "Erweitert: Vorgeschlagene Overrides anwenden..."
    assert spanish.translate("Texture source probe") == "Sonda de origen de textura"
    assert german.translate("Texture source probe") == "Texturquellen-Probe"
    assert spanish.translate("Exact Item Name") == "Nombre exacto de item"
    assert german.translate("Exact Item Name") == "Exakter Item-Name"
    assert spanish.translate("Name Match") == "Coincidencia de nombre"
    assert german.translate("Name Match") == "Namensabgleich"
    assert spanish.translate("Related Name Hint") == "Pista de nombre relacionado"
    assert german.translate("Related Name Hint") == "Hinweis auf verwandten Namen"
    assert spanish.translate("Window") == "Ventana"
    assert german.translate("Window") == "Fenster"
    assert spanish.translate("Detach Current Tool") == "Separar herramienta actual"
    assert german.translate("Detach Current Tool") == "Aktuelles Werkzeug abtrennen"
    assert spanish.translate("Reattach Current Tool") == "Volver a acoplar herramienta actual"
    assert german.translate("Reattach Current Tool") == "Aktuelles Werkzeug wieder andocken"
    assert spanish.translate("Reattach All Tools") == "Volver a acoplar todas las herramientas"
    assert german.translate("Reattach All Tools") == "Alle Werkzeuge wieder andocken"
    assert spanish.translate("Reattach Tool") == "Volver a acoplar herramienta"
    assert german.translate("Reattach Tool") == "Werkzeug wieder andocken"
    assert spanish.translate("Show Text Search") == "Mostrar busqueda de texto"
    assert german.translate("Show Text Search") == "Textsuche anzeigen"
    assert spanish.translate("Texture Research") == "Investigacion de texturas"
    assert german.translate("Texture Research") == "Textur-Recherche"
    assert spanish.translate("Show Texture Research") == "Mostrar investigacion de texturas"
    assert german.translate("Show Texture Research") == "Textur-Recherche anzeigen"
    assert spanish.translate("Global font size (8-15 px)") == "Tamano de fuente global (8-15 px)"
    assert german.translate("Lists / columns font size (8-15 px)") == "Schriftgroesse fuer Listen / Spalten (8-15 px)"
    assert spanish.translate("Existing PNG folder") == "Carpeta PNG existente"
    assert german.translate("Rebuilt DDS folder") == "Neu erstellter DDS-Ordner"
    assert spanish.translate("Shortcuts") == "Atajos"
    assert german.translate("Shortcuts") == "Tastenkurzel"
    assert spanish.translate("Composite Preview...") == "Vista previa compuesta..."
    assert german.translate("Composite Preview...") == "Kompositvorschau..."
    assert spanish.translate("Appearance Armor Swap...") == "Intercambio de armadura de apariencia..."
    assert german.translate("Appearance Armor Swap...") == "Appearance-Ruestungs-Swap..."
    assert spanish.translate("Material Authority Manual") == "Autoridad de material manual"
    assert german.translate("Material Authority Manual") == "Materialautoritaet manuell"
    assert spanish.translate("Runtime XML preserve") == "Preservar XML runtime"
    assert german.translate("Runtime XML preserve") == "Runtime XML erhalten"
    assert spanish.translate("True Source Authority") == "Autoridad de origen real"
    assert german.translate("True Source Authority") == "Echte Quellenautoritaet"
    assert spanish.translate("Review Compare") == "Revisar comparacion"
    assert german.translate("Review Compare") == "Vergleich pruefen"
    assert spanish.translate("Recolor Variants") == "Variantes de recolor"
    assert german.translate("Recolor Variants") == "Umfaerbungsvarianten"
    assert spanish.translate("Stowed / on body") == "Guardado / en el cuerpo"
    assert german.translate("Stowed / on body") == "Verstaut / am Koerper"
    assert spanish.translate("Held / in hand") == "Sostenido / en mano"
    assert german.translate("Held / in hand") == "Gehalten / in der Hand"
    assert spanish.translate("Retrofit/Repackage Mods") == "Adaptar/reempaquetar mods"
    assert german.translate("Retrofit/Repackage Mods") == "Mods anpassen/neu paketieren"
    assert spanish.translate("Mod Manager") == "Gestor de mods"
    assert german.translate("Mod Manager") == "Mod-Manager"
    assert spanish.translate("files/ wrapper") == "Contenedor files/"
    assert german.translate("files/ wrapper") == "files/-Wrapper"
    assert spanish.translate("Field-JSON v3.1 assets") == "Recursos Field-JSON v3.1"
    assert german.translate("Field-JSON v3.1 assets") == "Field-JSON-v3.1-Assets"
    assert spanish.translate("Retrofit/Repackage plan for selected packages").startswith("Plan de adaptacion")
    assert german.translate("Retrofit/Repackage plan for selected packages").startswith("Anpassungs")
    assert spanish.translate("Scan a source folder to find packaged mods.") == (
        "Escanea una carpeta de origen para encontrar mods empaquetados."
    )
    assert german.translate("Scan a source folder to find packaged mods.") == (
        "Quellordner scannen, um paketierte Mods zu finden."
    )
    assert spanish.translate("Apply Suggested Overrides...") == "Aplicar anulaciones sugeridas..."
    assert german.translate("Apply Suggested Overrides...") == "Vorgeschlagene Overrides anwenden..."
    assert spanish.translate(
        "Paint tool active. Brush presets, image stamps, patterns, and symmetry are available here. Alt+click samples a color into the paint swatch."
    ).startswith("Herramienta de pintura activa.")


def test_builtin_fallback_translates_short_unlisted_gui_labels() -> None:
    spanish = UiLocalizer(language_dir=Path("__unused__"), language_code="es")
    german = UiLocalizer(language_dir=Path("__unused__"), language_code="de")

    assert spanish.translate("Custom") == "Personalizado"
    assert german.translate("Custom") == "Benutzerdefiniert"
    assert spanish.translate("Expected NCNN model contents") == "Contenido esperado del modelo NCNN"
    assert german.translate("Expected NCNN model contents") == "Erwarteter NCNN-Modellinhalt"
    assert spanish.translate("Swap With In-Game Mesh...") == "Intercambiar con malla del juego..."
    assert german.translate("Swap With In-Game Mesh...") == "Mit Ingame-Mesh tauschen..."


def test_builtin_fallback_leaves_code_like_text_alone() -> None:
    spanish = UiLocalizer(language_dir=Path("__unused__"), language_code="es")
    german = UiLocalizer(language_dir=Path("__unused__"), language_code="de")

    code_like = "{value}\\path"
    assert spanish.translate(code_like) == code_like
    assert german.translate(code_like) == code_like


def test_quick_start_and_documentation_cover_mesh_import_and_swap() -> None:
    help_dialogs_source = Path("cdmw/ui/shell/help_dialogs.py").read_text(encoding="utf-8")
    main_window_source = _source("cdmw/ui/shell/app_window.py") + "\n" + _about_documentation_source()

    assert "Mesh Quick Guide" in help_dialogs_source
    assert "Guia rapida de mallas" in help_dialogs_source
    assert "Schnellguide fuer Meshes" in help_dialogs_source
    assert "Import DDS Preview" in help_dialogs_source
    assert "Vista previa de importar DDS" in help_dialogs_source
    assert "DDS-Importvorschau" in help_dialogs_source
    assert "Swap With In-Game Mesh" in main_window_source
    assert "Intercambiar con malla del juego" in main_window_source
    assert "Mit Ingame-Mesh tauschen" in main_window_source


def test_archive_browser_documentation_covers_current_functionality_in_supported_languages() -> None:
    main_window_source = _about_documentation_source()

    assert "active mod/original/shadowed duplicate status" in main_window_source
    assert "static geometry thumbnail so browsing candidates" in main_window_source
    assert "Item Finder" in main_window_source

    assert "mod activo" in main_window_source
    assert "miniatura estatica de geometria" in main_window_source
    assert "Intercambio masivo de colocacion" not in main_window_source

    assert "Aktiver Mod" in main_window_source
    assert "statische Geometrie-Miniatur" in main_window_source
    assert "HKX-Platzierung" in main_window_source


def test_profile_window_and_documentation_cover_current_settings_scope() -> None:
    main_window_source = "\n".join(
        (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/shell/profile_controller.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/shell/startup_restore.py").read_text(encoding="utf-8"),
            _about_documentation_source(),
        )
    )

    assert "_collect_profile_settings_snapshot" in main_window_source
    assert '"profile_format": 4' in main_window_source
    assert '"settings_key_count"' in main_window_source
    assert "_restore_profile_settings_snapshot" in main_window_source
    assert "self._load_settings()" in main_window_source
    assert (
        "appearance, startup, preview, window/layout, Texture Replacer, and Texture Editor preferences"
        in main_window_source
    )
    assert "one app-wide snapshot, not a separate profile per tab" in main_window_source
    assert "Profiles do not save open archives, active documents, or per-tab project sessions." in main_window_source
    assert "no perfiles separados por pestana" in main_window_source
    assert "keine getrennten Profile pro Tab" in main_window_source
    assert "Profile &gt; Export Profile" in main_window_source
    assert "Window &amp; Layout" in main_window_source
    assert "window/detached/&lt;tool&gt;/geometry" in main_window_source


def test_mod_packaging_documentation_covers_supported_manager_formats() -> None:
    main_window_source = _about_documentation_source()
    retrofit_source = Path("cdmw/ui/tools/mod_package_retrofit_widget.py").read_text(encoding="utf-8")

    assert "DMM, CDUMM, JMM JSON, Crimson Sharp / Crimson Browser, and Field-JSON v3.1" in main_window_source
    assert "CDUMM uses <code>manifest.json</code>, <code>modinfo.json</code>, <code>.no_encrypt</code>, and a <code>files/</code> wrapper" in main_window_source
    assert "DMM texture folders use <code>modinfo.json</code>" in main_window_source
    assert "DMM mesh folders keep <code>manifest.json</code> plus <code>modinfo.json</code>" in main_window_source

    assert "def _apply_widget_localization(self, widget: QWidget) -> None:" in retrofit_source
    assert "self._apply_widget_localization(self.parent)" in retrofit_source
    assert "self._apply_widget_localization(manager)" in retrofit_source
    assert "self._apply_widget_localization(structure)" in retrofit_source


def test_documentation_and_readme_cover_current_mesh_and_dds_workflows() -> None:
    main_window_source = _about_documentation_source()
    readme_source = Path("README.md").read_text(encoding="utf-8")

    assert "OBJ/DAE/glTF/GLB preview" in main_window_source
    assert "Appearance Armor Swap</b> loose packages" not in main_window_source
    assert "Runtime XML preserve</b> keeps target/corpus PAC XML structure" in main_window_source
    assert "True Source Authority</b> uses original PAC/XML as runtime ABI" in main_window_source
    assert "Material Authority Manual</b> starts from Runtime XML preserve" in main_window_source
    assert "Stowed / on body</b> versus <b>Held / in hand" in main_window_source
    assert "Intercambio de armadura de apariencia" not in main_window_source
    assert "Autoridad de origen real" in main_window_source
    assert "Appearance-Ruestungs-Swap" not in main_window_source
    assert "Echte Quellenautoritaet" in main_window_source

    assert "OBJ/DAE/glTF/GLB import preview" in readme_source
    assert "bundled `cd-texture-dx.exe` native" in readme_source
    assert "DDS preview, staging, and rebuild use the bundled `cd-texture-dx.exe`" in readme_source


def test_supported_documentation_languages_cover_all_topic_ids() -> None:
    english_block = Path("cdmw/ui/shell/about_documentation_en.py").read_text(encoding="utf-8")
    spanish_block = Path("cdmw/ui/shell/about_documentation_es.py").read_text(encoding="utf-8")
    german_block = Path("cdmw/ui/shell/about_documentation_de.py").read_text(encoding="utf-8")

    english_ids = set(re.findall(r'"id"\s*:\s*"([^"]+)"', english_block))
    assert set(re.findall(r'"id"\s*:\s*"([^"]+)"', spanish_block)) == english_ids
    assert set(re.findall(r'"id"\s*:\s*"([^"]+)"', german_block)) == english_ids

    for required in ("first_run_checklist", "texture_workflow_guides", "mod_packaging", "safety", "faq"):
        assert required in english_ids


def test_help_about_surfaces_have_localized_html_and_documentation_route() -> None:
    main_window_source = _about_documentation_source()
    help_dialogs_source = Path("cdmw/ui/shell/help_dialogs.py").read_text(encoding="utf-8")

    assert "def _build_about_overview_html_es" in main_window_source
    assert "def _build_about_overview_html_de" in main_window_source
    assert 'overview_browser.setProperty("_i18n_html_es"' in main_window_source
    assert 'overview_browser.setProperty("_i18n_html_de"' in main_window_source
    assert 'hasattr(parent_window, "show_documentation_dialog")' in help_dialogs_source
    assert 'parent_window.show_documentation_dialog(topic_id="overview")' in help_dialogs_source
    assert 'parent_window.show_about_dialog(topic_id="overview")' not in help_dialogs_source
