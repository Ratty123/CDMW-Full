from pathlib import Path

from cdmw.ui.localization import UiLocalizer


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
    assert spanish.translate("Detach Current Tab") == "Separar pestana actual"
    assert german.translate("Detach Current Tab") == "Aktuellen Tab abtrennen"
    assert spanish.translate("Show Text Search") == "Mostrar busqueda de texto"
    assert german.translate("Show Text Search") == "Textsuche anzeigen"
    assert spanish.translate("Global font size (8-15 px)") == "Tamano de fuente global (8-15 px)"
    assert german.translate("Lists / columns font size (8-15 px)") == "Schriftgroesse fuer Listen / Spalten (8-15 px)"
    assert spanish.translate("Existing PNG folder") == "Carpeta PNG existente"
    assert german.translate("Rebuilt DDS folder") == "Neu erstellter DDS-Ordner"
    assert spanish.translate("Shortcuts") == "Atajos"
    assert german.translate("Shortcuts") == "Tastenkurzel"
    assert spanish.translate("Dashboard") == "Panel"
    assert german.translate("Dashboard") == "Dashboard"
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
    assert spanish.translate("Open DirectXTex / texconv Page") == "Abrir pagina de DirectXTex / texconv"
    assert german.translate("Open DirectXTex / texconv Page") == "DirectXTex-/texconv-Seite oeffnen"
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
    widgets_source = Path("cdmw/ui/widgets.py").read_text(encoding="utf-8")
    main_window_source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

    assert "Mesh Quick Guide" in widgets_source
    assert "Guia rapida de mallas" in widgets_source
    assert "Schnellguide fuer Meshes" in widgets_source
    assert "Import DDS Preview" in widgets_source
    assert "Vista previa de importar DDS" in widgets_source
    assert "DDS-Importvorschau" in widgets_source
    assert "Swap With In-Game Mesh" in main_window_source
    assert "Intercambiar con malla del juego" in main_window_source
    assert "Mit Ingame-Mesh tauschen" in main_window_source


def test_archive_browser_documentation_covers_current_functionality_in_supported_languages() -> None:
    main_window_source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

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
    main_window_source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

    assert "_collect_profile_settings_snapshot" in main_window_source
    assert '"profile_format": 3' in main_window_source
    assert '"settings_key_count"' in main_window_source
    assert "_restore_profile_settings_snapshot" in main_window_source
    assert "self._load_settings()" in main_window_source
    assert (
        "appearance, startup, preview, window/layout, Texture Replacer, and Texture Editor preferences"
        in main_window_source
    )
    assert "Profile &gt; Export Profile" in main_window_source
    assert "Window &amp; Layout" in main_window_source
    assert "window/detached/&lt;tool&gt;/geometry" in main_window_source


def test_documentation_and_readme_cover_current_mesh_and_dds_workflows() -> None:
    main_window_source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
    readme_source = Path("README.md").read_text(encoding="utf-8")

    assert "Dashboard</b>: compact workspace health" in main_window_source
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
    assert "DirectXTex/native helpers first" in readme_source
    assert "texconv.exe` remains an optional legacy fallback" in readme_source
    assert "Open DirectXTex / texconv Page" in readme_source
