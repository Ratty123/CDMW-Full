"""Shell help/about dialogs."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QBrush, QDesktopServices, QFont, QPalette, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

_QUICK_START_HTML_ES = """
<h3>Que cubre esta app</h3>
<p><b>Crimson Desert Mod Workbench</b> es una herramienta de archivos y archivos sueltos para Crimson Desert. Cubre extraccion, investigacion, edicion, reconstruccion DDS, escalado opcional, comparacion y exportacion suelta lista para mods.</p>
<ul>
  <li><b>Explorador de archivos</b>: escanear .pamt/.paz, previsualizar recursos compatibles, filtrar, clasificar y extraer a carpetas sueltas.</li>
  <li><b>Acciones de malla</b>: exportar OBJ/FBX, probar <b>Importar vista de malla</b>, probar texturas con <b>Vista previa de importar DDS</b>, ejecutar <b>Importar malla</b>, alinear reemplazos estaticos y usar <b>Intercambiar con malla del juego</b> cuando otra malla del archivo deba ser el origen.</li>
  <li><b>Flujo de texturas</b>: escanear DDS sueltos, convertir DDS a PNG si hace falta, escalar opcionalmente, reconstruir DDS, comparar resultados y exportar salida mod-ready.</li>
  <li><b>Editor de texturas</b>: abrir imagenes para edicion visible por capas y enviar la salida plana al flujo de reconstruccion.</li>
  <li><b>Asistente de reemplazo</b>: tomar PNG/DDS editados, asociarlos con el DDS original del juego, reconstruir la salida corregida y preparar carpetas mod-ready.</li>
  <li><b>Investigacion</b>: inspeccionar familias de texturas, clasificaciones desconocidas, referencias, analisis DDS, informes y notas locales.</li>
  <li><b>Busqueda de texto</b>: buscar archivos de texto de archivo o sueltos, como .xml, .json, .cfg y .lua.</li>
  <li><b>Configuracion</b>: guardar tema, densidad, cache, estado de layout, confirmaciones y preferencias de inicio.</li>
</ul>
<h3>Configuracion inicial recomendada</h3>
<ol>
  <li>Crea una carpeta dedicada para la app y coloca alli el <b>.exe</b> portable para mantener juntos configuracion, cache, herramientas y workspace.</li>
  <li>Abre <b>Configuracion &gt; Ubicaciones de archivo</b> y define la ruta del juego/paquete de Crimson Desert. Usa deteccion automatica si aplica.</li>
  <li>Abre <b>Configuracion &gt; Setup</b> y haz clic en <b>Inicializar espacio</b>.</li>
  <li>Usa las herramientas DirectXTex/native incluidas para DDS; <b>texconv.exe</b> queda como fallback legacy opcional.</li>
  <li>Define <b>Raiz DDS original</b>, <b>Raiz PNG</b> y <b>Raiz de salida</b>. Activa staging DDS solo si quieres una carpeta PNG previa al escalado.</li>
  <li>Elige un backend de escalado: desactivado, <b>Real-ESRGAN NCNN</b> directo o <b>chaiNNer</b>.</li>
  <li>Empieza con una politica de texturas segura y deja las reglas automaticas activadas para preservar mapas tecnicos riesgosos.</li>
  <li>Revisa perfiles, reglas y coincidencias antes de ejecutar un lote.</li>
  <li>Usa <b>Vista de politica</b> antes de <b>Iniciar</b> para revisar la accion planeada por textura.</li>
  <li>Ejecuta un subconjunto pequeno primero y revisa el resultado en <b>Comparar</b>.</li>
  <li>Si ya editaste una textura fuera de la app, usa <b>Asistente de reemplazo</b>.</li>
  <li>Para mallas, empieza en <b>Explorador de archivos</b>: selecciona una malla .pam/.pamlod/.pac, usa <b>Importar vista de malla</b> para probar sin escribir y usa <b>Importar malla</b> solo cuando la alineacion y las texturas se vean correctas.</li>
</ol>
<h3>Guia rapida de mallas</h3>
<ul>
  <li><b>Exportar OBJ/FBX</b>: util para inspeccionar o editar externamente. OBJ es la base de round-trip cuando la app puede escribir los metadatos necesarios.</li>
  <li><b>Importar vista de malla</b>: abre la revision y <b>Alineacion de reemplazo de malla</b> sin escribir salida.</li>
  <li><b>Vista previa de importar DDS</b>: prueba una textura DDS en el modelo seleccionado sin escribir salida.</li>
  <li><b>Importar malla</b>: despues de revisar, permite exportar salida suelta mod-ready o parchear archivos donde sea compatible.</li>
  <li><b>Intercambiar con malla del juego</b>: primero marca la malla seleccionada como destino, luego selecciona otra malla del archivo como origen. La app abre la misma alineacion de reemplazo y puede incluir texturas, sidecars, esqueletos o animaciones relacionadas cuando corresponda.</li>
  <li><b>GLB/glTF/DAE</b>: se tratan como fuentes estaticas. No convierten skins, huesos, animaciones ni grafos PBR complejos a datos nativos del juego.</li>
