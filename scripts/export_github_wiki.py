"""Export the in-app guides to a multilingual GitHub Wiki without publishing."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cdmw.constants import APP_VERSION
from cdmw.domain.localization import BUILTIN_LANGUAGES
from cdmw.ui.localization import _translate_html_text
from cdmw.ui.localization_catalogs_v2 import load_builtin_catalog
from cdmw.ui.shell.about_documentation_en import AboutDocumentationEnglishMixin
from cdmw.ui.shell.compact.registry import COMPACT_TOOL_SPECS

WIKI = "https://github.com/Ratty123/CDMW-Full/wiki/"
REPOSITORY = "https://github.com/Ratty123/CDMW-Full"
PAGE_TOPICS = {
    "Home": ("overview", "safety"),
    "Getting-Started": ("first_run_checklist",),
    "Tools-and-Navigation": ("documentation_index",),
    "Archive-Browser": ("archive_browser", "archive_guides"),
    "Create-New-Item": ("new_item_studio",),
    "Mesh-Editor": ("mesh_editor",),
    "Textures": (
        "workflow_overview", "texture_workflow_guides", "texture_editor",
        "replace_assistant", "texture_recolor", "compare_review",
        "workflow_profiles", "workflow_rules", "workflow_matched_files",
        "dds_output", "upscaling_backends", "workflow_planner_profiles",
        "workflow_planner_paths",
    ),
    "Placement-and-Animations": ("placement_studio",),
    "Model-Library": ("model_library",),
    "Item-Icons": ("icon_creator",),
    "Mod-Management": ("mod_management", "mod_package_retrofit", "mod_packaging"),
    "Independent-Item-Packages": (),
    "Translations-and-Text-Search": ("translation_studio", "text_search"),
    "Formats-and-Research": ("format_explorer", "research"),
    "Settings-and-Profiles": ("profile_settings", "window_layout"),
    "Troubleshooting-and-Reporting": ("troubleshooting",),
    "FAQ": ("faq",),
    "Contributing": ("contributing",),
}
TOPIC_PAGE = {topic: page for page, topics in PAGE_TOPICS.items() for topic in topics}
TOPIC_PAGE["settings_files"] = "Settings-and-Profiles"
PAGE_REFERENCES = {
    "Getting-Started": ("README.md#install",),
    "Archive-Browser": ("cdmw/ui/archive_browser/README.md",),
    "Create-New-Item": ("cdmw/ui/new_item/README.md",),
    "Mesh-Editor": ("cdmw/ui/mesh_editor/README.md", "cdmw/ui/mesh_editor/SHADER_CONTROLS.md"),
    "Textures": ("cdmw/ui/texture_workflow/README.md", "cdmw/ui/replace_assistant/README.md"),
    "Placement-and-Animations": ("README.md#placement--animations",),
    "Model-Library": ("cdmw/ui/model_library/README.md",),
    "Item-Icons": ("cdmw/ui/item_icons/README.md",),
    "Mod-Management": ("cdmw/ui/new_item/README.md#output-review-and-mod-management",),
    "Independent-Item-Packages": (
        "cdmw/ui/new_item/INDEPENDENT_ITEMS.md", "cdmw/ui/new_item/VIRTUAL_LOADER.md",
        "cdmw/services/INDEPENDENT_TEXTURES.md",
    ),
    "Translations-and-Text-Search": ("cdmw/ui/text_search/README.md",),
    "Formats-and-Research": (
        "docs/crimson-desert-research.md", "schemas/archive_content_capabilities.v1.json",
    ),
    "Troubleshooting-and-Reporting": ("README.md#privacy-and-support", "SECURITY.md"),
}
MANUAL_GROUPS = (
    ("Start Here", ("Home", "Getting-Started", "Tools-and-Navigation", "FAQ")),
    ("Assets", ("Archive-Browser", "Create-New-Item", "Model-Library", "Item-Icons")),
    ("Authoring", ("Mesh-Editor", "Placement-and-Animations", "Textures")),
    ("Utilities", ("Mod-Management", "Independent-Item-Packages", "Translations-and-Text-Search", "Formats-and-Research")),
    ("Help", ("Settings-and-Profiles", "Troubleshooting-and-Reporting", "Contributing")),
)


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node | str"] = field(default_factory=list)


class DocumentParser(HTMLParser):
    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(text)
        if len(self.stack) != 1:
            raise ValueError("Unclosed documentation HTML")

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {"br", "hr", "img", "input", "meta", "link"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if tag in {"br", "hr", "img", "input", "meta", "link"}:
            return
        if len(self.stack) == 1 or self.stack[-1].tag != tag:
            raise ValueError(f"Mismatched documentation HTML: {tag}")
        self.stack.pop()

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def page_slug(page: str, locale: str) -> str:
    return page if locale == "en" else f"{page}-{locale}"


def page_url(page: str, locale: str, anchor: str = "") -> str:
    return WIKI + page_slug(page, locale) + ("#" + anchor if anchor else "")


def _inline(node: Node | str, locale: str) -> str:
    if isinstance(node, str):
        return re.sub(r"\s+", " ", node)
    body = "".join(_inline(child, locale) for child in node.children)
    if node.tag in {"b", "strong"}:
        return f"**{body.strip()}**"
    if node.tag in {"i", "em"}:
        return f"*{body.strip()}*"
    if node.tag == "code":
        return f"`{body.strip()}`"
    if node.tag == "a":
        target = node.attrs.get("href", "")
        if target.startswith("topic:"):
            topic = target[6:]
            if topic not in TOPIC_PAGE:
                raise ValueError(f"Unmapped documentation topic: {topic}")
            anchor = "" if topic == "documentation_index" else "profile_settings" if topic == "settings_files" else topic
            target = page_url(TOPIC_PAGE[topic], locale, anchor)
        return f"[{body.strip()}]({target})"
    if node.tag == "br":
        return " "
    return body


def _blocks(node: Node, locale: str, *, heading_level: int = 3) -> str:
    blocks = []
    for child in node.children:
        if isinstance(child, str):
            if child.strip():
                blocks.append(child.strip())
            continue
        if child.tag in {"p", "h4", "h3", "h2", "h1"}:
            prefix = "#" * heading_level + " " if child.tag.startswith("h") else ""
            body = prefix + _inline(child, locale).strip()
            if child.attrs.get("id"):
                body = f'<a id="{child.attrs["id"]}"></a>\n\n' + body
            if child.attrs.get("data-alert"):
                body = f'> [!{child.attrs["data-alert"]}]\n> ' + body
            blocks.append(body)
        elif child.tag in {"ul", "ol"}:
            items = []
            for item in child.children:
                if isinstance(item, Node) and item.tag == "li":
                    prefix = "1. " if child.tag == "ol" else "- "
                    items.append(prefix + _inline(item, locale).strip())
            blocks.append("\n".join(items))
        elif child.tag == "table":
            rows = []
            for row in child.children:
                if isinstance(row, Node) and row.tag in {"thead", "tbody"}:
                    row_nodes = row.children
                else:
                    row_nodes = [row]
                for row_node in row_nodes:
                    if not isinstance(row_node, Node) or row_node.tag != "tr":
                        continue
                    cells = [
                        _inline(cell, locale).strip().replace("|", "\\|")
                        for cell in row_node.children
                        if isinstance(cell, Node) and cell.tag in {"td", "th"}
                    ]
                    rows.append(cells)
            if rows:
                if any(len(row) != len(rows[0]) for row in rows):
                    raise ValueError("Uneven documentation table")
                rows.insert(1, ["---"] * len(rows[0]))
                blocks.append("\n".join("| " + " | ".join(row) + " |" for row in rows))
        elif child.tag in {"div", "section"}:
            if "doc-callout" in child.attrs.get("class", ""):
                kind = "WARNING" if "doc-warning" in child.attrs.get("class", "") else "NOTE"
                blocks.append(f"> [!{kind}]\n> " + _inline(child, locale).strip())
            else:
                blocks.append(_blocks(child, locale, heading_level=heading_level))
        else:
            raise ValueError(f"Unsupported documentation block: {child.tag}")
    return "\n\n".join(block for block in blocks if block)


def _translate_html(body: str, locale: str, translations: dict) -> str:
    def translate(source: str) -> str:
        value = translations.get(source, source)
        if not isinstance(value, str):
            raise ValueError(f"Unexpected plural in documentation: {source}")
        if locale != "en" and value == source and len(source.split()) > 3:
            raise ValueError(f"Untranslated {locale} documentation: {source}")
        return value
    return _translate_html_text(body, translate)


def _title(page: str, sections: dict, translate) -> str:
    if page == "Home":
        return "Crimson Desert Mod Workbench · " + translate("Documentation")
    if page == "Independent-Item-Packages":
        return translate("Independent items")
    if page == "Translations-and-Text-Search":
        return translate("Translations") + " / " + translate("Text Search")
    if page == "Formats-and-Research":
        return translate("Format Explorer") + " / " + translate("Research")
    topics = PAGE_TOPICS[page]
    return translate(sections[topics[0]]["title"])


def build_pages() -> dict[str, str]:
    """Render individual guides in memory for manual composition and migration."""
    builder = AboutDocumentationEnglishMixin()
    builder.settings_file_path = "CrimsonDesertModWorkbench.cfg"
    builder.archive = type("DocumentationArchive", (), {"archive_cache_root": "workspace/cache"})()
    sections = {section["id"]: section for section in builder._build_about_sections()}
    result = {}
    source_fingerprint = hashlib.sha256(
        (ROOT / "cdmw/ui/shell/about_documentation_en.py").read_bytes()
    ).hexdigest()[:12]
    for language in BUILTIN_LANGUAGES:
        locale = language.code
        translations = load_builtin_catalog(locale)["translations"]
        translate = lambda text: str(translations.get(text, text))
        for page, topics in PAGE_TOPICS.items():
            language_bar = "🌐 " + " · ".join(
                f"[{entry.display_name}]({page_url(page, entry.code)})"
                for entry in BUILTIN_LANGUAGES
            )
            title = _title(page, sections, translate)
            parts = [
                f"# {title}",
                f"[⌂ {translate('Home')}]({page_url('Home', locale)}) · "
                f"[☰ {translate('Documentation Index')}]({page_url('Tools-and-Navigation', locale)}) · "
                f"[🌐 {translate('Language')}]({WIKI}Languages)",
            ]
            if page == "Home":
                parts.extend([
                    language_bar,
                    f"[⬇ {translate('Download')}]({REPOSITORY}/releases) · "
                    f"[{translate('Source')}]({REPOSITORY}) · "
                    f"[CHANGELOG.md]({REPOSITORY}/blob/main/CHANGELOG.md)",
                    "## " + translate("Start Here") + "\n\n" + " · ".join(
                        f"[{_title(target, sections, translate)}]({page_url(target, locale)})"
                        for target in ("Getting-Started", "Create-New-Item", "Mesh-Editor")
                    ),
                ])
            if page == "Tools-and-Navigation":
                rows = [f"| {translate('Name')} | {translate('Path')} |", "|---|---|"]
                for spec in COMPACT_TOOL_SPECS:
                    topic = spec.key if spec.key in TOPIC_PAGE else {
                        "new_item_studio": "new_item_studio", "item_icons": "icon_creator",
                        "textures": "workflow_overview", "translation_studio": "translation_studio",
                    }.get(spec.key, spec.key)
                    target = TOPIC_PAGE[topic]
                    rows.append(f"| [{translate(spec.label)}]({page_url(target, locale)}) | {translate(spec.category)} > {translate(spec.label)} |")
                parts.append("\n".join(rows))
            visible_topics = [topic for topic in topics if sections[topic]["html"].strip()]
            if len(visible_topics) > 1 and page != "Home":
                topic_links = "\n".join(
                    f"- [{translate(sections[topic]['title'])}](#{topic})" for topic in visible_topics
                )
                parts.append(f'<details>\n<summary>{html.escape(translate("Documentation Index"))}</summary>\n\n{topic_links}\n\n</details>')
            for topic in visible_topics:
                section = sections[topic]
                body = _translate_html(section["html"], locale, translations)
                parsed = DocumentParser(body).root
                if topic == "overview":
                    # The Help search field is outside the article in CDMW.
                    # Wiki navigation replaces that first, app-specific paragraph.
                    first_paragraph = next(node for node in parsed.children if isinstance(node, Node) and node.tag == "p")
                    parsed.children.remove(first_paragraph)
                    for node in parsed.children:
                        if isinstance(node, Node) and node.tag == "p" and "source build" in section["html"]:
                            if _inline(node, locale).strip() == translations.get(
                                "Documentation follows the source build it describes. Published releases and development builds can differ; check the release notes when controls or output options differ from your installed version.",
                                "Documentation follows the source build it describes. Published releases and development builds can differ; check the release notes when controls or output options differ from your installed version.",
                            ):
                                node.attrs["data-alert"] = "NOTE"
                if page in {"Create-New-Item", "Mesh-Editor"}:
                    entries = []
                    for index, node in enumerate(child for child in parsed.children if isinstance(child, Node) and child.tag == "h4"):
                        node.attrs["id"] = f"{topic}-{index + 1}"
                        entries.append(f'- [{_inline(node, locale)}](#{node.attrs["id"]})')
                    if entries:
                        parts.append(f'<details>\n<summary>{html.escape(translate("Documentation Index"))}</summary>\n\n' + "\n".join(entries) + "\n\n</details>")
                    alert_prefix = "Mod folder supports" if page == "Create-New-Item" else "Finish accepts"
                    original_paragraphs = [text for text in re.findall(r"<p>(.*?)</p>", section["html"], re.S) if text.startswith(alert_prefix)]
                    if len(original_paragraphs) != 1:
                        raise ValueError("Core guide alert paragraph is missing")
                    alert_text = _translate_html(original_paragraphs[0], locale, translations)
                    for node in parsed.children:
                        if isinstance(node, Node) and node.tag == "p" and _inline(node, locale).strip() == html.unescape(alert_text).strip():
                            node.attrs["data-alert"] = "WARNING" if page == "Create-New-Item" else "IMPORTANT"
                markdown = _blocks(parsed, locale, heading_level=2 if len(visible_topics) == 1 else 3)
                heading = f'<a id="{topic}"></a>'
                if len(visible_topics) != 1:
                    heading += f'\n\n## {translate(section["title"])}'
                if page == "Textures" and topic in {
                    "workflow_profiles", "workflow_rules", "workflow_matched_files",
                    "dds_output", "upscaling_backends", "workflow_planner_profiles", "workflow_planner_paths",
                }:
                    parts.append(f'{heading}\n\n<details>\n<summary>{html.escape(translate(section["title"]))}</summary>\n\n{markdown}\n\n</details>')
                else:
                    parts.extend([heading, markdown])
            if page == "Independent-Item-Packages":
                source = sections["new_item_studio"]["html"]
                paragraphs = re.findall(r"<p>(.*?)</p>", source, re.S)
                selected = [text for text in paragraphs if text.startswith((
                    "Independent item package writes", "Use the player-facing name", "Add to existing mod deliberately",
                ))]
                if len(selected) != 3:
                    raise ValueError("Independent package guide paragraphs are missing")
                parts.append(_blocks(DocumentParser(_translate_html(
                    "".join(f"<p>{text}</p>" for text in selected), locale, translations
                )).root, locale))
            references = PAGE_REFERENCES.get(page, ())
            if page in {"Home", "Tools-and-Navigation"}:
                parts.extend([
                    "## " + translate("Documentation Index"),
                    "\n".join(
                        f"- [{_title(target, sections, translate)}]({page_url(target, locale)})"
                        for target in PAGE_TOPICS if target != page
                    ),
                ])
            if references:
                parts.append("### " + translate("References"))
                parts.append("\n".join(
                    f"- [{Path(ref.split('#')[0]).name}]({REPOSITORY}/blob/main/{ref})"
                    for ref in references
                ))
            parts.append(f"---\n\nCDMW `{APP_VERSION}` · `{source_fingerprint}` · {language_bar}")
            result[page_slug(page, locale) + ".md"] = "\n\n".join(parts) + "\n"
    result["Languages.md"] = "# 🌐 Languages\n\n" + "\n".join(
        f"- [{language.display_name}]({page_url('Home', language.code)})"
        for language in BUILTIN_LANGUAGES
    ) + "\n"
    sidebar = [f"**[CDMW Full Wiki]({WIKI}Home)**", f"[🌐 Languages]({WIKI}Languages)"]
    for language in BUILTIN_LANGUAGES:
        catalogue = load_builtin_catalog(language.code)["translations"]
        translate = lambda text: str(catalogue.get(text, text))
        links = "\n".join(
            f"- [{_title(page, sections, translate)}]({page_url(page, language.code)})"
            for page in PAGE_TOPICS
        )
        sidebar.append(f"<details>\n<summary>{language.display_name}</summary>\n\n{links}\n\n</details>")
    result["_Sidebar.md"] = "\n\n".join(sidebar) + "\n"
    result["_Footer.md"] = f"[CDMW Full]({REPOSITORY}) · [🌐 Languages]({WIKI}Languages) · `{APP_VERSION}`\n"
    return result


def manual_slug(locale: str) -> str:
    language = next(entry for entry in BUILTIN_LANGUAGES if entry.code == locale)
    return "Home" if locale == "en" else language.display_name.replace(" ", "-")


def manual_url(locale: str, anchor: str = "") -> str:
    return WIKI + quote(manual_slug(locale), safe="-") + ("#" + anchor if anchor else "")


def _guide_body(markdown: str) -> str:
    body = markdown.split("\n", 1)[1].strip()
    body = re.sub(r"\A\[⌂ [^\n]+\n\n", "", body, count=1)
    body = re.sub(r"\A🌐 [^\n]+\n\n", "", body, count=1)
    return re.sub(r"\n\n---\n\nCDMW [^\n]+\Z", "", body)


def build_manuals(guides: dict[str, str] | None = None) -> dict[str, str]:
    """Consolidate all guide content into one native-named manual per locale."""
    if guides is None:
        guides = build_pages()
    targets = {
        page_slug(page, language.code): (language.code, page)
        for language in BUILTIN_LANGUAGES for page in PAGE_TOPICS
    }
    missing = sorted(name + ".md" for name in targets if name + ".md" not in guides)
    if missing:
        raise ValueError("Missing source Wiki guides: " + ", ".join(missing))

    def rewrite_link(match):
        target, _, anchor = match[1][len(WIKI):].partition("#")
        if target not in targets:
            return match[0]
        locale, page = targets[target]
        return "](" + manual_url(locale, anchor or "guide-" + page.lower()) + ")"

    result = {}
    order = [page for _, pages in MANUAL_GROUPS for page in pages]
    for language in BUILTIN_LANGUAGES:
        locale = language.code
        catalogue = load_builtin_catalog(locale)["translations"]
        translate = lambda text: str(catalogue.get(text, text))
        home = guides[page_slug("Home", locale) + ".md"]
        titles = {
            page: translate("Home") if page == "Home" else guides[page_slug(page, locale) + ".md"].splitlines()[0][2:]
            for page in PAGE_TOPICS
        }
        provenance = re.search(r"^CDMW `[^`]+` · `[^`]+`", home, re.MULTILINE)
        if provenance is None:
            raise ValueError("Missing documentation provenance: " + locale)
        parts = [
            home.splitlines()[0],
            f"**{language.display_name}** · [🌐 {translate('Language')}]({WIKI}Languages)",
            '<a id="contents"></a>\n\n## ' + translate("Contents"),
        ]
        for group, pages in MANUAL_GROUPS:
            parts.extend([
                "**" + translate(group) + "**",
                "\n".join(f"- [{titles[page]}](#guide-{page.lower()})" for page in pages),
            ])
        for page in order:
            body = _guide_body(guides[page_slug(page, locale) + ".md"])
            body = re.sub(r"(?m)^(#{1,5}) ", r"#\1 ", body)
            body = re.sub(r"\]\((" + re.escape(WIKI) + r"[^)\n]+)\)", rewrite_link, body)
            parts.extend([
                '---\n\n<a id="guide-' + page.lower() + '"></a>\n\n## ' + titles[page],
                body,
                f"[↑ {translate('Contents')}](#contents)",
            ])
        parts.append("---\n\n" + provenance[0])
        result[manual_slug(locale) + ".md"] = "\n\n".join(parts) + "\n"
    languages = "\n".join(
        f"- [{language.display_name}]({manual_url(language.code, 'contents')})"
        for language in BUILTIN_LANGUAGES
    )
    result["Languages.md"] = "# 🌐 Languages\n\n" + languages + "\n"
    result["_Sidebar.md"] = (
        f"**[CDMW Full Wiki]({WIKI}Home)**\n\n[🌐 Languages]({WIKI}Languages)\n\n" + languages + "\n"
    )
    result["_Footer.md"] = guides["_Footer.md"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Explicit local Wiki checkout or draft folder.")
    parser.add_argument("--check", action="store_true", help="Check existing pages without writing them.")
    parser.add_argument("--source-wiki", type=Path, help="Preserve guides from an existing pre-manual Wiki checkout instead of regenerating prose.")
    parser.add_argument("--replace-legacy", action="store_true", help="Remove only obsolete generated guide files after writing the manuals.")
    args = parser.parse_args()
    legacy_names = {
        page_slug(page, language.code) + ".md"
        for page in PAGE_TOPICS for language in BUILTIN_LANGUAGES
    } | {"Languages.md", "_Sidebar.md", "_Footer.md"}
    guides = None if args.source_wiki is None else {
        name: (args.source_wiki / name).read_text(encoding="utf-8") for name in legacy_names
    }
    pages = build_manuals(guides)
    output = args.output.resolve()
    obsolete = sorted(name for name in legacy_names - pages.keys() if (output / name).is_file())
    if args.check:
        stale = [name for name, body in pages.items() if not (output / name).is_file() or (output / name).read_text(encoding="utf-8") != body]
        if stale or obsolete:
            if stale:
                print("Stale Wiki pages: " + ", ".join(stale))
            if obsolete:
                print("Obsolete Wiki guide files: " + ", ".join(obsolete))
            return 1
    else:
        if obsolete and not args.replace_legacy:
            print("Legacy guide files remain; use --replace-legacy to consolidate this checkout.")
            return 1
        output.mkdir(parents=True, exist_ok=True)
        for name, body in pages.items():
            (output / name).write_text(body, encoding="utf-8", newline="\n")
        for name in obsolete:
            (output / name).unlink()
    print(f"{'Checked' if args.check else 'Exported'} {len(pages)} Wiki files across {len(BUILTIN_LANGUAGES)} locales. No publication performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
