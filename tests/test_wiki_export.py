from __future__ import annotations

import os
import re
from urllib.parse import unquote

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from scripts.export_github_wiki import (
    BUILTIN_LANGUAGES, PAGE_TOPICS, WIKI, DocumentParser, _blocks,
    _translate_html, build_pages, page_slug,
    build_manuals, manual_slug,
)


@pytest.fixture(scope="module")
def wiki_pages():
    return build_pages()


@pytest.fixture(scope="module")
def wiki_manuals(wiki_pages):
    return build_manuals(wiki_pages)


def test_manuals_have_one_native_named_page_per_language_and_18_guide_entries(wiki_manuals):
    assert len(wiki_manuals) == 17
    assert set(wiki_manuals) == {
        *(manual_slug(language.code) + ".md" for language in BUILTIN_LANGUAGES),
        "Languages.md", "_Sidebar.md", "_Footer.md",
    }
    assert "Deutsch.md" in wiki_manuals and "日本語.md" in wiki_manuals
    for language in BUILTIN_LANGUAGES:
        body = wiki_manuals[manual_slug(language.code) + ".md"]
        guides = re.findall(r'<a id="guide-([^"]+)"></a>', body)
        assert set(guides) == {page.lower() for page in PAGE_TOPICS}
        assert len(guides) == len(PAGE_TOPICS) == 18
        assert body.count("](#contents)") == 18
        assert "> [!WARNING]" in body and "> [!IMPORTANT]" in body
    assert "<details>" not in wiki_manuals["_Sidebar.md"]


def test_manual_links_resolve_to_the_reduced_page_set_and_unique_section_ids(wiki_manuals):
    for filename, body in wiki_manuals.items():
        anchors = re.findall(r'<a id="([^"]+)"></a>', body)
        assert len(anchors) == len(set(anchors)), filename
        for target in re.findall(r"\]\(([^)]+)\)", body):
            if target.startswith(WIKI):
                page, _, anchor = target[len(WIKI):].partition("#")
                destination = unquote(page) + ".md"
                assert destination in wiki_manuals, (filename, target)
                if anchor:
                    assert f'<a id="{anchor}"></a>' in wiki_manuals[destination], (filename, target)
            elif target.startswith("#"):
                assert target[1:] in anchors, (filename, target)


def test_consolidation_preserves_every_guides_visible_text(wiki_pages, wiki_manuals):
    def content_lines(text):
        lines = []
        for line in text.splitlines():
            if not line.strip() or line == "---" or line.startswith(("[⌂ ", "🌐 ", "CDMW `", "[↑ ")):
                continue
            line = re.sub(r"\]\([^)\n]+\)", "]", line)
            lines.append(re.sub(r"^#{1,6} ", "", line))
        return lines

    for language in BUILTIN_LANGUAGES:
        manual = wiki_manuals[manual_slug(language.code) + ".md"]
        sections = dict(re.findall(
            r'<a id="guide-([^"]+)"></a>\n\n## [^\n]+\n\n(.*?)(?=\n\n---\n\n(?:<a id="guide-|CDMW `))',
            manual, re.DOTALL,
        ))
        assert len(sections) == 18
        for page in PAGE_TOPICS:
            old = wiki_pages[page_slug(page, language.code) + ".md"].split("\n", 1)[1]
            assert content_lines(old) == content_lines(sections[page.lower()]), (language.code, page)


def test_manual_migration_requires_every_source_guide(wiki_pages):
    incomplete = dict(wiki_pages)
    del incomplete["Mesh-Editor-ja.md"]
    with pytest.raises(ValueError, match="Missing source Wiki guides: Mesh-Editor-ja.md"):
        build_manuals(incomplete)


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
    assert {file.name for file in folder.iterdir()} == set(build_manuals())
    monkeypatch.setattr("sys.argv", ["export_github_wiki.py", "--output", str(folder), "--check"])
    assert main() == 0
    (folder / "Home.md").write_text("stale", encoding="utf-8")
    assert main() == 1
    assert "Stale Wiki pages: Home.md" in capsys.readouterr().out


def test_migration_removes_only_known_legacy_pages_with_explicit_flag(tmp_path, monkeypatch, wiki_pages):
    from scripts.export_github_wiki import main

    source = tmp_path / "published"
    source.mkdir()
    for name, body in wiki_pages.items():
        (source / name).write_text(body, encoding="utf-8")
    output = tmp_path / "manuals"
    output.mkdir()
    obsolete = output / "Archive-Browser.md"
    obsolete.write_text("old generated guide", encoding="utf-8")
    unrelated = output / "Personal-notes.md"
    unrelated.write_text("keep this", encoding="utf-8")
    arguments = ["export_github_wiki.py", "--source-wiki", str(source), "--output", str(output)]
    monkeypatch.setattr("sys.argv", arguments)
    assert main() == 1
    assert obsolete.exists() and not (output / "Home.md").exists()
    monkeypatch.setattr("sys.argv", arguments + ["--replace-legacy"])
    assert main() == 0
    assert not obsolete.exists() and unrelated.read_text(encoding="utf-8") == "keep this"
    monkeypatch.setattr("sys.argv", arguments + ["--check"])
    assert main() == 0
    obsolete.write_text("unexpected old guide", encoding="utf-8")
    assert main() == 1


@pytest.mark.parametrize("language", BUILTIN_LANGUAGES, ids=lambda language: language.code)
def test_in_app_browser_renders_the_expanded_guides_in_each_locale(tmp_path, language):
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
        assert "_CDMW_VERTEX_ID" in dialog.browser.toPlainText()
    finally:
        localizer.shutdown()
        dialog.deleteLater()
        app.processEvents()