</ul>
<h3>Areas principales</h3>
<ul>
  <li><b>Configuracion / Setup</b>: creacion de workspace, herramientas externas, enlaces de ayuda e importadores.</li>
  <li><b>Configuracion / Rutas</b>: origen, staging, PNG, salida y raices de exportacion mod-ready.</li>
  <li><b>Salida DDS</b>: formato, tamano, mips y staging globales.</li>
  <li><b>Perfiles, reglas y coincidencias</b>: planificacion reutilizable por archivo.</li>
  <li><b>Escalado</b>: backend, politica, controles NCNN y notas.</li>
  <li><b>Comparar</b>: revision lado a lado antes de lotes grandes.</li>
</ul>
<h3>Nota sobre cache de sidecars</h3>
<p>Crear el cache global de sidecars puede tardar mucho en archivos grandes. Mejora referencias inversas DDS, conexiones de texturas de modelos y busqueda de sidecars/materiales. Si lo activas, deja que termine; se configura en <b>Configuracion &gt; Rendimiento del explorador de archivos</b>.</p>
<h3>Advertencia sobre texturas tecnicas</h3>
<p>Las texturas visibles de color no son iguales que mapas tecnicos. Altura, desplazamiento, normales, mascaras, vectores y otros DDS sensibles son mas riesgosos al pasar por PNG.</p>
<ul>
  <li>Empieza con un preajuste seguro.</li>
  <li>Manten las reglas automaticas activadas.</li>
  <li>Revisa perfiles y rutas del planificador antes de forzar mapas tecnicos por la ruta PNG visible.</li>
</ul>
<h3>Documentacion</h3>
<p>El menu <b>Documentacion</b> abre un navegador de documentacion con busqueda y temas de flujo, perfiles y rutas del planificador.</p>
"""


_QUICK_START_HTML_DE = """
<h3>Was diese App abdeckt</h3>
<p><b>Crimson Desert Mod Workbench</b> ist ein Archiv- und Loose-File-Werkzeug fuer Crimson Desert. Es deckt Extraktion, Research, Bearbeitung, DDS-Neuaufbau, optionales Upscaling, Vergleich und mod-fertigen Loose-Export ab.</p>
<ul>
  <li><b>Archiv-Browser</b>: .pamt/.paz scannen, unterstuetzte Assets anzeigen, filtern, klassifizieren und in lose Ordner extrahieren.</li>
  <li><b>Mesh-Aktionen</b>: OBJ/FBX exportieren, <b>Mesh-Importvorschau</b> testen, Texturen mit <b>DDS-Importvorschau</b> pruefen, <b>Mesh importieren</b> ausfuehren, statische Ersetzungen ausrichten und <b>Mit Ingame-Mesh tauschen</b> nutzen, wenn eine andere Archiv-Mesh als Quelle dienen soll.</li>
  <li><b>Textur-Workflow</b>: lose DDS scannen, DDS bei Bedarf zu PNG konvertieren, optional hochskalieren, DDS neu erstellen, Ergebnisse vergleichen und mod-fertige Ausgabe exportieren.</li>
  <li><b>Textur-Editor</b>: Bilder fuer sichtbare Ebenenbearbeitung oeffnen und die flache Ausgabe zurueck in den Neuaufbau senden.</li>
  <li><b>Ersetzungsassistent</b>: bearbeitete PNG/DDS mit dem Original-DDS abgleichen, korrigierte Ausgabe neu erstellen und mod-fertige Ordner vorbereiten.</li>
  <li><b>Recherche</b>: Texturfamilien, unbekannte Klassifizierungen, Referenzen, DDS-Analyse, Berichte und lokale Notizen pruefen.</li>
  <li><b>Textsuche</b>: Archiv- oder lose Textdateien wie .xml, .json, .cfg und .lua durchsuchen.</li>
  <li><b>Einstellungen</b>: Theme, Dichte, Cache, Layoutstatus, Bestaetigungen und Startpraeferenzen speichern.</li>
