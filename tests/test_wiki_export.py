from __future__ import annotations

import os
import re
import html
from pathlib import Path
from urllib.parse import unquote

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from scripts.export_github_wiki import (
    BUILTIN_LANGUAGES, PAGE_TOPICS, WIKI, DocumentParser, _blocks,
    _translate_html, build_pages, page_slug,
    build_manuals, manual_path, manual_slug,
    _emphasize_controls, _readable_guide, _sentences,
)


@pytest.fixture(scope="module")
def wiki_pages():
    return build_pages()


@pytest.fixture(scope="module")
def wiki_manuals(wiki_pages):
    return build_manuals(wiki_pages)


def test_manuals_have_one_native_named_page_per_language_and_18_guide_entries(wiki_manuals):
    assert len(wiki_manuals) == 30
    assert set(wiki_manuals) == {
        *(manual_path(language.code) for language in BUILTIN_LANGUAGES),
        *(Path(manual_path(language.code)).with_name("_Sidebar.md").as_posix() for language in BUILTIN_LANGUAGES),
        "Languages.md", "_Sidebar.md", "_Footer.md",
    }
    assert "de/Deutsch.md" in wiki_manuals and "ja/日本語.md" in wiki_manuals
    for language in BUILTIN_LANGUAGES:
        body = wiki_manuals[manual_path(language.code)]
        guides = re.findall(r'<a id="guide-([^"]+)"></a>', body)
        assert set(guides) == {page.lower() for page in PAGE_TOPICS}
        assert len(guides) == len(PAGE_TOPICS) == 18
        assert body.count("](#contents)") == 18
        assert "> [!WARNING]" in body and "> [!IMPORTANT]" in body
    assert "<details>" not in wiki_manuals["_Sidebar.md"]


def test_each_manual_has_localized_contents_sidebar_and_opens_with_home(wiki_manuals):
    from scripts.export_github_wiki import load_builtin_catalog, manual_url

    for language in BUILTIN_LANGUAGES:
        path = manual_path(language.code)
        body = wiki_manuals[path]
        sidebar = wiki_manuals[Path(path).with_name("_Sidebar.md").as_posix()]
        translate = load_builtin_catalog(language.code)["translations"].get
        assert sidebar.startswith("### " + translate("Contents", "Contents"))
        assert f"[{translate('Start Here', 'Start Here')}]({manual_url(language.code, 'start-here')})" in sidebar
        assert f"[{translate('Overview', 'Overview')}]({manual_url(language.code, 'overview')})" in sidebar
        assert len(re.findall(r"\]\([^\n]+#guide-", sidebar)) == 18
        assert "/Languages" not in sidebar and "🌐" not in sidebar
        assert all(url.startswith(manual_url(language.code) + "#") for url in re.findall(r"\]\(([^)]+)\)", sidebar))
        assert re.search(r"^## (.+)$", body, re.MULTILINE)[1] == translate("Home", "Home")
        assert body.index("</details>") < body.index('<a id="guide-home"></a>')
        assert '<a id="start-here"></a>' in body
        assert f"[{language.display_name}]({manual_url(language.code)})" in wiki_manuals["Languages.md"]


def test_manual_links_resolve_to_the_reduced_page_set_and_unique_section_ids(wiki_manuals):
    public_pages = {Path(name).name: body for name, body in wiki_manuals.items() if Path(name).name != "_Sidebar.md"}
    for filename, body in wiki_manuals.items():
        anchors = re.findall(r'<a id="([^"]+)"></a>', body)
        assert len(anchors) == len(set(anchors)), filename
        for target in re.findall(r"\]\(([^)]+)\)", body):
            if target.startswith(WIKI):
                page, _, anchor = target[len(WIKI):].partition("#")
                destination = unquote(page) + ".md"
                assert destination in public_pages, (filename, target)
                if anchor:
                    assert f'<a id="{anchor}"></a>' in public_pages[destination], (filename, target)
            elif target.startswith("#"):
                assert target[1:] in anchors, (filename, target)


