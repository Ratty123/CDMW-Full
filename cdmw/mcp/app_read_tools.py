"""Read tools for what the interface itself shows: Settings > Shortcuts, Help, the Textures panel.

Each reads the same source as its screen and changes nothing:

* ``app.shortcuts``: the rows of Settings > Shortcuts (``keymap.keymap_rows``) with
  their clashes (``keymap.conflicts``), the Mesh Editor's commands included;
* ``app.manual``: the Help topics, the source of the GitHub Wiki manual that
  Help > Documentation opens, as plain text;
* ``textures.list``: the Mesh Editor's Textures panel for the shown tab, built
  from that session's manifest by ``textures_panel.texture_rows_from_manifest``,
  whether the panel is shown or not. The panel is neither built nor shown.
"""

from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path

from cdmw.mcp.errors import NOT_FOUND, UNAVAILABLE, ToolError
from cdmw.mcp.names import READ
from cdmw.mcp.tools import ON_UI, ON_WORKER, Tool, object_schema

MAX_MANUAL_CHARS = 100_000
NO_MESH = "Open a mesh in the Mesh Editor first: the Textures panel lists the textures of the shown tab."


# ----- Settings > Shortcuts ---------------------------------------------------------
def _shortcuts(call) -> dict[str, object]:
    from cdmw.ui.commands.keymap import conflicts, keymap_rows

    registry = call.context.command_registry()
    settings = getattr(call.context, "settings", None)
    if registry is None or settings is None:
        return {"shortcuts": []}
    rows = keymap_rows(registry, settings)
    clashes = conflicts(rows)
    a = call.arguments
    wanted = str(a.get("context") or "")
    words = str(a.get("query") or "").casefold().split()
    result = []
    for row in rows:
        if wanted and row.context != wanted:
            continue
        text = f"{row.label} {row.command_id} {' '.join(row.keys)}".casefold()
        if words and not all(word in text for word in words):
            continue
        if a.get("conflicts_only") and row.command_id not in clashes:
            continue
        if a.get("changed_only") and not row.changed:
            continue
        result.append({"command": row.command_id, "label": row.label, "context": row.context,
                       "keys": list(row.keys), "default_keys": list(row.defaults), "changed": row.changed,
                       "clashes_with": sorted(set(clashes.get(row.command_id, ())))})
    return {"shortcuts": result}


# ----- Help ----------------------------------------------------------------------------
class _TextOf:
    _BLOCK = re.compile(r"<\s*(?:br|/p|/li|/h\d|/tr|/ol|/ul|/div|/table)\b[^>]*>", re.IGNORECASE)
    _ITEM = re.compile(r"<\s*li\b[^>]*>", re.IGNORECASE)
    _TAG = re.compile(r"<[^>]+>")

    @classmethod
    def of(cls, markup: str) -> str:
        text = cls._ITEM.sub("\n- ", str(markup or ""))
        text = cls._BLOCK.sub("\n", text)
        text = html.unescape(cls._TAG.sub("", text))
        lines = [" ".join(line.split()) for line in text.splitlines()]
        return "\n".join(line for line in lines if line).strip()


@lru_cache(maxsize=1)
def _topics() -> tuple[dict[str, str], ...]:
    """Help's topics, built as the Wiki export builds them (``scripts/export_github_wiki.py``)."""

    from cdmw.ui.shell.about_documentation_en import AboutDocumentationEnglishMixin

    builder = AboutDocumentationEnglishMixin()
    builder.settings_file_path = "CrimsonDesertModWorkbench.cfg"
    builder.archive = type("DocumentationArchive", (), {"archive_cache_root": "workspace/cache"})()
    return tuple({"id": str(section.get("id") or ""), "title": str(section.get("title") or ""),
                  "summary": str(section.get("summary") or ""), "keywords": str(section.get("keywords") or ""),
                  "text": _TextOf.of(section.get("html") or "")}
                 for section in builder._build_about_sections())


def _manual(call) -> dict[str, object]:
    from cdmw.ui.shell.wiki_links import documentation_url

    a = call.arguments
    topics = _topics()
    wanted = str(a.get("topic") or "").strip()
    if wanted:
        topic = next((t for t in topics if t["id"] == wanted), None)
        if topic is None:
            raise ToolError(NOT_FOUND, f"Help has no topic {wanted}. Call app_manual without a topic for the list.")
        limit = int(a.get("max_characters") or MAX_MANUAL_CHARS)
        return {"id": topic["id"], "title": topic["title"], "summary": topic["summary"],
                "url": documentation_url("en", topic["id"]), "text": topic["text"][:limit],
                "characters": len(topic["text"]), "truncated": len(topic["text"]) > limit}
    words = str(a.get("query") or "").casefold().split()
    rows = []
    for topic in topics:
        haystack = " ".join((topic["title"], topic["summary"], topic["keywords"], topic["text"])).casefold()
        if words and not all(word in haystack for word in words):
            continue
        rows.append({"id": topic["id"], "title": topic["title"], "summary": topic["summary"],
                     "url": documentation_url("en", topic["id"])})
    return {"topics": rows}


