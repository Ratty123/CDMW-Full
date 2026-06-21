"""Shell About and documentation dialog surface."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import APP_TITLE, APP_VERSION
from cdmw.ui.shell.theme_controller import build_monospace_font
from cdmw.ui.widgets import AboutDialog


class AboutControllerMixin:
    """About dialog, project notices, and documentation entry points."""

    def _project_text_file_candidates(self, filename: str) -> List[Path]:
        roots: List[Path] = []
        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                roots.append(Path(str(meipass)))
            roots.append(Path(sys.executable).resolve().parent)
        roots.append(Path(__file__).resolve().parents[3])
        candidates: List[Path] = []
        for root in roots:
            candidate = root / filename
            if candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def _read_project_text_file(self, filename: str, fallback: str) -> str:
        for candidate in self._project_text_file_candidates(filename):
            try:
                if candidate.exists():
                    return candidate.read_text(encoding="utf-8")
            except OSError:
                continue
        return fallback

    def _read_license_text(self) -> str:
        return self._read_project_text_file(
            "LICENSE",
            "License file was not found beside this build. Check the project repository or bundled release notes.",
        )

    def _read_third_party_notices_text(self) -> str:
        return self._read_project_text_file(
            "THIRD_PARTY_NOTICES.md",
            "Third-party notices file was not found beside this build.",
        )

    def _handle_about_page_link(self, url: QUrl) -> None:
        url_text = url.toString()
        if url_text.startswith("topic:"):
            self.show_documentation_dialog(topic_id=url_text.partition(":")[2] or "overview")
            return
        QDesktopServices.openUrl(url)

    def _build_about_overview_html(self) -> str:
        return self._build_about_intro_html() + """
            <h3>Application Areas</h3>
            <ul>
              <li><b>Texture Workflow</b>: batch processing, review, DDS rebuild, and mod-ready export.</li>
              <li><b>Archive Browser</b>: game-file search, preview, extraction, references, mesh tools, and supported patch workflows.</li>
              <li><b>Model Library and Icon Creator</b>: local/importable model routing and item-icon package helpers.</li>
              <li><b>Texture Editor</b>: visible texture edits with handoff back to workflow/replacement tools.</li>
              <li><b>Texture Replacer</b>: guided one-off replacement packaging.</li>
              <li><b>Research and Text Search</b>: inspect file families, references, strings, and notes.</li>
              <li><b>Profile, Settings, and Window</b>: portable app profiles, language/theme/performance preferences, and detachable work tabs.</li>
            </ul>
            <p>Use the top <b>Documentation</b> menu for the full searchable guide.</p>
            """

    def _build_about_overview_html_es(self) -> str:
        return f"""
            <p><b>{APP_TITLE} v{APP_VERSION}</b> es una herramienta de escritorio de Windows para explorar archivos de Crimson Desert, previsualizar recursos, aplicar parches compatibles, reconstruir DDS, editar texturas visibles, preparar reemplazos, investigar y buscar texto.</p>
            <p>Usa la busqueda y la lista de temas de la izquierda, o abre directamente:
            <a href="topic:quick_start">Inicio rapido</a>,
            <a href="topic:first_run_checklist">Lista de primera ejecucion</a>,
            <a href="topic:workflow_overview">Flujo de texturas</a>,
            <a href="topic:archive_browser">Explorador de archivos</a>,
            <a href="topic:mesh_media_guides">Importacion e intercambio de mallas</a>,
            <a href="topic:texture_editor">Editor de texturas</a>,
            <a href="topic:replace_assistant">Asistente de reemplazo</a>,
            <a href="topic:mod_packaging">Empaquetado mod-ready</a>,
            <a href="topic:faq">FAQ</a>,
            <a href="topic:troubleshooting">Solucion de problemas</a>.
            </p>
            <h3>Areas de la aplicacion</h3>
            <ul>
              <li><b>Flujo de texturas</b>: proceso por lotes, revision, reconstruccion DDS y exportacion mod-ready.</li>
              <li><b>Explorador de archivos</b>: busqueda de archivos del juego, vista previa, extraccion, referencias, herramientas de malla y parches compatibles.</li>
              <li><b>Biblioteca de modelos y creador de iconos</b>: enrutamiento de modelos locales/importables y paquetes de iconos de items.</li>
              <li><b>Editor de texturas</b>: ediciones de texturas visibles con envio a flujo o reemplazo.</li>
              <li><b>Asistente de reemplazo</b>: empaquetado guiado para reemplazos individuales.</li>
              <li><b>Investigacion y busqueda de texto</b>: inspeccion de familias de archivos, referencias, cadenas y notas.</li>
              <li><b>Perfil, configuracion y ventana</b>: perfiles portables, idioma, tema, rendimiento y pestanas separables.</li>
            </ul>
            <p>Usa el menu superior <b>Documentacion</b> para abrir la guia completa con busqueda.</p>
            """

    def _build_about_overview_html_de(self) -> str:
        return f"""
            <p><b>{APP_TITLE} v{APP_VERSION}</b> ist ein Windows-Desktopwerkzeug fuer Crimson-Desert-Archive: Browsing, Vorschau, kompatibles Patchen, DDS-Neuaufbau, sichtbare Texturbearbeitung, Ersatzpakete, Recherche und Textsuche.</p>
            <p>Nutze Suche und Themenliste links, oder springe direkt zu:
            <a href="topic:quick_start">Schnellstart</a>,
            <a href="topic:first_run_checklist">Erster-Lauf-Checkliste</a>,
            <a href="topic:workflow_overview">Textur-Workflow</a>,
            <a href="topic:archive_browser">Archiv-Browser</a>,
            <a href="topic:mesh_media_guides">Mesh-Import und Swap</a>,
            <a href="topic:texture_editor">Textur-Editor</a>,
            <a href="topic:replace_assistant">Ersetzungsassistent</a>,
            <a href="topic:mod_packaging">Mod-fertige Pakete</a>,
            <a href="topic:faq">FAQ</a>,
            <a href="topic:troubleshooting">Fehlerbehebung</a>.
            </p>
            <h3>Anwendungsbereiche</h3>
            <ul>
              <li><b>Textur-Workflow</b>: Stapelverarbeitung, Pruefung, DDS-Neuaufbau und mod-fertiger Export.</li>
              <li><b>Archiv-Browser</b>: Suche in Spieldateien, Vorschau, Extraktion, Referenzen, Mesh-Werkzeuge und kompatible Patch-Workflows.</li>
              <li><b>Modellbibliothek und Icon Creator</b>: Routing lokaler/importierbarer Modelle und Item-Icon-Pakete.</li>
              <li><b>Textur-Editor</b>: sichtbare Texturbearbeitung mit Uebergabe an Workflow oder Ersetzung.</li>
              <li><b>Ersetzungsassistent</b>: gefuehrte Einzelersatz-Paketierung.</li>
              <li><b>Recherche und Textsuche</b>: Dateifamilien, Referenzen, Strings und Notizen pruefen.</li>
              <li><b>Profil, Einstellungen und Fenster</b>: portable Profile, Sprache, Theme, Leistung und abtrennbare Arbeitstabs.</li>
            </ul>
            <p>Nutze das obere Menue <b>Dokumentation</b> fuer die vollstaendige durchsuchbare Anleitung.</p>
            """

    def _build_about_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QFrame()
        header.setFrameShape(QFrame.StyledPanel)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(4)
        title_label = QLabel(f"{APP_TITLE} v{APP_VERSION}")
        title_font = QFont(title_label.font())
        title_font.setPointSize(max(title_font.pointSize() + 4, title_font.pointSize()))
        title_font.setBold(True)
        title_label.setFont(title_font)
        subtitle_label = QLabel(
            "Crimson Desert archive browsing, texture workflows, mesh preview/import tools, item/icon helpers, research, app profiles, and safe mod packaging."
        )
        subtitle_label.setWordWrap(True)
        subtitle_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        header_layout.addWidget(title_label)
        header_layout.addWidget(subtitle_label)
        layout.addWidget(header)

        about_tabs = QTabWidget()
        layout.addWidget(about_tabs, stretch=1)

        overview_page = QWidget()
        overview_layout = QVBoxLayout(overview_page)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_browser = QTextBrowser()
        overview_browser.setOpenLinks(False)
        overview_browser.anchorClicked.connect(self._handle_about_page_link)
        overview_html = self._build_about_overview_html()
        overview_browser.setProperty("_i18n_source_html", overview_html)
        overview_browser.setProperty("_i18n_html_es", self._build_about_overview_html_es())
        overview_browser.setProperty("_i18n_html_de", self._build_about_overview_html_de())
        overview_browser.setHtml(overview_html)
        overview_layout.addWidget(overview_browser)
        about_tabs.addTab(overview_page, "Overview")

        license_page = QWidget()
        license_layout = QVBoxLayout(license_page)
        license_layout.setContentsMargins(0, 0, 0, 0)
        license_edit = QPlainTextEdit()
        license_edit.setReadOnly(True)
        license_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        license_edit.setFont(build_monospace_font(self.settings))
        license_edit.setPlainText(self._read_license_text())
        license_layout.addWidget(license_edit)
        about_tabs.addTab(license_page, "License")

        notices_page = QWidget()
        notices_layout = QVBoxLayout(notices_page)
        notices_layout.setContentsMargins(0, 0, 0, 0)
        notices_edit = QPlainTextEdit()
        notices_edit.setReadOnly(True)
        notices_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        notices_edit.setFont(build_monospace_font(self.settings))
        notices_edit.setPlainText(self._read_third_party_notices_text())
        notices_layout.addWidget(notices_edit)
        about_tabs.addTab(notices_page, "Third-Party Notices")

        return page

    def _build_about_intro_html(self) -> str:
        return f"""
        <p><b>{APP_TITLE} v{APP_VERSION}</b> is a Windows desktop tool for Crimson Desert archive browsing and preview, supported archive patching, DDS rebuild workflows, visible-texture editing, replacement packaging, research, and text search.</p>
        <p>Use the search box and topic list on the left, or jump straight to:
        <a href="topic:quick_start">Quick Start</a>,
        <a href="topic:first_run_checklist">First Run Checklist</a>,
        <a href="topic:workflow_overview">Texture Workflow</a>,
        <a href="topic:workflow_profiles">Workflow Profiles</a>,
        <a href="topic:workflow_rules">Ordered Rules</a>,
        <a href="topic:workflow_planner_profiles">Planner Profiles</a>,
        <a href="topic:workflow_planner_paths">Planner Paths</a>,
        <a href="topic:archive_browser">Archive Browser</a>,
        <a href="topic:mesh_media_guides">Mesh Import &amp; Swap</a>,
        <a href="topic:texture_editor">Texture Editor</a>,
        <a href="topic:replace_assistant">Texture Replacer</a>,
        <a href="topic:research">Research</a>,
        <a href="topic:text_search">Text Search</a>,
        <a href="topic:mod_packaging">Mod Packaging</a>,
        <a href="topic:profile_settings">Profile &amp; Settings</a>,
        <a href="topic:window_layout">Window &amp; Layout</a>,
        <a href="topic:safety">Safety</a>,
        <a href="topic:faq">FAQ</a>,
        <a href="topic:troubleshooting">Troubleshooting</a>.
        </p>
        """

    def show_documentation_dialog(self, _checked: bool = False, topic_id: str = "") -> None:
        title, intro_html, sections = self._build_about_document_for_language(self.ui_localizer.language_code)
        dialog = AboutDialog(
            self,
            title=title,
            intro_html=intro_html,
            sections=sections,
            initial_section_id=topic_id or "overview",
        )
        self.ui_localizer.apply(dialog)
        dialog.exec()

    def show_about_dialog(self, _checked: bool = False) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"About {APP_TITLE}")
        dialog.setMinimumSize(720, 520)
        dialog.resize(920, 680)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._build_about_page(), stretch=1)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        documentation_button = QPushButton("Documentation")
        close_button = QPushButton("Close")
        close_button.setDefault(True)
        button_row.addWidget(documentation_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        def _open_documentation() -> None:
            dialog.accept()
            QTimer.singleShot(0, self.show_documentation_dialog)

        documentation_button.clicked.connect(_open_documentation)
        close_button.clicked.connect(dialog.accept)
        self.ui_localizer.apply(dialog)
        dialog.exec()