def test_consolidation_preserves_every_guides_visible_text(wiki_pages, wiki_manuals):
    def content_text(text):
        lines = []
        for line in text.splitlines():
            if not line.strip() or line == "---" or line.startswith(("[⌂ ", "🌐 ", "CDMW `", "[↑ ")) or re.fullmatch(r"\*\*[^*]+\*\*", line):
                continue
            line = re.sub(r"^> ?", "", line)
            if re.fullmatch(r"\[![A-Z]+\]", line) or re.fullmatch(r"\*\*(?:ℹ️|⚠️) [^*]+\*\*", line):
                continue
            line = re.sub(r"^(?:- |\d+\. )", "", line)
            line = re.sub(r"\]\([^)\n]+\)", "]", line)
            line = re.sub(r"<a id=\"[^\"]+\"></a>", "", line)
            line = re.sub(r"</?(?:details|summary|strong)>", "", line)
            lines.append(re.sub(r"^#{1,6} ", "", line).replace("**", ""))
        return re.sub(r"\s+", "", html.unescape("".join(lines)))

    for language in BUILTIN_LANGUAGES:
        manual = wiki_manuals[manual_path(language.code)]
        sections = dict(re.findall(
            r'<a id="guide-([^"]+)"></a>\n\n## [^\n]+\n\n(.*?)(?=\n\n---\n\n(?:<a id="guide-|CDMW `))',
            manual, re.DOTALL,
        ))
        assert len(sections) == 18
        for page in PAGE_TOPICS:
            old = wiki_pages[page_slug(page, language.code) + ".md"].split("\n", 1)[1]
            assert content_text(old) == content_text(sections[page.lower()]), (language.code, page)


def test_procedures_are_steps_with_separate_limits_and_optional_details(wiki_manuals):
    body = wiki_manuals["Home.md"]
    vertex = body.split('<a id="mesh_editor-5"></a>', 1)[1].split("</details>", 1)[0]
    assert "1. Open **Mesh Data** > **Vertex Parameters**" in vertex
    assert "1. Inspect **Position**, **UV Coordinates**, **Normals**, and **Skin Weights**" in vertex
    assert "- **Discard** clears pending inputs." in vertex
    assert "1. **Discard**" not in vertex
    assert "> **ℹ️ Info**\n>\n> - Editing depends" in vertex
    assert "[!NOTE]" not in vertex
    assert "UV1 and vertex colours are not editable." in vertex
    assert "<summary><strong>Vertex Parameters</strong></summary>" in body
    assert "<summary><strong>Authored cloth profiles</strong></summary>" in body
    assert "##### Do I need to install a DDS converter?" in body
    for language in BUILTIN_LANGUAGES:
        manual = wiki_manuals[manual_path(language.code)]
        assert manual.count("<details>") == manual.count("</details>")


def test_sentence_formatting_preserves_code_versions_ellipsis_and_cjk_punctuation():
    assert _sentences("Use Import Replacement... for the mesh. Keep `.cditem` v2. Reopen `mesh.pac`.") == [
        "Use Import Replacement... for the mesh.", "Keep `.cditem` v2.", "Reopen `mesh.pac`.",
    ]
    assert _sentences("変更を適用します。元のファイルを保持します。") == ["変更を適用します。", "元のファイルを保持します。"]
    with pytest.raises(ValueError, match="Documentation block structure differs: de"):
        _readable_guide("First.\n\nSecond.", "Zuerst.\n\nZweitens.\n\nDrittens.", "de")


def test_readable_guide_keeps_discard_separate_from_required_editing_steps():
    source = (
        '<a id="vertex"></a>\n\n## Vertex Parameters\n\n'
        'Open Mesh Data > Vertex Parameters and select vertices. '
        'Inspect Position, enter changes, then choose Apply. Discard clears pending inputs.\n\n'
        'Editing depends on the format. Unsupported channels remain read-only.'
    )
    rendered = _readable_guide(source, source, "en", mesh=True)
    assert rendered.startswith('<a id="vertex"></a>\n\n<details>')
    assert "1. Open **Mesh Data** > **Vertex Parameters**" in rendered
    assert "1. Inspect **Position**" in rendered
    assert "- **Discard** clears pending inputs." in rendered
    assert "1. **Discard**" not in rendered
    assert "> **ℹ️ Info**\n>\n> - Editing depends" in rendered


def test_existing_details_use_portable_localized_callouts():
    source = '<details>\n<summary>Advanced</summary>\n\nEditing depends on the format. Unsupported channels remain read-only.\n\n</details>'
    rendered = _readable_guide(source, source, "fr")
    assert "> **ℹ️ Informations**" in rendered
    assert "[!NOTE]" not in rendered


def test_korean_procedures_split_sentences_without_emphasizing_word_fragments(wiki_manuals):
    assert _sentences("변경을 적용하세요. 원본을 유지하세요.") == ["변경을 적용하세요.", "원본을 유지하세요."]
    assert _emphasize_controls("지원되는 원본을 유지하세요. 원 도구를 선택하세요.", "ko") == (
        "지원되는 원본을 유지하세요. **원** 도구를 선택하세요."
    )
    assert _emphasize_controls("정점 매개변수를 열고 적용을 선택하세요.", "ko") == (
        "**정점 매개변수**를 열고 **적용**을 선택하세요."
    )
    vertex = wiki_manuals["ko/한국어.md"].split('<a id="mesh_editor-5"></a>', 1)[1].split("</details>", 1)[0]
    assert vertex.count("\n1. ") == 2
    assert "지**원**" not in vertex


