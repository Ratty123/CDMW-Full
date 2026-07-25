"""German About documentation content."""

from __future__ import annotations

from html import escape
from typing import Dict, List, Tuple

from cdmw.constants import APP_TITLE, APP_VERSION


class AboutDocumentationGermanMixin:
    """German documentation topic content."""

    def _build_about_document_for_german(self) -> Tuple[str, str, List[Dict[str, str]]]:
        title = f"Dokumentation zu {APP_TITLE}"
        intro_html = f"""
        <p><b>{APP_TITLE} v{APP_VERSION}</b> ist ein Windows-Desktopwerkzeug fuer Archivsuche, Asset-Vorschau, DDS-Neuaufbau, sichtbare Texturbearbeitung, Ersatzpakete, Recherche und Textsuche in Crimson Desert.</p>
        <p>Nutze Suche und Themenliste links, oder springe direkt zu:
        <a href="topic:quick_start">Schnellstart</a>,
        <a href="topic:first_run_checklist">Erster-Lauf-Checkliste</a>,
        <a href="topic:workflow_overview">Textur-Workflow</a>,
        <a href="topic:workflow_profiles">Workflow-Profile</a>,
        <a href="topic:workflow_rules">Geordnete Regeln</a>,
        <a href="topic:workflow_planner_profiles">Planerprofile</a>,
        <a href="topic:workflow_planner_paths">Planerpfade</a>,
        <a href="topic:texture_workflow_guides">Textur-Workflow-Anleitungen</a>,
        <a href="topic:compare_review">Vergleichen und pruefen</a>,
        <a href="topic:archive_browser">Archiv-Browser</a>,
        <a href="topic:mesh_media_guides">Mesh-Import und Swap</a>,
        <a href="topic:texture_editor">Textur-Editor</a>,
        <a href="topic:replace_assistant">Ersetzungsassistent</a>,
        <a href="topic:research">Recherche</a>,
        <a href="topic:text_search">Textsuche</a>,
        <a href="topic:mod_packaging">Mod-fertige Pakete</a>,
        <a href="topic:profile_settings">Profil und Einstellungen</a>,
        <a href="topic:window_layout">Fenster und Layout</a>,
        <a href="topic:safety">Sicherheit</a>,
        <a href="topic:faq">FAQ</a>,
        <a href="topic:troubleshooting">Fehlerbehebung</a>.
        </p>
        """
        settings_text = escape(str(self.settings_file_path))
        cache_text = escape(str(self.archive_cache_root))
        sections = [
            {
                "id": "overview",
                "title": "Uebersicht",
                "summary": "Ueberblick ueber die Hauptbereiche der App.",
                "keywords": "uebersicht funktionen tabs archiv workflow editor ersetzung recherche suche einstellungen",
                "html": """
                <p>Die App ist in Arbeitsbereiche aufgeteilt, damit nicht jede Aufgabe durch dieselbe Pipeline laufen muss.</p>
                <ul>
                  <li><b>Textur-Workflow</b>: Stapelverarbeitung loser DDS, optionales Upscaling, DDS-Neuaufbau, Vergleich und mod-fertiger Export.</li>
                  <li><b>Archiv-Browser</b>: Scannen, Filtern, Vorschau, Extraktion, Loose-Export und kompatible Patches.</li>
                  <li><b>Modellbibliothek</b>: lokale/importierbare Modelle scannen, anzeigen und an Archiv-Browser-Workflows uebergeben.</li>
                  <li><b>Icon Creator</b>: Quellbilder vorbereiten und kompatible Item-Icon-Pakete erzeugen.</li>
                  <li><b>Textur-Editor</b>: Ebenenbasierte Bearbeitung sichtbarer Texturen mit direkter Workflow-Uebergabe.</li>
                  <li><b>Ersetzungsassistent</b>: Gefuehrte Ersetzungen fuer bearbeitete PNG/DDS-Dateien.</li>
                  <li><b>Recherche</b>: DDS-Familien, Klassifizierung, Referenzen, Analyse und Notizen.</li>
                  <li><b>Textsuche</b>: Suche in Textdateien aus Archiven oder losen Ordnern.</li>
                  <li><b>Profil, Einstellungen und Fenster</b>: vollstaendiger Praeferenzexport/-import, Sprache, Leistung, 3D-Vorschau und abtrennbare Arbeitstabs.</li>
                </ul>
                """,
            },
            {
                "id": "first_run_checklist",
                "title": "Erster-Lauf-Checkliste",
                "summary": "Checkliste fuer Pfade, Werkzeuge, Richtlinie und erste Testausgabe.",
                "keywords": "erster lauf checkliste setup pfade natives dds workspace ncnn chainner richtlinie vorschau vergleichen",
                "html": """
                <ol>
                  <li>Oeffne <b>Einstellungen</b> und fuehre <b>Arbeitsbereich einrichten</b> aus, wenn die App die ueblichen Arbeitsordner erstellen soll.</li>
                  <li><b>Natives DDS-Werkzeug</b>: <code>cd-texture-dx.exe</code> ist gebuendelt und wird automatisch fuer Vorschau, Staging, Vergleich und DDS-Neuaufbau verwendet.</li>
                  <li>Setze <b>Original-DDS-Stamm</b>, <b>PNG-Stamm</b> und <b>Ausgabe-Stamm</b>. Starte mit einem kleinen Testordner.</li>
                  <li>Waehle ein Upscaling-Backend: <b>Deaktiviert</b> fuer Neuaufbau-Tests, direktes <b>Real-ESRGAN NCNN</b> fuer In-App-Upscaling oder <b>chaiNNer</b> fuer eine bereits getestete Kette.</li>
                  <li>Behalte zuerst eine sichere <b>Textur-Richtlinie</b> und aktive automatische Regeln.</li>
                  <li>Pruefe <b>Workflow-Profile</b>, <b>Geordnete Regeln</b> und <b>Passende Dateien</b>, wenn du Datei-Overrides brauchst.</li>
                  <li>Nutze <b>Richtlinienvorschau</b> vor <b>Start</b>, um die Planeraktion zu bestaetigen.</li>
                  <li>Fuehre <b>Scannen</b> aus, verarbeite einen kleinen Stapel und pruefe ihn in <b>Vergleichen</b>.</li>
                  <li>Erweitere Filter oder Quellstamm erst, wenn der kleine Stapel korrekt aussieht.</li>
                </ol>
                <p>Wenn etwas fehlschlaegt, oeffne <a href="topic:troubleshooting">Fehlerbehebung und Grenzen</a> und pruefe den Live-Log, bevor du viele Einstellungen gleichzeitig aenderst.</p>
                """,
            },
            {
                "id": "workflow_overview",
                "title": "Textur-Workflow",
                "summary": "Haupttab fuer Stapelverarbeitung loser DDS-Dateien.",
                "keywords": "textur workflow stapel dds png neuaufbau vergleichen start scan richtlinie",
                "html": """
                <p>Der Textur-Workflow scannt DDS-Dateien unter dem Originalstamm, plant die Aktion pro Datei, erstellt bei Bedarf PNG-Zwischenstufen, fuehrt optionales Upscaling aus und baut DDS-Ausgaben neu.</p>
                <ol>
                  <li>Konfiguriere <b>Einstellungen / Einrichtung</b>, <b>Einstellungen / Pfade</b> und <b>DDS-Ausgabe</b>.</li>
                  <li>Pruefe Profile, Regeln und passende Dateien.</li>
                  <li>Waehle ein Upscaling-Backend oder lasse Upscaling deaktiviert.</li>
                  <li>Nutze die Richtlinienvorschau fuer den Plan pro Datei.</li>
                  <li>Starte den Lauf und pruefe das Ergebnis in Vergleichen.</li>
                </ol>
                """,
            },
            {
                "id": "workflow_profiles",
                "title": "Workflow-Profile",
                "summary": "Wiederverwendbare Override-Sets pro Datei.",
                "keywords": "profile workflow aktion format groesse mips ncnn skalierung tile korrektur",
                "html": """
                <p>Workflow-Profile sind wiederverwendbare Einstellungen, die durch Regeln zugewiesen werden. Leere Felder erben die aktuellen globalen Werte.</p>
                <ul>
                  <li><b>Aktion</b>: Planerentscheidung erben oder Neuaufbau, Upscaling, Erhalt oder Ueberspringen erzwingen.</li>
                  <li><b>DDS-Format, Groesse und Mipmaps</b>: aendern die Ausgabe fuer passende Dateien.</li>
                  <li><b>NCNN-Optionen</b>: Modell, Skalierung, Tile, Extra-Argumente und Nachkorrektur fuer direktes Real-ESRGAN NCNN.</li>
                  <li><b>Starterprofile</b>: sichere Ausgangspunkte fuer Farbe, Normalen, Hoehe und Specular.</li>
                </ul>
                """,
            },
            {
                "id": "workflow_rules",
                "title": "Geordnete Regeln",
                "summary": "Treffertabelle, in der die letzte passende Regel gewinnt.",
                "keywords": "regeln glob exakter pfad profil semantik planer farben alpha",
                "html": """
                <p>Regeln werden von oben nach unten ausgewertet; der letzte Treffer gewinnt. Breite Familienregeln gehoeren nach oben, konkrete Korrekturen nach unten.</p>
                <ul>
                  <li><b>Treffer</b>: Glob fuer Muster oder exakter Pfad fuer eine einzelne Datei.</li>
                  <li><b>Workflow-Profil</b>: weist das wiederverwendbare Verhalten zu.</li>
                  <li><b>Semantik</b>: erzwingt eine technische Bedeutung, wenn die Erkennung nicht reicht.</li>
                  <li><b>Planerprofil und Planerpfad</b>: aendern technische Annahmen fuer diese Familie.</li>
                </ul>
                """,
            },
            {
                "id": "workflow_planner_profiles",
                "title": "Planerprofile",
                "summary": "Technische Profile fuer Format, Farbe, Alpha und Erhalt.",
                "keywords": "planer profile farbe normal maske scalar vector alpha erhalten",
                "html": """
                <p>Ein Planerprofil beschreibt technische Annahmen fuer eine Textur: Farbraum, erwartete Kompression, Alpha, Mipmaps und ob die Datei zuerst erhalten bleiben soll.</p>
                <ul>
                  <li><code>color_default</code>: sichtbare Farbtexturen.</li>
                  <li><code>normal_bc5</code>: lineare Normalmaps mit Erhalt als sicherem Standard.</li>
                  <li><code>scalar_bc4</code>: skalare Masken oder Ein-Kanal-Daten.</li>
                  <li><code>packed_mask_preserve_layout</code>: gepackte Kanaele, deren Layout nicht driften darf.</li>
                  <li><code>float_or_vector_preserve_only</code>: praezise Daten, die erhalten bleiben sollten.</li>
                </ul>
                """,
            },
            {
                "id": "workflow_planner_paths",
                "title": "Planerpfade",
                "summary": "Bevorzugter Zwischenpfad fuer passende Dateien.",
                "keywords": "planerpfade png sichtbar technisch erhalten hohe praezision",
                "html": """
                <p>Der Planerpfad legt fest, ob eine Textur durch den sichtbaren PNG-Pfad oder durch einen vorsichtigeren technischen Pfad gehen soll.</p>
                <ul>
                  <li><code>visible_color_png_path</code>: geeignet fuer sichtbare Farbtexturen und pruefbare Ausgaben.</li>
                  <li><code>technical_preserve_path</code>: behaelt das Original, wenn eine Aenderung zu riskant ist.</li>
                  <li><code>technical_high_precision_path</code>: nutzt einen technischen Pfad fuer kompatible Hochpraezisionsdaten.</li>
                </ul>
                <p>Technische Maps in den sichtbaren Pfad zu zwingen kann Helligkeit, Kanaele oder Nutzbarkeit beschaedigen.</p>
                """,
            },
            {
                "id": "workflow_matched_files",
                "title": "Passende Dateien",
                "summary": "Live-Ansicht der DDS-Dateien, die von Regeln und Filtern betroffen sind.",
                "keywords": "passende dateien profil regel aktion dds ncnn filter",
                "html": """
                <p>Die Tabelle zeigt DDS-Dateien unter dem Originalstamm, die den aktuellen Filter passieren und eine berechnete Aktion haben.</p>
                <ul>
                  <li><b>Pfad</b>: relativer Speicherort des DDS.</li>
                  <li><b>Semantik</b>: erkannter oder erzwungener Typ.</li>
                  <li><b>Regel</b>: letzte passende Regel.</li>
                  <li><b>Aktion</b>: Endergebnis aus Regel, Profil, Backend und Sicherheitslogik.</li>
                </ul>
                """,
            },
            {
                "id": "dds_output",
                "title": "DDS-Ausgabe und Staging",
                "summary": "Globale Werte fuer den DDS-Neuaufbau.",
                "keywords": "dds ausgabe format groesse mipmaps staging nativ png",
                "html": """
                <p>DDS-Ausgabe definiert globale Werte fuer Dateien ohne Profil-Override.</p>
                <ul>
                  <li><b>Format</b>: Originalformat behalten oder ein unterstuetztes natives DDS-Format erzwingen.</li>
                  <li><b>Groesse</b>: PNG-Groesse, Originalgroesse oder benutzerdefinierte Groesse verwenden.</li>
                  <li><b>Mipmaps</b>: behalten, voll erzeugen, eine verwenden oder Anzahl festlegen.</li>
                  <li><b>DDS-Staging</b>: erstellt PNG-Zwischenstufen vor externem Backend-Lauf.</li>
                </ul>
                """,
            },
            {
                "id": "upscaling_backends",
                "title": "Upscaling und Backends",
                "summary": "Unterschiede zwischen deaktiviert, direktem NCNN und chaiNNer.",
                "keywords": "upscaling backend ncnn chainner deaktiviert skalierung tile korrektur",
                "html": """
                <p>Upscaling kann deaktiviert sein, direktes Real-ESRGAN NCNN verwenden oder Arbeit an chaiNNer uebergeben.</p>
                <ul>
                  <li><b>Deaktiviert</b>: DDS aus vorhandenen PNG-Eingaben neu aufbauen, ohne Upscaling.</li>
                  <li><b>Real-ESRGAN NCNN</b>: direktes Backend mit Modell, Skalierung, Tile und Nachkorrektur.</li>
                  <li><b>chaiNNer</b>: externer Workflow, dessen Kette die echte Verarbeitung bestimmt.</li>
                </ul>
                <p>Automatische Texturregeln gelten weiterhin, auch wenn ein Upscaling-Backend aktiv ist.</p>
                """,
            },
            {
                "id": "texture_workflow_guides",
                "title": "Textur-Workflow-Anleitungen",
                "summary": "Rezepte fuer DDS-Neuaufbau, Upscaling und Profile.",
                "keywords": "textur workflow anleitungen rezept neuaufbau upscale ncnn chainner dds staging profil exakter pfad regeln",
                "html": """
                <h4>DDS ohne Upscaling neu aufbauen</h4>
                <ol>
                  <li>Setze <b>Original-DDS-Stamm</b>, <b>PNG-Stamm</b> und <b>Ausgabe-Stamm</b>. Das gebuendelte native DDS-Werkzeug wird automatisch gewaehlt.</li>
                  <li>Setze das Backend auf <b>Deaktiviert</b>.</li>
                  <li>Lege bearbeitete PNG-Dateien unter <b>PNG-Stamm</b> mit passenden relativen Pfaden ab.</li>
                  <li>Nutze <b>Scannen</b>, dann <b>Richtlinienvorschau</b> und danach <b>Start</b>.</li>
                </ol>
                <h4>Direkten NCNN-Upscale testen</h4>
                <ol>
                  <li>Konfiguriere NCNN-Programm und Modellordner.</li>
                  <li>Starte nur mit Farbe/UI/Emissiv-Inhalten oder lege exakte Pfadregeln fuer Testdateien an.</li>
                  <li>Nutze einen moderaten Tile-Wert, wenn VRAM knapp ist. Wenn das Backend fehlschlaegt, zuerst Tile senken und erst danach Modelle wechseln.</li>
                  <li>In Vergleichen pruefen und erst danach den Filter erweitern.</li>
                </ol>
                <h4>Profile fuer einen gemischten Ordner nutzen</h4>
                <ol>
                  <li>Erstelle oder dupliziere Profile fuer sichtbare Farbe, technische Maps mit Nur-Erhalt und besondere DDS-Ausgabeanforderungen.</li>
                  <li>Fuege breite Glob-Regeln fuer haeufige Suffixfamilien weiter oben ein.</li>
                  <li>Nutze <b>Passende Dateien</b>, um exakte Pfadregeln fuer Ausnahmen weiter unten zu erstellen.</li>
                  <li>Oeffne <b>Richtlinienvorschau</b> und bestaetige die finale Aktionsspalte vor dem Lauf.</li>
                </ol>
                """,
            },
            {
                "id": "compare_review",
                "title": "Vergleichen und pruefen",
                "summary": "Seit-an-Seit-Pruefung von Original-DDS und Ausgabe.",
                "keywords": "vergleichen pruefen original ausgabe helligkeit kanaele mips",
                "html": """
                <p>Vergleichen hilft, Ausgaben zu pruefen, bevor ein grosser Stapellauf vertrauenswuerdig ist.</p>
                <ul>
                  <li>Vergleiche Original und Ergebnis visuell.</li>
                  <li>Achte auf Helligkeit, Farbe, Alpha, Details oder technische Kanaele.</li>
                  <li>Wenn etwas falsch aussieht, passe Richtlinie, Profil oder Backend vor dem Export an.</li>
                </ul>
                """,
            },
            {
                "id": "archive_browser",
                "title": "Archiv-Browser",
                "summary": "Scannen, Filtern, Vorschau, aktiver Mod-/Originalstatus, Item Finder, Extraktion und Export aus Paketen.",
                "keywords": "archiv browser paket vorschau extraktion patch obj fbx referenzen item finder dmm aktiver mod verdeckt platzierung hkx",
                "html": """
                <p>Der Archiv-Browser arbeitet mit .pamt/.paz-Paketen. Er filtert Eintraege, zeigt kompatible Formate an, extrahiert Dateien, sendet Assets an Recherche oder Editor und oeffnet kompatible Export-, Import- und Patch-Workflows.</p>
                <ul>
                  <li>Die Dateitabelle zeigt originale und gemoddete Eintraege, wenn sie dieselbe virtuelle Route haben. Die Spalte <b>Status</b> markiert aktiven Mod, aktives Original, verdeckte Zeilen oder Mod-hinzugefuegte Dateien.</li>
                  <li>Die Vorschau zeigt Bilder, farbigen Text/XML/HKX-Zusammenfassungen, Binaerzusammenfassungen, Audio/Video, 3D-Modelle und Material-/Sidecar-Kontext, soweit aufloesbar.</li>
                  <li>Die Modellvorschau versucht Geometrie, Sidecars, Texturen, Skelette und Metadaten aufzuloesen.</li>
                  <li><b>Item Finder</b> sucht nach Name, Kategorie, Icon und iteminfo-/Lokalisierungsbeziehungen; er kann auch die Platzierungsquellen-Auswahl starten.</li>
                  <li>OBJ/FBX-Exporte koennen ein Manifest mit Referenzen fuer den Reimport schreiben.</li>
                  <li><b>Mesh-Importvorschau</b> testet OBJ/DAE/glTF/GLB, ohne Ausgabe zu schreiben.</li>
                  <li><b>Mesh importieren</b> nutzt dieselbe Pruefung und kann nach Bestaetigung mod-fertige Loose-Ausgabe oder kompatible Patches schreiben.</li>
                  <li><b>Mit Ingame-Mesh tauschen</b> markiert eine Archiv-Mesh als Ziel und nutzt eine andere geladene Mesh als Quelle fuer die Ausrichtung.</li>
                  <li><b>HKX bearbeiten</b> und <b>Platzierungsquelle waehlen</b> kopieren Prefab-/Socket-Daten von einer anderen Waffen-/Modellfamilie. Wenn moeglich den sichtbaren <code>.pac</code> waehlen; der Picker zeigt eine statische Geometrie-Miniatur, die visuelle Bearbeitung laeuft in der .NET/Vortice-Vorschau.</li>
                  <li>Direkte Patches sind nur fuer Formate sinnvoll, die die App sicher rekonstruieren kann.</li>
                </ul>
                """,
            },
            {
                "id": "texture_editor",
                "title": "Textur-Editor",
                "summary": "Ebeneneditor fuer sichtbare Texturarbeit.",
                "keywords": "textur editor ebenen malen kanaele maske auswahl transformieren",
                "html": """
                <p>Der Textur-Editor ist fuer sichtbare Arbeiten gedacht: Ebenen, Auswahl, Malen, Kanaele, Masken, Transformationen und PNG-Export.</p>
                <p>Er macht technische Maps nicht automatisch sicher. Pruefe Semantik und Richtlinie, bevor du technische DDS-Dateien neu aufbaust.</p>
                """,
            },
            {
                "id": "replace_assistant",
                "title": "Ersetzungsassistent",
                "summary": "Gefuehrter Ablauf fuer einzelne PNG/DDS-Ersetzungen.",
                "keywords": "ersetzungsassistent png dds original ausgabe mod ready",
                "html": """
                <p>Der Assistent nimmt ein bearbeitetes Bild, ordnet es dem richtigen Original-DDS zu, baut die Ausgabe mit aktueller Richtlinie neu auf und erstellt einen mod-fertigen Ordner.</p>
                <ul>
                  <li>Nutze ihn, wenn die Textur bereits ausserhalb der App bearbeitet wurde.</li>
                  <li>Pruefe immer, dass Originaldatei und rekonstruierte Ausgabe zur erwarteten Textur gehoeren.</li>
                </ul>
                """,
            },
            {
                "id": "research",
                "title": "Recherche",
                "summary": "Pruefung von Familien, Klassifizierung, Referenzen, DDS-Analyse und Notizen.",
                "keywords": "recherche familien dds klassifizierung referenzen notizen berichte",
                "html": """
                <p>Recherche buendelt Daten, um Texturfamilien und zusammenhaengende Dateien vor Regeln oder Exporten zu verstehen.</p>
                <ul>
                  <li>Pruefe DDS-Familien und erkannte Rollen.</li>
                  <li>Klassifiziere unbekannte Dateien und speichere lokale Freigaben.</li>
                  <li>Nutze Referenzen, UI-Einschraenkungen, Heatmaps, Notizen und Berichte.</li>
                </ul>
                """,
            },
            {
                "id": "text_search",
                "title": "Textsuche",
                "summary": "Suche in Textdateien aus Archiven oder losen Ordnern.",
                "keywords": "textsuche xml json cfg lua regex export vorschau",
                "html": """
                <p>Textsuche findet Zeichenketten oder Regex-Muster in Textdateien aus Archiven oder losen Ordnern.</p>
                <ul>
                  <li>Zeigt Treffer mit hervorgehobenem Kontext an.</li>
                  <li>Exportiert Ergebnisse mit erhaltener Ordnerstruktur.</li>
                  <li>Hilfreich fuer .xml, .json, .cfg, .lua und aehnliche Formate.</li>
                </ul>
                """,
            },
            {
                "id": "settings_files",
                "title": "Einstellungen, Dateien und Abhaengigkeiten",
                "summary": "Lokale Konfiguration, Cache, Projektdateien und externe Werkzeuge.",
                "keywords": "einstellungen dateien cache abhaengigkeiten natives dds ncnn chainner sprache",
                "html": f"""
                <p>Konfiguration, Cache und Praeferenzen werden neben Installation oder lokalem Checkout gespeichert.</p>
                <ul>
                  <li><b>Konfigurationsdatei</b>: <code>{settings_text}</code></li>
                  <li><b>Archiv-Cache</b>: <code>{cache_text}</code></li>
                  <li><b>cd-texture-dx.exe</b> ist gebuendelt und fuer DDS-Vorschau, DDS-zu-PNG, Vergleich und DDS-Neuaufbau erforderlich.</li>
                  <li><b>Real-ESRGAN NCNN</b> und <b>chaiNNer</b>: optionale Upscaling-Backends.</li>
                  <li><b>Sprachen</b>: Sprachdatei exportieren, Werte bearbeiten und wieder importieren.</li>
                </ul>
                """,
            },
            {
                "id": "troubleshooting",
                "title": "Fehlerbehebung und Grenzen",
                "summary": "Haeufige Fehler und aktuelle Einschraenkungen.",
                "keywords": "fehlerbehebung grenzen natives dds ncnn chainner png helligkeit cache vorschau",
                "html": """
                <ul>
                  <li><b>Natives DDS-Werkzeug fehlt</b>: DDS-Vorschau und Neuaufbau stoppen mit einem eindeutigen Fehler. Pruefe, ob <code>cd-texture-dx.exe</code> neben der Anwendung paketiert wurde.</li>
                  <li><b>NCNN-Modelle fehlen</b>: direktes NCNN braucht eine gueltige EXE und passende .param/.bin-Paare.</li>
                  <li><b>Keine PNG-Ausgabe</b>: wenn das Backend kein nutzbares PNG erzeugt, gibt es nichts zum Neuaufbauen.</li>
                  <li><b>Falsche chaiNNer-Pfade</b>: eine Kette kann aus falschen Ordnern lesen oder dorthin schreiben.</li>
                  <li><b>Helligkeits- oder Detaildrift</b>: vergleiche Ergebnisse und passe Modell, Richtlinie oder Nachkorrektur an.</li>
                  <li><b>Technische Texturen</b>: Normalen, Masken, Vektoren und gepackte Kanaele sollten zuerst erhalten bleiben.</li>
                </ul>
                """,
            },
        ]
        sections.extend(
            [
                {
                    "id": "quick_start",
                    "title": "Schnellstart",
                    "summary": "Erste Schritte fuer Spielpfad, Workspace und Werkzeuge.",
                    "keywords": "schnellstart spiel paket workspace natives dds sidecar",
                    "html": """
                    <ol>
                      <li>Erstelle einen eigenen App-Ordner und lege die portable .exe dort ab.</li>
                      <li>Setze unter <b>Einstellungen &gt; Archiv-Orte</b> den Spiel-/Paketpfad.</li>
                      <li>Fuehre <b>Arbeitsbereich einrichten</b> aus, um Workspace, tools, Ausgabe, PNG und Extraktion anzulegen.</li>
                      <li>Nutze das gebuendelte native DDS-Werkzeug <code>cd-texture-dx.exe</code> fuer Vorschau und Neuaufbau.</li>
                      <li>Scanne zuerst einen kleinen Testsatz.</li>
                      <li>Fuer Meshes zuerst <b>Mesh-Importvorschau</b> im Archiv-Browser nutzen. <b>Mesh importieren</b> oder <b>Mit Ingame-Mesh tauschen</b> erst nach der Ausrichtungspruefung verwenden.</li>
                    </ol>
                    <div class="doc-callout doc-warning"><b>Sidecar-Cache:</b> kann lange dauern, verbessert aber verwandte Dateien, Modell-Textur-Verbindungen und Material-Sidecar-Suche. Wenn aktiviert, den ersten Lauf fertig werden lassen.</div>
                    """,
                },
                {
                    "id": "archive_guides",
                    "title": "Archiv-Browser-Anleitungen",
                    "summary": "Navigieren, Verbindungen finden, exportieren und an Workflows uebergeben.",
                    "keywords": "archiv anleitung navigieren referenzen verbindungen metadaten export material xml",
                    "html": """
                    <table>
                      <tr><th>Ziel</th><th>Bereich</th><th>Hinweis</th></tr>
                      <tr><td>Modell oder Item finden</td><td>Suche nach Pfad, Endung, Paket oder Ingame-Name.</td><td><b>Exakter Item-Name</b> erscheint nur bei direktem iteminfo-/Lokalisierungs-/Modellhash-Link. <b>Hinweis auf verwandten Namen</b> markiert abgeleitete Beziehungen, keine bewiesene Identitaet.</td></tr>
                      <tr><td>Aktives Duplikat erkennen</td><td>Spalte <b>Status</b> lesen.</td><td><b>Aktiver Mod</b> ist die Nutzlast, die ueber dem Original gewinnt. Verdeckte Zeilen bleiben sichtbar, sind aber nicht die aktive Nutzlast.</td></tr>
                      <tr><td>Verwandte Texturen finden</td><td>Modell waehlen und <b>Referenzierte Dateien</b> lesen.</td><td>Zeigt Texturen, Sidecars, Skelette, Animationen, Paket und Status.</td></tr>
                      <tr><td>Platzierungsquelle waehlen</td><td><b>HKX bearbeiten</b> und dann <b>Platzierungsquelle waehlen</b> nutzen, oder ueber <b>Item Finder</b> starten.</td><td>Wenn moeglich den sichtbaren <code>.pac</code> waehlen. HKX ist Kontext, aber Platzierung wird meist ueber Prefab/Socket-Daten der Modellfamilie aufgeloest.</td></tr>
                      <tr><td>Metadaten pruefen</td><td><b>Details</b> oeffnen.</td><td>Enthaelt Groesse, Kompression, lesbare Strings, Diagnostik und Warnungen.</td></tr>
                      <tr><td>XML/Material bearbeiten</td><td><b>Materialwerte bearbeiten</b>, wenn ein Sidecar erkannt wurde.</td><td>Exportiert bearbeitete Werte als mod-fertiges Paket.</td></tr>
                    </table>
                    <h4>Gemoddete Duplikate und aktive Zeilen</h4>
                    <ul>
                      <li>Wenn Originalpaket und Mod dieselbe virtuelle Route enthalten, zeigt der Browser beide Zeilen, damit sichtbar bleibt, was existiert.</li>
                      <li><b>Aktiver Mod</b> oder <b>aktives Original</b> markiert die Zeile, die gewinnt. Verdeckte Zeilen sind niedriger priorisiert. <b>Mod-hinzugefuegt</b> bedeutet: keine Original-Gegenpart.</li>
                      <li>Vor Extraktion oder Ersatz pruefen, ob du Originaldaten oder DMM-/Mod-Manager-Ersatzdaten ansiehst.</li>
                    </ul>
                    <p>Beginne mit breiten Filtern und verfeinere dann nach Paket, Rolle, Endung, Ordner, Groesse oder Vorschaufaehigkeit. Vor grossen Exporten den Filter pruefen.</p>
                    """,
                },
                {
                    "id": "mesh_media_guides",
                    "title": "Mesh-, 3D- und Medien-Anleitungen",
                    "summary": "Meshes exportieren, ersetzen, pruefen und Sidecars verstehen.",
                    "keywords": "mesh 3d obj fbx gltf dae pac pam material sidecar textur",
                    "html": """
                    <table>
                      <tr><th>Aktion</th><th>Verwendung</th><th>Ergebnis</th></tr>
                      <tr><td>OBJ exportieren</td><td>Round-trip-Bearbeitung mit kompatiblem Sidecar.</td><td>Schreibt Geometrie und Kontext fuer Reimport.</td></tr>
                      <tr><td>FBX exportieren</td><td>Inspektion oder DCC-Arbeit.</td><td>Gut zum Anzeigen; keine Garantie fuer patchbaren Reimport.</td></tr>
                      <tr><td>Mesh-Importvorschau</td><td>OBJ/DAE/glTF/GLB testen, ohne Dateien zu schreiben.</td><td>Erzeugt nur eine Vorschau.</td></tr>
                      <tr><td>DDS-Importvorschau</td><td>Eine DDS-Textur am gewaehlten Modell testen, ohne Dateien zu schreiben.</td><td>Erzeugt nur eine Modellvorschau.</td></tr>
                      <tr><td>Mesh importieren</td><td>Unterstuetzten Ersatz erstellen.</td><td>Erlaubt Patch oder mod-fertige Loose-Ausgabe, wo kompatibel.</td></tr>
                      <tr><td>Mit Ingame-Mesh tauschen</td><td>Eine andere Archiv-Mesh als Ersatz fuer das gewaehlte Ziel verwenden.</td><td>Oeffnet Mesh-Ersetzungsausrichtung und uebernimmt verwandte Dateien, wenn kompatibel.</td></tr>
                      <tr><td>HKX bearbeiten</td><td>Platzierung aus einer anderen Waffen-/Modellfamilie kopieren.</td><td>Zeigt Zielkontext, waehlt Quelle, vergleicht Platzierung und erstellt ein Loose-Platzierungspaket.</td></tr>
                    </table>
                    <h4>Mesh-Ersetzungsausrichtung</h4>
                    <ul>
                      <li>Dies ist die zentrale Pruefung fuer statische Ersetzungen und Ingame-Mesh-Swaps: Geometrie, gemappte Teile, Texturen, Sidecars, Position, Skalierung, Rotation und Exportwerte.</li>
                      <li>Nutze <b>Mesh-Importvorschau</b>, bevor Dateien geschrieben werden.</li>
                      <li>Nutze <b>Mesh importieren</b> erst nach Kompatibilitaets-, Platzierungs- und Texturplan-Pruefung.</li>
                      <li>Erweiterte DDS-Slot-Overrides sind manuelle Reparaturwerkzeuge; beginne mit den Vorschlaegen.</li>
                    </ul>
                    <h4>Materialautoritaet und Sidecars</h4>
                    <ul>
                      <li><b>Materialautoritaet</b> nutzt die bewaehrte quellenbasierte Route: Quellfarbe ueber Overlay-Farbe, PBR-/Materialmaske ueber Detailmaske und keine glaenzende Color-Blend-Reaktion.</li>
                      <li><b>Materialautoritaet manuell</b> startet mit derselben Route und zeigt Override-Regler fuer erweiterte Reparatur.</li>
                      <li>Legacy Runtime XML und Echte Quellenautoritaet bleiben fuer alte Einstellungen/Debug ladbar, werden aber nicht mehr als Standardauswahl gezeigt.</li>
                      <li><b>Andere Original-Mesh verwenden</b> waehlt eine andere Originalreferenz fuer Ausrichtung oder Materialkontext.</li>
                      <li>Pruefe den Platzierungszustand <b>Verstaut / am Koerper</b> gegen <b>Gehalten / in der Hand</b>, bevor Pakete gebaut werden.</li>
                    </ul>
                    <h4>Ingame-Mesh-Swap</h4>
                    <ol>
                      <li>Waehle die Archiv-Mesh, die ersetzt werden soll, und markiere sie als Swap-Ziel.</li>
                      <li>Waehle, ob verwandte Dateien wie Texturen, Sidecars, Skelette oder Animationen eingeschlossen werden. Skelette und Animationen sind explizit, weil inkompatible Rigs oder Physikdaten Assets beschaedigen koennen.</li>
                      <li>Waehle eine andere geladene Archiv-Mesh als Quelle.</li>
                      <li>Pruefe Platzierung und Texturzuordnung in <b>Mesh-Ersetzungsausrichtung</b>.</li>
                      <li>Schreibe Loose-Ausgabe oder patche Archive nur, wenn das Ergebnis visuell und strukturell plausibel ist.</li>
                    </ol>
                    <div class="doc-callout doc-warning"><b>Mesh-Grenzen:</b> statische Ersetzungen koennen Geometrie und kompatible Sidecars retargeten, konvertieren aber nicht jedes Rig, jede Animation, jeden Skin oder komplexe Materialgraphen in native Spieldaten.</div>
                    <h4>HKX-Platzierung und Sockets</h4>
                    <ul>
                      <li><b>HKX bearbeiten</b> behandelt das geoeffnete Asset als Ziel, das sich aendert. <b>Platzierungsquelle waehlen</b> sucht die Waffen-/Modellquelle, deren Platzierung kopiert wird.</li>
                      <li>Wenn moeglich einen sichtbaren <code>.pac</code> als Quelle waehlen. Du kannst direkt in Archivindizes suchen oder mit <b>Item Finder</b> ueber Name, Icon oder Kategorie starten.</li>
                      <li>Der Quellen-Picker zeigt eine statische Geometrie-Miniatur zur Modellbestaetigung; die visuelle Bearbeitung laeuft in der .NET/Vortice-Vorschau.</li>
                      <li><b>Platzierung vergleichen</b> prueft aufgeloeste Prefab-/Socket-/HKX-Daten vor dem Paketbau. <b>Socket-Werte bearbeiten</b> erscheint, wenn das wiederhergestellte XML sicher angezeigt und geschrieben werden kann.</li>
                    </ul>
                    """,
                },
                {
                    "id": "mod_packaging",
                    "title": "Mod-fertige Pakete",
                    "summary": "Loose-Ausgabe, manifest.json, .no_encrypt und Backups.",
                    "keywords": "mod ready paket ausgabe info json no_encrypt backup",
                    "html": """
                    <p>Normale Ausgabe und mod-fertige Pakete bleiben getrennt, damit Ergebnisse vor Installation geprueft werden koennen.</p>
                    <ul>
                      <li><b>Ausgabe-Stamm</b> enthaelt normale DDS-Ergebnisse.</li>
                      <li><b>Mod-ready Export</b> erzeugt eine Loose-Struktur mit manifest.json, optionalen Manager-Metadaten und optional .no_encrypt.</li>
                      <li><b>Ziel-Mod-Manager</b> kann DMM-, CDUMM-, JMM-JSON-, Crimson-Sharp-/Crimson-Browser- und Field-JSON-v3.1-Formate schreiben. CDUMM nutzt <code>manifest.json</code>, <code>modinfo.json</code>, <code>.no_encrypt</code> und einen <code>files/</code>-Wrapper; DMM-Texturordner nutzen <code>modinfo.json</code>, DMM-Meshordner behalten <code>manifest.json</code> plus <code>modinfo.json</code>.</li>
                      <li>Archiv-Patches brauchen Bestaetigung und nutzen Backup/Wiederherstellung, wo verfuegbar.</li>
                    </ul>
                    """,
                },
                {
                    "id": "profile_settings",
                    "title": "Profil und Einstellungen",
                    "summary": "Was Profile, Diagnosen, Praeferenzen und Sprachen enthalten.",
                    "keywords": "profil einstellungen export import diagnose sprache darstellung start leistung vorschau editor ersetzer",
                    "html": """
                    <p><b>Profil &gt; Profil exportieren</b> speichert die Workflow-Konfiguration und einen vollstaendigen App-Einstellungssnapshot: Pfade, Regeln/Profile, Paketmetadaten, aktuelle Archiv-Browser-Steuerung, Darstellung, Sprache, Startverhalten, Leistung, Cache/Indexierung, 3D-Vorschau, Textur-Ersetzer, Textur-Editor, Sicherheitsabfragen und Fenstergeometrie.</p>
                    <ul>
                      <li>Ein App-Profil ist ein einzelner app-weiter Snapshot, keine getrennten Profile pro Tab. Es enthaelt Werkzeugpraeferenzen und Layout abgetrennter Fenster in einer Profildatei.</li>
                      <li><b>Profil importieren</b> stellt zuerst den Workflow wieder her und laedt danach die Einstellungen in Einstellungen, Textur-Ersetzer und Textur-Editor.</li>
                      <li>Profile speichern keine geoeffneten Archive, aktiven Dokumente oder Projekt-Sitzungen pro Tab.</li>
                      <li><b>Diagnosen exportieren</b> enthaelt dasselbe Profil, Logs, Cache-Zusammenfassung, chaiNNer-Analyse, Crash-Kontext wenn vorhanden, README, Lizenz und Drittanbieterhinweise.</li>
                    </ul>
                    <p>Einstellungen hat sieben Seiten in der linken Liste: <b>Setup</b>, <b>Start</b>, <b>Pfade</b>, <b>Leistung</b>, <b>Darstellung</b>, <b>Layout</b> und <b>Sicherheit</b>.</p>
                    <ul>
                      <li><b>Einstellungen / Setup</b>: Workspace anlegen, externe Werkzeuge finden und Status der Authoring-Helfer.</li>
                      <li><b>Einstellungen / Start</b>: Archiv-Autoload, Cache-Praeferenz und Wiederherstellung des letzten Tabs. Archivfilter starten neutral.</li>
                      <li><b>Einstellungen / Pfade</b>: Workflow-Wurzeln, Archivorte, Spiel-/Paketwurzel und Extraktionswurzel.</li>
                      <li><b>Einstellungen / Leistung</b>: Workload-Preset, Batches der Archivliste, nativer Helfer, optionale Sidecar-Indexierung, Vorschau-Caches und .NET/Vortice-Paketcache.</li>
                      <li><b>Einstellungen / Darstellung</b>: Themes, integriertes Spanisch/Deutsch, eigene Sprachdateien, Schrift, Dichte, Farben und 3D-Werte.</li>
                      <li><b>Einstellungen / Layout und Sicherheit</b>: Speicher fuer Pane-Groessen, Aufraeum-Bestaetigungen und zusaetzlicher lokaler Diagnosekontext.</li>
                    </ul>
                    <p>Sprachexport erzeugt JSON mit englischen Schluesseln. Schluessel unveraendert lassen und nur uebersetzte Werte bearbeiten.</p>
                    """,
                },
                {
                    "id": "window_layout",
                    "title": "Fenster und Layout",
                    "summary": "Abtrennbare Tabs, gespeicherte Geometrie und Layoutspeicher.",
                    "keywords": "fenster layout abtrennen andocken tab geometrie splitter wiederherstellen",
                    "html": """
                    <p>Das Menu <b>Fenster</b> kann schwere Arbeitsbereiche in eigene Top-Level-Fenster verschieben, ohne ihren Platz in der Hauptnavigation zu verlieren.</p>
                    <ul>
                      <li><b>Aktuelles Werkzeug abtrennen</b> verschiebt das aktuelle Werkzeug in ein neues Fenster und laesst einen Platzhalter zurueck.</li>
                      <li><b>Aktuelles Werkzeug wieder andocken</b> und <b>Alle Werkzeuge wieder andocken</b> bringen abgetrennte Werkzeuge in ihre urspruenglichen Tabgruppen zurueck.</li>
                      <li>Abgetrennte Geometrie wird unter <code>window/detached/&lt;tool&gt;/geometry</code> gespeichert; das Hauptfenster nutzt <code>window/geometry</code>.</li>
                      <li><b>Einstellungen / Layout</b> steuert, ob Pane-Groessen und Splitter sitzungsuebergreifend gespeichert werden.</li>
                      <li>Die untere Haelfte des Menues <b>Fenster</b> listet je Werkzeug einen Eintrag <b>&lt;Werkzeug&gt; anzeigen</b>: er waehlt den Tab aus oder holt das abgetrennte Fenster nach vorn.</li>
                    </ul>
                    """,
                },
                {
                    "id": "safety",
                    "title": "Sicherheitsmodell",
                    "summary": "Erhalt, technische Texturen und bestaetigte Operationen.",
                    "keywords": "sicherheit erhalten technisch normalen masken backup dry run",
                    "html": """
                    <div class="doc-callout doc-danger">Nicht jede DDS ist ein sichtbares Bild. Normalen, Masken, Hoehe, Vektoren und gepackte Kanaele koennen durch generische PNG-Pfade kaputtgehen.</div>
                    <ul>
                      <li>Mit sicherer Richtlinie und aktiven automatischen Regeln starten.</li>
                      <li><b>Richtlinienvorschau</b> vor grossen Laeufen nutzen.</li>
                      <li>Unklare Familien in Recherche klassifizieren, bevor aggressive Profile erzwungen werden.</li>
                    </ul>
                    """,
                },
                {
                    "id": "faq",
                    "title": "FAQ",
                    "summary": "Kurze Antworten auf haeufige Fragen.",
                    "keywords": "faq natives dds sidecar ncnn chainner helligkeit archiv",
                    "html": """
                    <p><b>Muss ich einen DDS-Konverter installieren?</b><br/>Nein. CDMW enthaelt <code>cd-texture-dx.exe</code> und nutzt es fuer alle DDS-Vorschau- und Neuaufbau-Workflows.</p>
                    <p><b>Sollte ich alle Texturen hochskalieren?</b><br/>Nein. Mit Farbe/UI/Emissive starten; Normalen, Masken und technische Maps zuerst erhalten.</p>
                    <p><b>Warum dauert der Sidecar-Cache lange?</b><br/>Er liest viele Sidecars fuer globale Verbindungen. Teuer, aber nuetzlich fuer verwandte Dateien.</p>
                    <p><b>Wann nutze ich den Ersetzungsassistenten?</b><br/>Fuer eine einzelne bearbeitete Textur. Fuer Stapel den Textur-Workflow nutzen.</p>
                    """,
                },
            ]
        )
        return title, intro_html, sections