</ul>
<h3>Empfohlene Starteinrichtung</h3>
<ol>
  <li>Erstelle einen eigenen Ordner fuer die App und lege die portable <b>.exe</b> dort ab, damit Konfiguration, Cache, Tools und Workspace zusammen bleiben.</li>
  <li>Oeffne <b>Einstellungen &gt; Archiv-Orte</b> und setze den Crimson-Desert-Spiel-/Paketpfad. Nutze Auto-Erkennung, wenn moeglich.</li>
  <li>Oeffne <b>Einstellungen &gt; Einrichtung</b> und klicke auf <b>Arbeitsbereich einrichten</b>.</li>
  <li>Nutze die gebuendelten DirectXTex/native-DDS-Tools; <b>texconv.exe</b> bleibt nur optionaler Legacy-Fallback.</li>
  <li>Setze <b>Original-DDS-Stamm</b>, <b>PNG-Stamm</b> und <b>Ausgabe-Stamm</b>. Aktiviere DDS-Staging nur fuer einen separaten PNG-Staging-Ordner.</li>
  <li>Waehle ein Upscaling-Backend: deaktiviert, direktes <b>Real-ESRGAN NCNN</b> oder <b>chaiNNer</b>.</li>
  <li>Starte mit einer sicheren Textur-Richtlinie und lasse automatische Regeln aktiv, damit riskante technische Maps erhalten bleiben.</li>
  <li>Pruefe Profile, Regeln und Treffer, bevor du einen Stapellauf startest.</li>
  <li>Nutze <b>Richtlinienvorschau</b> vor <b>Start</b>, um die geplante Aktion pro Textur zu pruefen.</li>
  <li>Fuehre zuerst eine kleine Auswahl aus und pruefe das Ergebnis in <b>Vergleichen</b>.</li>
  <li>Wenn du eine Textur bereits extern bearbeitet hast, nutze den <b>Ersetzungsassistent</b>.</li>
  <li>Fuer Meshes im <b>Archiv-Browser</b> starten: .pam/.pamlod/.pac waehlen, mit <b>Mesh-Importvorschau</b> ohne Schreiben testen und <b>Mesh importieren</b> erst nutzen, wenn Ausrichtung und Texturen korrekt aussehen.</li>
</ol>
<h3>Schnellguide fuer Meshes</h3>
<ul>
  <li><b>OBJ/FBX exportieren</b>: nuetzlich fuer Inspektion oder externe Bearbeitung. OBJ ist die Roundtrip-Basis, wenn die App die noetigen Metadaten schreiben kann.</li>
  <li><b>Mesh-Importvorschau</b>: oeffnet Review und <b>Mesh-Ersetzungsausrichtung</b>, ohne Ausgabe zu schreiben.</li>
  <li><b>DDS-Importvorschau</b>: testet eine DDS-Textur am gewaehlten Modell, ohne Ausgabe zu schreiben.</li>
  <li><b>Mesh importieren</b>: nach der Pruefung mod-fertige Loose-Ausgabe oder Patch schreiben, wo kompatibel.</li>
  <li><b>Mit Ingame-Mesh tauschen</b>: zuerst die ausgewaehlte Mesh als Ziel markieren, dann eine andere Archiv-Mesh als Quelle waehlen. Die App oeffnet dieselbe Ersetzungsausrichtung und kann passende Texturen, Sidecars, Skelette oder Animationen einschliessen.</li>
  <li><b>GLB/glTF/DAE</b>: werden als statische Quellen behandelt. Skins, Knochen, Animationen und komplexe PBR-Graphen werden nicht in native Spieldaten konvertiert.</li>
</ul>
<h3>Hauptbereiche</h3>
<ul>
  <li><b>Einstellungen / Einrichtung</b>: Workspace-Erstellung, externe Tools, Hilfelinks und Importhelfer.</li>
  <li><b>Einstellungen / Pfade</b>: Quelle, Staging, PNG, Ausgabe und mod-fertige Exportstaemme.</li>
  <li><b>DDS-Ausgabe</b>: globale Format-, Groessen-, Mip- und Staging-Regeln.</li>
  <li><b>Profile, Regeln und Treffer</b>: wiederverwendbare Planung pro Datei.</li>
  <li><b>Upscaling</b>: Backend, Richtlinie, NCNN-Steuerung und Notizen.</li>
  <li><b>Vergleichen</b>: Seit-an-Seit-Pruefung vor groesseren Laeufen.</li>
</ul>
<h3>Hinweis zum Sidecar-Cache</h3>
<p>Der globale Sidecar-Cache kann bei grossen Archiven lange dauern. Er verbessert DDS-Rueckreferenzen, Modell-Textur-Verbindungen und Material-Sidecar-Suche. Wenn du ihn aktivierst, lass den ersten Lauf fertig werden; die Optionen findest du unter <b>Einstellungen &gt; Archiv-Browser-Leistung</b>.</p>
<h3>Warnung zu technischen Texturen</h3>
<p>Sichtbare Farbtexturen sind nicht dasselbe wie technische Maps. Hoehe, Displacement, Normalen, Masken, Vektoren und andere empfindliche DDS-Dateien sind riskanter, wenn sie ueber PNG laufen.</p>
<ul>
  <li>Starte mit einem sicheren Preset.</li>
  <li>Lasse automatische Regeln aktiv.</li>
  <li>Pruefe Planerprofile und Planerpfade, bevor technische Maps in den sichtbaren PNG-Pfad gezwungen werden.</li>
