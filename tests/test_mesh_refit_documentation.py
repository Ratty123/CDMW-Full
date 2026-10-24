"""The fitting guidance reaches both documentation surfaces in every locale."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cdmw.ui.localization import UiLocalizer
from cdmw.ui.shell.about_documentation_en import AboutDocumentationEnglishMixin
from cdmw.ui.shell.help_dialogs import AboutDialog
from scripts.export_github_wiki import BUILTIN_LANGUAGES, build_pages, page_slug


def test_layer_and_accessory_guidance_is_translated_in_help_and_wiki(tmp_path):
    source = "Fit all enabled garments starts fresh setups at 100% Tightness and retains explicit Part and mesh-island choices. Cloth layers stay separate; recognized solid accessories and attached bows keep their shape. Use Rigid component for unrecognized hard details. Material names alone do not determine stiffness. Excluded surfaces do not affect fitting. Reset discards the preview; Bake keeps it."
    sources = (source, "At full Tightness, waistcloth follows the body's changing contour and flexible belts fit over the cloth. Set daggers and other hard pieces to Rigid component so they follow their fitted support without bending.")
    sources += ('Turned rims keep their original width while the cloth fits against the body and other layers. Matching material seams stay joined. Check all sides before Bake; conflicting pins can prevent a safe fit.',)
    sources += ('Refitting preserves smooth shading across texture and material seams without rounding intentional hard edges. It does not add polygons: coarse outlines and authored folds can remain angular. Incompatible shapes may still need manual mesh edits.',
                'Small caps can stay attached to a larger rigid accessory in the same Part when their island settings match. Different settings, body regions or protection masks keep islands independent.',)
    pages = build_pages()
    app = QApplication.instance() or QApplication([])
    builder = AboutDocumentationEnglishMixin()
    builder.settings_file_path = "CrimsonDesertModWorkbench.cfg"
    builder.archive = type("Archive", (), {"archive_cache_root": "workspace/cache"})()
    for language in BUILTIN_LANGUAGES:
        dialog = AboutDialog(None, title="Documentation", intro_html="", sections=builder._build_about_sections())
        localizer = UiLocalizer(language_dir=tmp_path / language.code, language_code=language.code)
        try:
            dialog.select_section("mesh_editor")
            localizer.apply(dialog)
            for source in sources:
                translated = localizer.translate(source)
                assert language.code == "en" or translated != source
                assert translated in dialog.browser.toPlainText()
                assert translated in pages[page_slug("Mesh-Editor", language.code) + ".md"]
        finally:
            localizer.shutdown()
            dialog.deleteLater()
            app.processEvents()