def test_adjacent_cjk_controls_share_one_emphasis(wiki_manuals):
    # Two control names with no space between them must not render literal asterisks.
    assert _emphasize_controls("出力設定を確認します。", "ja") == "**出力設定**を確認します。"
    assert _emphasize_controls("请确认**输出**设置。", "zh-Hans").count("****") == 0
    for name in ("ja/日本語.md", "zh-Hans/简体中文.md", "zh-Hant/繁體中文.md", "ko/한국어.md"):
        assert "****" not in wiki_manuals[name], name


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
    assert {file.relative_to(folder).as_posix() for file in folder.rglob("*.md")} == set(build_manuals())
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
    old_manual = output / "Deutsch.md"
    old_manual.write_text("old manual with shared sidebar", encoding="utf-8")
    unrelated = output / "Personal-notes.md"
    unrelated.write_text("keep this", encoding="utf-8")
    arguments = ["export_github_wiki.py", "--source-wiki", str(source), "--output", str(output)]
    monkeypatch.setattr("sys.argv", arguments)
    assert main() == 1
    assert obsolete.exists() and old_manual.exists() and not (output / "Home.md").exists()
    monkeypatch.setattr("sys.argv", arguments + ["--replace-legacy"])
    assert main() == 0
    assert not obsolete.exists() and unrelated.read_text(encoding="utf-8") == "keep this"
    assert not old_manual.exists() and (output / "de/Deutsch.md").exists()
    monkeypatch.setattr("sys.argv", arguments + ["--check"])
    assert main() == 0
    obsolete.write_text("unexpected old guide", encoding="utf-8")
    assert main() == 1


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
                for hover_guide in (
                    "Open Parts to find Part colors and Island colors above either list. These options also appear under Viewport > Display and work outside Morph & Refit. Matching swatches identify parts and islands; turn the active color option off to return to the normal display.",
                    "Island colors applies in Edit view and keeps selection, pending fitting edits, textures and exports unchanged. New local geometry stays gray until its island data updates.",
                    "Open Parts on hover is below the color options in Parts and is off by default. Enable it to open the list when hovering a visible surface; saved choices are retained. Open lists still highlight and reveal matching names while keeping the chosen Parts or Mesh islands tab. Selection and pending fitting edits stay unchanged.",
                    "Hover an island name in Mesh islands or Morph & Refit > Choose mesh islands to highlight only that island in the viewport. Hover a visible island in the viewport to highlight and reveal its name in the open lists. Move away to clear the highlight. Selection and pending fitting edits stay unchanged; hidden geometry stays hidden.",
                ):
                    translated = localizer.translate(hover_guide)
                    assert translated in body
                    assert translated in wiki_pages[page_slug("Mesh-Editor", language.code) + ".md"]
                output_guide = "Output, beside Finish Edit Mesh and at the top of Tools, shows the route Finish follows. Open it to switch between Exact and Free Edit, choose a Free Edit package folder, or open a package in CDMW."
                translated = localizer.translate(output_guide)
                assert translated != output_guide or language.code == "en"
                assert translated in body
                assert translated in wiki_pages[page_slug("Mesh-Editor", language.code) + ".md"]
            if topic == "new_item_studio":
                definition_guide = "Extended item definition groups text and knowledge, linked items and bundles, flags, equipment and sharpness, presentation, and world/economy fields. Load definition references, select a field and check Override selected field. Edit Value; select lists to add entries or select rows to remove them. Uncheck to inherit; an overridden empty list clears. Secondary descriptions need a source item with an existing secondary description; language overrides fall back to English or source text. These settings require item.definition version 1 and preserve earlier packages. Missing or ambiguous references refuse. Raw selectors, money identifiers, routing, respawn units and game/save effects remain unverified."
                translated = localizer.translate(definition_guide)
                assert translated in body
                assert translated in wiki_pages[page_slug("Create-New-Item", language.code) + ".md"]
                if language.code != "en": assert translated != definition_guide
        assert "_CDMW_VERTEX_ID" in dialog.browser.toPlainText()
        dialog.select_section('new_item_studio')
        localizer.apply(dialog)
        import json
        english=json.loads((Path(__file__).resolve().parents[1]/'cdmw/resources/localization/en.json').read_text(encoding='utf-8'))['translations']
        for prefix in ('Additional item behavior covers classification,','Write stock item package exports the current combat'):
            guide=next(key for key in english if key.startswith(prefix))
            translated=localizer.translate(guide)
            assert translated in dialog.browser.toPlainText()
            assert translated in wiki_pages[page_slug('Create-New-Item',language.code)+'.md']
            if language.code!='en': assert translated!=guide
    finally:
        localizer.shutdown()
        dialog.deleteLater()
        app.processEvents()
