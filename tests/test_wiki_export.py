from __future__ import annotations

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from scripts.export_github_wiki import (
    BUILTIN_LANGUAGES, PAGE_TOPICS, WIKI, DocumentParser, _blocks,
    _translate_html, build_pages, page_slug,
)


@pytest.fixture(scope="module")
def wiki_pages():
    return build_pages()


def test_all_14_locales_have_complete_guides_and_same_language_navigation(wiki_pages):
    assert len(BUILTIN_LANGUAGES) == 14
    assert len(wiki_pages) == 18 * 14 + 3
    for language in BUILTIN_LANGUAGES:
        for page in PAGE_TOPICS:
            name = page_slug(page, language.code)
            body = wiki_pages[name + ".md"]
            assert body.startswith("# ")
            assert f"({WIKI}{page_slug('Home', language.code)})" in body
            assert not re.search(r"[A-Z]:[\\/]", body.replace("https://", ""))
        item = wiki_pages[page_slug("Create-New-Item", language.code) + ".md"]
        mesh = wiki_pages[page_slug("Mesh-Editor", language.code) + ".md"]
        assert item.count('<a id="new_item_studio-') >= 8
        assert mesh.count('<a id="mesh_editor-') >= 13
        headings = re.findall(r"^#{2,3} (.+)$", mesh, re.MULTILINE)
        assert len(headings) == len(set(headings)), (language.code, headings)
        assert "> [!WARNING]" in item
        assert "> [!IMPORTANT]" in mesh
        assert "65" in item and ".cditem" in item
        assert "_CDMW_VERTEX_ID" in mesh and "CDMW_VERTEX_ID" in mesh
        assert '<a id="new_item_studio-7"></a>' in item
        assert '<a id="mesh_editor-10"></a>' in mesh


def test_all_page_links_and_explicit_section_anchors_resolve(wiki_pages):
    for filename, body in wiki_pages.items():
        for target in re.findall(r"\]\(([^)]+)\)", body):
            if target.startswith(WIKI):
                page, _, anchor = target[len(WIKI):].partition("#")
                assert page + ".md" in wiki_pages, (filename, target)
                if anchor:
                    assert f'<a id="{anchor}"></a>' in wiki_pages[page + ".md"], (filename, target)
            elif target.startswith("#"):
                assert f'<a id="{target[1:]}"></a>' in body, (filename, target)


def test_translated_prose_cannot_silently_fall_back_to_english():
    with pytest.raises(ValueError, match="Untranslated de documentation"):
        _translate_html("<p>This guide has untranslated prose.</p>", "de", {})


def test_html_conversion_preserves_tables_inline_spacing_and_topic_links():
    body = '<p>Use <b>Build Mod</b> next.</p><table><tr><th>Name</th><th>Link</th></tr><tr><td>A</td><td><a href="topic:mesh_editor">Mesh</a></td></tr></table>'
    rendered = _blocks(DocumentParser(body).root, "fr")
    assert "Use **Build Mod** next." in rendered
    assert "| Name | Link |\n| --- | --- |" in rendered
    assert f"({WIKI}Mesh-Editor-fr#mesh_editor)" in rendered


def test_export_output_stays_in_the_named_folder_and_check_detects_stale_page(tmp_path, monkeypatch, capsys):
    from scripts.export_github_wiki import main

    folder = tmp_path / "wiki"
    monkeypatch.setattr("sys.argv", ["export_github_wiki.py", "--output", str(folder)])
    assert main() == 0
    assert {file.name for file in folder.iterdir()} == set(build_pages())
    monkeypatch.setattr("sys.argv", ["export_github_wiki.py", "--output", str(folder), "--check"])
    assert main() == 0
    (folder / "Home.md").write_text("stale", encoding="utf-8")
    assert main() == 1
    assert "Stale Wiki pages: Home.md" in capsys.readouterr().out


@pytest.mark.parametrize("language", BUILTIN_LANGUAGES, ids=lambda language: language.code)
def test_in_app_browser_renders_the_expanded_guides_in_each_locale(tmp_path, language, wiki_pages):
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.localization import UiLocalizer
    from cdmw.ui.shell.about_documentation_en import AboutDocumentationEnglishMixin
    from cdmw.ui.shell.help_dialogs import AboutDialog

    app = QApplication.instance() or QApplication([])
    builder = AboutDocumentationEnglishMixin()
    builder.settings_file_path = "CrimsonDesertModWorkbench.cfg"
    builder.archive = type("Archive", (), {"archive_cache_root": "workspace/cache"})()
    sections = builder._build_about_sections()
    dialog = AboutDialog(None, title="Documentation", intro_html="", sections=sections)
    localizer = UiLocalizer(language_dir=tmp_path / language.code, language_code=language.code)
    try:
        dialog.select_section("contributing")
        localizer.apply(dialog)
        assert localizer.translate("Contributing") in dialog.browser.toPlainText()
        for topic in ("new_item_studio", "mesh_editor"):
            dialog.select_section(topic)
            localizer.apply(dialog)
            body = dialog.browser.toPlainText()
            source = "Drafts" if topic == "mesh_editor" else "Distribution"
            assert localizer.translate(source) in body
            source_paragraph = (
                "Draft recovery needs an associated project and matching source data. Keep the project descriptor, workspace manifest and saved generations together. A source mismatch refuses recovery. A recovered older generation is not proof that the latest edit or exported package was recovered."
                if topic == "mesh_editor" else
                "Start with a template from the same equipment family. Keep its original model for a first test, set a name, choose one supported shop route, then build a separate package. This checks identity and distribution before you add imported geometry, materials or effects."
            )
            assert localizer.translate(source_paragraph) in body
            if topic == "mesh_editor":
                hover_guide = "Open Parts on hover, beside Part colors in Morph & Refit, opens the Parts list when you hover a visible surface. Turn it off to keep closed panels closed; open lists still highlight and reveal matching names. Selection and pending fitting edits stay unchanged."
                translated = localizer.translate(hover_guide)
                assert translated in body
                assert translated in wiki_pages[page_slug("Mesh-Editor", language.code) + ".md"]
        assert "_CDMW_VERTEX_ID" in dialog.browser.toPlainText()
    finally:
        localizer.shutdown()
        dialog.deleteLater()
        app.processEvents()