# ----- the Mesh Editor's Textures panel ----------------------------------------------------
def _shown_session_root(context) -> str:
    """On the UI thread: the session folder of the Mesh Editor tab that is shown, or ""."""

    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    shell = getattr(getattr(context, "window", None), "shell", None)
    view = created_tool_widget(getattr(shell, "mesh_editor_tab", None))  # None until the tab is built
    if view is None:
        return ""
    tab = getattr(view, "active", None) or view
    root = getattr(tab, "standalone_rust_session_root", None)
    return str(root) if root else ""


def _textures(call) -> dict[str, object]:
    from cdmw.ui.mesh_editor.textures_panel import (
        contributing_rows,
        made_from_several_files,
        texture_role_label,
        texture_rows_from_manifest,
    )

    root = call.context.ui_call(lambda: _shown_session_root(call.context))
    if not root:
        raise ToolError(UNAVAILABLE, NO_MESH)
    try:
        manifest = json.loads((Path(root) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ToolError(UNAVAILABLE, "The Mesh Editor is still preparing this mesh; try again in a moment.") from None
    if not isinstance(manifest, dict):
        raise ToolError(UNAVAILABLE, NO_MESH)
    parts = []
    for group in texture_rows_from_manifest(manifest, session_root=root):
        parts.append({
            "part_index": group.part_index, "part": group.part_name, "source_file": group.source_file,
            "textures": [{"role": row.role, "role_label": texture_role_label(row.role), "game_path": row.game_path,
                          "file_name": row.file_name, "shared": row.shared,
                          # A colour CDMW made from several files: no game file of its own.
                          "not_one_file": made_from_several_files(row),
                          "made_from": [other.game_path for other in contributing_rows(group, row)],
                          "session_file": row.decoded_path}
                         for row in group.rows]})
    return {"parts": parts, "session": root}


def app_read_tools() -> list[Tool]:
    from cdmw.ui.commands.registry import CONTEXTS

    return [
        Tool(name="app.shortcuts", family="app", title="Shortcuts",
             description="Settings > Shortcuts as a list: every command of every tool (the Mesh Editor's and the "
                         "Texture Editor's included) with its keys now, its default keys, whether it was changed, "
                         "and the commands it clashes with.",
             input_schema=object_schema({"context": {"type": "string", "enum": ["", *CONTEXTS]},
                                         "query": {"type": "string", "maxLength": 128},
                                         "conflicts_only": {"type": "boolean"},
                                         "changed_only": {"type": "boolean"}}),
             effect=READ, route="service:ui.commands.keymap.keymap_rows+conflicts", handler=_shortcuts,
             runs_on=ON_UI, paged="shortcuts"),
        Tool(name="app.manual", family="app", title="Help",
             description="CDMW's Help, the manual Help > Documentation opens on the GitHub Wiki: without arguments "
                         "the list of topics, with query the topics that hold every word, with topic one topic's "
                         "text and its Wiki address.",
             input_schema=object_schema({"topic": {"type": "string", "maxLength": 128},
                                         "query": {"type": "string", "maxLength": 256},
                                         "max_characters": {"type": "integer", "minimum": 1,
                                                            "maximum": MAX_MANUAL_CHARS,
                                                            "default": MAX_MANUAL_CHARS}}),
             effect=READ, route="service:ui.shell.about_documentation_en._build_about_sections",
             handler=_manual, runs_on=ON_WORKER, paged="topics"),
        Tool(name="textures.list", family="textures", title="Textures panel",
             description="The Mesh Editor's Textures panel for the tab that is shown: each part with its textures, "
                         "their role, game file, whether other parts share it, and for a colour CDMW made from "
                         "several files the files it is made from. The panel need not be shown.",
             input_schema=object_schema(), effect=READ,
             route="service:ui.mesh_editor.textures_panel.texture_rows_from_manifest", handler=_textures,
             runs_on=ON_WORKER, paged="parts"),
    ]


__all__ = ["app_read_tools"]