</ul>
<h3>Dokumentation</h3>
<p>Das Menue <b>Dokumentation</b> oeffnet einen durchsuchbaren Dokumentationsbrowser mit Workflow-Themen, Profilen und Planerpfaden.</p>
"""


class QuickStartDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Startup Setup")
        self.setMinimumSize(560, 460)
        self.resize(720, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title_label = QLabel("Startup setup guide")
        title_font = QFont(self.font())
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        intro_label = QLabel(
            "Start by putting the portable EXE in its own app folder, setting the Crimson Desert game/package path in Settings > Archive Locations, then clicking Init Workspace. DDS preview and rebuild use DirectXTex/native helpers first; texconv is optional legacy fallback."
        )
        intro_label.setObjectName("HintLabel")
        intro_label.setWordWrap(True)
        layout.addWidget(intro_label)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setReadOnly(True)
        quick_start_html = (
            """
            <h3>What This App Covers</h3>
            <p><b>Crimson Desert Mod Workbench</b> is a read-only archive and loose-file workflow tool for Crimson Desert. It is built around extraction, research, editing, DDS rebuild, optional upscaling, comparison, and mod-ready loose export.</p>
            <ul>
              <li><b>Dashboard</b>: launch common tasks, check workspace paths/tool health, review recent work, and reopen the last result.</li>
              <li><b>Archive Browser</b>: scan <b>.pamt/.paz</b>, preview supported assets, filter, classify, and extract to loose folders.</li>
              <li><b>Mesh Actions</b>: export OBJ/FBX, test <b>Import Mesh Preview</b>, preview texture overrides with <b>Import DDS Preview</b>, run <b>Import Mesh</b>, align static replacements, and use <b>Swap With In-Game Mesh</b> when another loaded archive mesh should become the source.</li>
              <li><b>Texture Workflow</b>: scan loose DDS files, convert DDS to PNG when needed, optionally upscale, rebuild DDS, compare results, and export loose mod output.</li>
              <li><b>Texture Editor</b>: open images directly for layered visible-texture editing and send flattened output back into the rebuild flow.</li>
              <li><b>Texture Replacer</b>: take edited PNG/DDS files, match them to the original game DDS, rebuild corrected output, and prepare mod-ready folders.</li>
              <li><b>Model Library</b>: scan local/importable models, use mirror catalogue metadata, preview models, and route imports to archive workflows.</li>
              <li><b>Icon Creator</b>: manage icon source images and generate compatible item-icon packages from archive targets.</li>
              <li><b>Research</b>: inspect grouped texture families, unknown classifications, references, DDS analysis, reports, and local notes.</li>
              <li><b>Text Search</b>: search archive or loose text-like files such as <b>.xml</b>, <b>.json</b>, <b>.cfg</b>, and <b>.lua</b>.</li>
              <li><b>Settings</b>: store theme, density, cache behavior, remembered layout state, confirmations, and startup preferences beside the EXE.</li>
            </ul>
            <h3>Recommended Startup Setup</h3>
            <ol>
              <li>Create or choose a dedicated folder for the app, then place the portable <b>.exe</b> there so config, cache, tools, and workspace folders stay together.</li>
              <li>Open <b>Settings &gt; Archive Locations</b> and set the Crimson Desert game/package path. Use <b>Auto-detect</b> if the game is in a common install location.</li>
              <li>Open <b>Settings &gt; Setup</b> and click <b>Init Workspace</b>.</li>
              <li>Use the bundled DirectXTex/native DDS tools. <b>texconv.exe</b> is optional legacy fallback only.</li>
              <li>Confirm <b>Original DDS root</b>, <b>PNG root</b>, and <b>Output root</b>. Enable DDS staging only if you want a separate pre-upscale PNG staging folder.</li>
              <li>Choose an upscaling backend in <b>Upscaling</b>: disabled, direct <b>Real-ESRGAN NCNN</b>, or <b>chaiNNer</b>.</li>
              <li>Keep a safer <b>Texture Policy</b> preset first and leave automatic rules enabled so risky technical DDS files are preserved instead of pushed through the visible PNG path.</li>
              <li>Open <b>Profiles, Rules &amp; Matches</b> and review the starter workflow assignments before running a batch.</li>
              <li>Use <b>Preview Policy</b> before <b>Start</b> if you want to inspect the planned per-texture action.</li>
              <li>Click <b>Scan</b> in the Texture Workflow tab.</li>
              <li>Run a small subset first, then review the output in <b>Compare</b> before trying a larger batch.</li>
              <li>If you already edited a texture outside the app, use <b>Texture Replacer</b> instead of the batch workflow.</li>
              <li>If you want to edit visible textures inside the app, open them in <b>Texture Editor</b> and then send the flattened result back into <b>Texture Replacer</b> or <b>Texture Workflow</b>.</li>
              <li>For mesh work, start in <b>Archive Browser</b>: select a <b>.pam</b>, <b>.pamlod</b>, or <b>.pac</b>, use <b>Import Mesh Preview</b> to test without writing, and use <b>Import Mesh</b> only after alignment and texture choices look correct.</li>
            </ol>
            <h3>Mesh Quick Guide</h3>
            <ul>
              <li><b>Export OBJ/FBX</b>: use this for inspection or external editing. OBJ is the round-trip baseline when the app can write the companion metadata needed for import.</li>
              <li><b>Import Mesh Preview</b>: opens review and <b>Mesh Replacement Alignment</b> without writing archive or loose output.</li>
              <li><b>Import DDS Preview</b>: tests a DDS texture override on the selected model without writing output.</li>
              <li><b>Import Mesh</b>: after review, writes a supported replacement as mod-ready loose output or an archive patch where that workflow is available.</li>
              <li><b>Swap With In-Game Mesh</b>: first mark the selected archive mesh as the target, then choose another loaded archive mesh as the source. The app opens the same replacement alignment flow and can carry related textures, sidecars, skeletons, or animations when appropriate.</li>
              <li><b>GLB/glTF/DAE</b>: treated as static replacement sources. Skins, bones, animations, and complex PBR material graphs are not converted into native game material data.</li>
            </ul>
            <h3>Pick The Right Starting Path</h3>
            <ul>
              <li><b>I want to look inside the game files</b>: open <b>Archive Browser</b>, choose a package root, scan, filter, preview, and extract selected files.</li>
              <li><b>I want to replace a model</b>: use <b>Archive Browser</b> mesh actions, start with <b>Import Mesh Preview</b>, then continue to <b>Import Mesh</b> or <b>Swap With In-Game Mesh</b> after checking alignment.</li>
              <li><b>I want to batch-process loose DDS files</b>: use <b>Texture Workflow</b> with a small folder first, then review in <b>Compare</b>.</li>
              <li><b>I already edited one texture</b>: use <b>Texture Replacer</b> so the original DDS controls format, dimensions, mips, and output path.</li>
              <li><b>I want to edit inside the app</b>: use <b>Texture Editor</b>, save a project if you need layers later, then export or send the flattened PNG onward.</li>
              <li><b>I need to understand what a texture family is</b>: use <b>Research</b> for grouped sets, classifications, references, analysis, and notes.</li>
              <li><b>I am searching for XML, JSON, Lua, or config strings</b>: use <b>Text Search</b> against archives or loose folders.</li>
            </ul>
            <h3>Sidecar Cache Note</h3>
            <p>Building the global sidecar cache is intentionally optional because it can be expensive on large archives. It improves DDS related-file discovery, reverse references, mesh texture connections, and material-sidecar lookup. If you enable it, let the first run finish even when it takes a long time. Configure sidecar indexing and worker count in <b>Settings &gt; Archive Browser Performance</b>.</p>
            <h3>Safety Reminders</h3>
            <p>Visible color textures are not the same as technical maps. Height, displacement, normals, masks, vectors, and other precision-sensitive DDS files are riskier to push through PNG intermediates.</p>
            <ul>
              <li>Start with a safer preset.</li>
              <li>Keep automatic rules enabled.</li>
              <li>Use preview-only paths before writing mesh or archive output.</li>
              <li>Open Documentation for detailed field references, recipes, troubleshooting, and FAQs.</li>
            </ul>
            <h3>Where Details Live</h3>
            <p>The <b>Documentation</b> menu is topic-based and searchable. Use it for mesh import/swap steps, archive guides, Texture Workflow profiles and rules, Texture Editor tools, Texture Replacer packaging, Research, Text Search, settings, troubleshooting, and FAQs.</p>
            """
        )
        self.browser.setFont(self.font())
        self.browser.document().setDefaultFont(self.font())
        self.browser.setProperty("_i18n_source_html", quick_start_html)
        self.browser.setProperty("_i18n_html_es", _QUICK_START_HTML_ES)
        self.browser.setProperty("_i18n_html_de", _QUICK_START_HTML_DE)
        self.browser.setHtml(quick_start_html)
        layout.addWidget(self.browser, stretch=1)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.open_archive_locations_button = QPushButton("Open Archive Locations")
        self.open_setup_button = QPushButton("Open Setup && Paths")
        self.open_chainner_button = QPushButton("Open chaiNNer Setup")
        self.open_docs_button = QPushButton("Open Documentation")
        self.close_button = QPushButton("Close")
        button_row.addWidget(self.open_archive_locations_button)
        button_row.addWidget(self.open_setup_button)
        button_row.addWidget(self.open_chainner_button)
        button_row.addWidget(self.open_docs_button)
        button_row.addStretch(1)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        self.open_archive_locations_button.clicked.connect(self._open_archive_locations)
        self.open_setup_button.clicked.connect(self._open_setup)
        self.open_chainner_button.clicked.connect(self._open_chainner_setup)
        self.open_docs_button.clicked.connect(self._open_docs)
        self.close_button.clicked.connect(self.accept)

    def _open_setup(self) -> None:
        self.parent_window.focus_quick_start_sections(include_chainner=False)
        self.accept()

    def _open_chainner_setup(self) -> None:
        self.parent_window.focus_quick_start_sections(include_chainner=True)
        self.accept()

    def _open_archive_locations(self) -> None:
        self.parent_window.focus_archive_locations()
        self.accept()

    def _open_docs(self) -> None:
        parent_window = self.parent_window
        self.accept()
        if parent_window is not None and hasattr(parent_window, "show_documentation_dialog"):
            QTimer.singleShot(0, lambda: parent_window.show_documentation_dialog(topic_id="overview"))


class AboutDialog(QDialog):
    def __init__(
        self,
        parent,
        *,
        title: str,
        intro_html: str,
        sections: Sequence[Dict[str, str]],
        initial_section_id: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(840, 560)
        self.resize(1080, 720)
        self._sections: List[Dict[str, str]] = [dict(section) for section in sections]
        self._filtered_sections: List[Dict[str, str]] = list(self._sections)
        self._initial_section_id = initial_section_id.strip()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title_label = QLabel(title)
        title_font = QFont(self.font())
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        self.intro_html = intro_html
        guide_label = QLabel(
            "Search or choose a topic on the left. The reader shows one topic at a time so longer documentation stays navigable."
        )
        guide_label.setObjectName("HintLabel")
        guide_label.setWordWrap(True)
        layout.addWidget(guide_label)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_label = QLabel("Search")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search topics, fields, tabs, planner paths, planner profiles...")
        self.topic_count_label = QLabel("")
        self.topic_count_label.setObjectName("HintLabel")
        search_row.addWidget(search_label)
        search_row.addWidget(self.search_edit, stretch=1)
        search_row.addWidget(self.topic_count_label)
        layout.addLayout(search_row)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, stretch=1)

        topic_panel = QWidget()
        topic_layout = QVBoxLayout(topic_panel)
        topic_layout.setContentsMargins(0, 0, 0, 0)
        topic_layout.setSpacing(8)
        topic_hint = QLabel("Choose a documentation topic or search by feature name.")
        topic_hint.setObjectName("HintLabel")
        topic_hint.setWordWrap(True)
        topic_layout.addWidget(topic_hint)
        self.topic_list = QListWidget()
        self.topic_list.setAlternatingRowColors(True)
        self.topic_list.setProperty("_i18n_translate_items", True)
        topic_layout.addWidget(self.topic_list, stretch=1)
        splitter.addWidget(topic_panel)

        self.browser = QTextBrowser()
        self.browser.setReadOnly(True)
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.setFont(self.font())
        self.browser.document().setDefaultFont(self.font())
        self.browser.setProperty("_i18n_source_html", "")
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 760])

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self.search_edit.textChanged.connect(self._refresh_topic_list)
        self.topic_list.currentItemChanged.connect(self._handle_topic_changed)
        self.browser.anchorClicked.connect(self._handle_anchor_clicked)

        self._refresh_topic_list()
        if self._initial_section_id:
            self.select_section(self._initial_section_id)
        elif self.topic_list.count() > 0:
            self._select_first_topic()

    def _build_document_html(self, title: str, intro_html: str) -> str:
        section_html: List[str] = []
        for section in self._sections:
            section_id = str(section.get("id", "") or "").strip()
            section_title = str(section.get("title", "") or "").strip()
            section_body = str(section.get("html", "") or "")
            if not section_id or not section_title:
                continue
            section_html.append(
                f"<a name=\"{section_id}\"></a><h2>{section_title}</h2>{section_body}"
            )
        return (
            f"<h3>{title}</h3>{intro_html}"
            "<hr/>"
            + "<hr/>".join(section_html)
        )

    def _build_section_html(self, section: Dict[str, str]) -> str:
        section_id = str(section.get("id", "") or "").strip()
        section_title = str(section.get("title", "") or "").strip() or "Documentation"
        section_summary = str(section.get("summary", "") or "").strip()
        section_body = str(section.get("html", "") or "")
        category = self._section_category(section)
        summary_html = f"<p><i>{section_summary}</i></p>" if section_summary else ""
        category_html = f"<p><b>{category}</b></p>" if category else ""
        css = """
        <style>
        h2 { margin-top: 0; }
        h4 { margin-bottom: 4px; }
        table { border-collapse: collapse; width: 100%; margin: 8px 0 12px 0; }
        th, td { border: 1px solid #6b7280; padding: 5px 7px; vertical-align: top; }
        th { background: rgba(127, 127, 127, 0.18); font-weight: 600; }
        .doc-callout { border-left: 4px solid #3b82f6; padding: 7px 10px; margin: 8px 0; background: rgba(59, 130, 246, 0.10); }
        .doc-warning { border-left-color: #f59e0b; background: rgba(245, 158, 11, 0.12); }
        .doc-danger { border-left-color: #ef4444; background: rgba(239, 68, 68, 0.10); }
        .doc-ok { border-left-color: #22c55e; background: rgba(34, 197, 94, 0.10); }
        .pill { border: 1px solid #6b7280; border-radius: 4px; padding: 1px 4px; white-space: nowrap; }
        </style>
        """
        if section_id == "overview":
            return f"{css}<h2>{section_title}</h2>{category_html}{summary_html}{self.intro_html}<hr/>{section_body}"
        return f"{css}<h2>{section_title}</h2>{category_html}{summary_html}{section_body}"

    @staticmethod
    def _topic_search_text(section: Dict[str, str]) -> str:
        title = str(section.get("title", "") or "")
        keywords = str(section.get("keywords", "") or "")
        body = str(section.get("html", "") or "")
        plain_body = re.sub(r"<[^>]+>", " ", body)
        return f"{title}\n{keywords}\n{plain_body}".lower()

    @staticmethod
    def _section_category(section: Dict[str, str]) -> str:
        category = str(section.get("category", "") or "").strip()
        if category:
            return category
        section_id = str(section.get("id", "") or "").strip()
        if section_id in {"overview", "quick_start", "first_run_checklist", "faq"}:
            return "Start Here"
        if section_id.startswith("workflow_") or section_id in {"dds_output", "upscaling_backends", "texture_workflow_guides", "compare_review"}:
            return "Texture Workflow"
        if section_id in {"archive_browser", "archive_guides", "mesh_media_guides"}:
            return "Archive Browser"
        if section_id in {"texture_editor", "replace_assistant", "research", "text_search"}:
            return "Tools"
        if section_id in {"mod_packaging", "safety", "settings_files", "troubleshooting"}:
            return "Reference"
        return "Other"

    @staticmethod
    def _category_sort_key(category: str) -> Tuple[int, str]:
        order = {
            "Start Here": 0,
            "Texture Workflow": 1,
            "Archive Browser": 2,
            "Tools": 3,
            "Reference": 4,
            "Other": 99,
        }
        return (order.get(category, 50), category.lower())

    def _localized_category_label(self, category: str) -> str:
        language_code = self._current_language_code()
        labels = {
            "es": {
                "Start Here": "Primeros pasos",
                "Texture Workflow": "Flujo de texturas",
                "Archive Browser": "Explorador de archivos",
                "Tools": "Herramientas",
                "Reference": "Referencia",
                "Other": "Otros",
            },
            "de": {
                "Start Here": "Start",
                "Texture Workflow": "Textur-Workflow",
                "Archive Browser": "Archiv-Browser",
                "Tools": "Werkzeuge",
                "Reference": "Referenz",
                "Other": "Weitere Themen",
            },
        }
        return labels.get(language_code, {}).get(category, category)

    def _add_topic_group_header(self, category: str) -> None:
        item = QListWidgetItem("")
        item.setFlags(Qt.NoItemFlags)
        item.setData(Qt.UserRole, "")
        item.setSizeHint(QSize(0, 30))
        self.topic_list.addItem(item)

        header_widget = QWidget()
        header_widget.setAttribute(Qt.WA_TransparentForMouseEvents)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(8, 5, 8, 3)
        header_layout.setSpacing(8)

        label = QLabel(self._localized_category_label(category).upper())
        label_font = QFont(self.topic_list.font())
        label_font.setBold(True)
        label_font.setPointSize(max(8, label_font.pointSize() - 1))
        label.setFont(label_font)
        label.setAttribute(Qt.WA_TransparentForMouseEvents)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Plain)
        divider.setAttribute(Qt.WA_TransparentForMouseEvents)
        divider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        palette = self.topic_list.palette()
        muted = palette.color(QPalette.Disabled, QPalette.Text)
        if not muted.isValid():
            muted = palette.color(QPalette.Text)
        divider_color = palette.color(QPalette.Mid)
        if not divider_color.isValid():
            divider_color = muted
        label.setStyleSheet(f"color: {muted.name()};")
        divider.setStyleSheet(f"color: {divider_color.name()}; background: {divider_color.name()}; max-height: 1px;")

        header_layout.addWidget(label, stretch=0)
        header_layout.addWidget(divider, stretch=1)
        self.topic_list.setItemWidget(item, header_widget)

    def _refresh_topic_list(self) -> None:
        query = self.search_edit.text().strip().lower()
        current_section_id = self.current_section_id()
        self._filtered_sections = [
            section
            for section in self._sections
            if not query or query in self._topic_search_text(section)
        ]
        self.topic_list.blockSignals(True)
        self.topic_list.clear()
        grouped_sections: Dict[str, List[Dict[str, str]]] = {}
        for section in self._filtered_sections:
            grouped_sections.setdefault(self._section_category(section), []).append(section)
        for category in sorted(grouped_sections, key=self._category_sort_key):
            self._add_topic_group_header(category)
            for section in grouped_sections[category]:
                item = QListWidgetItem(str(section.get("title", "") or "Untitled"))
                item.setData(Qt.UserRole, str(section.get("id", "") or ""))
                item.setForeground(QBrush(self.topic_list.palette().color(QPalette.Text)))
                summary = str(section.get("summary", "") or "")
                if summary:
                    item.setToolTip(summary)
                self.topic_list.addItem(item)
        self.topic_list.blockSignals(False)
        self.topic_count_label.setText(self._format_topic_count(len(self._filtered_sections)))
        if not self._filtered_sections:
            self.browser.setHtml(
                "<h2>No Matching Topics</h2><p>Try a broader search term such as <b>DDS</b>, <b>archive</b>, <b>profile</b>, <b>replace</b>, or <b>FAQ</b>.</p>"
            )
            return
        if current_section_id:
            for index in range(self.topic_list.count()):
                item = self.topic_list.item(index)
                if str(item.data(Qt.UserRole) or "") == current_section_id:
                    self.topic_list.setCurrentItem(item)
                    return
        self._select_first_topic()

    def _select_first_topic(self) -> None:
        for index in range(self.topic_list.count()):
            item = self.topic_list.item(index)
            if str(item.data(Qt.UserRole) or ""):
                self.topic_list.setCurrentItem(item)
                return

    def _current_language_code(self) -> str:
        parent = self.parent()
        localizer = getattr(parent, "ui_localizer", None)
        return str(getattr(localizer, "language_code", "en") or "en").strip().lower()

    def _format_topic_count(self, count: int) -> str:
        language_code = self._current_language_code()
        if language_code == "es":
            return f"{count} tema" if count == 1 else f"{count} temas"
        if language_code == "de":
            return f"{count} Thema" if count == 1 else f"{count} Themen"
        return f"{count} topic" if count == 1 else f"{count} topics"

    def current_section_id(self) -> str:
        item = self.topic_list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "")

    def select_section(self, section_id: str) -> None:
        target_id = section_id.strip()
        if not target_id:
            return
        for index in range(self.topic_list.count()):
            item = self.topic_list.item(index)
            if str(item.data(Qt.UserRole) or "") == target_id:
                self.topic_list.setCurrentItem(item)
                self._render_section(target_id)
                return
        self.search_edit.clear()
        for index in range(self.topic_list.count()):
            item = self.topic_list.item(index)
            if str(item.data(Qt.UserRole) or "") == target_id:
                self.topic_list.setCurrentItem(item)
                self._render_section(target_id)
                return

    def _handle_topic_changed(self, current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem]) -> None:
        if current is None:
            return
        self._render_section(str(current.data(Qt.UserRole) or ""))

    def _scroll_to_section(self, section_id: str) -> None:
        if not section_id:
            return
        QTimer.singleShot(0, lambda: self.browser.scrollToAnchor(section_id))

    def _render_section(self, section_id: str) -> None:
        if not section_id:
            return
        for section in self._sections:
            if str(section.get("id", "") or "") == section_id:
                html = self._build_section_html(section)
                self.browser.setProperty("_i18n_source_html", html)
                self.browser.setHtml(html)
                QTimer.singleShot(0, lambda: self.browser.moveCursor(QTextCursor.Start))
                return

    def _handle_anchor_clicked(self, url: QUrl) -> None:
        if url.scheme() in {"http", "https"}:
            QDesktopServices.openUrl(url)
            return
        target_id = url.fragment().strip()
        if not target_id and url.scheme() == "topic":
            target_id = url.path().strip("/").strip()
        if target_id:
            self.select_section(target_id)
