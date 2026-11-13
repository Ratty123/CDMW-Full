"""The read-only tool families (P13 stage C, design record 2.3).

Every tool here changes nothing. Each reaches the service the interface uses
for the same question: the archive catalogue (through the context, which
submits on the UI thread and waits on the tool's thread), the archive
readers, the Model Library's catalogue, the saved work index, the Format
Explorer's manifest, the game table decoder and the localisation tables.
None runs on the UI thread.

Text that comes from archives and mods (paths, names, file text, strings)
is returned in data fields, never as instructions.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import threading
from collections import OrderedDict
from enum import Enum
from pathlib import Path

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, TOO_LARGE, UNAVAILABLE, ToolError
from cdmw.mcp.names import READ
from cdmw.mcp.tools import ON_UI, ON_WORKER, Tool, object_schema

MAX_BYTES = 1024 * 1024
MAX_SEARCH_ROWS = 5000
FETCH_PAGE = 500
TEXT_EXTENSIONS = frozenset({
    ".xml", ".json", ".txt", ".ini", ".cfg", ".lua", ".csv", ".html", ".htm", ".css", ".js", ".yaml", ".yml",
    ".md", ".log", ".hlsl", ".fx",
})
MAX_TEXT_CHARS = 200_000


# ----- shapes ---------------------------------------------------------------------
def to_data(value: object, depth: int = 0) -> object:
    """Dataclasses, enums, paths and tuples as plain JSON data; bytes are counted, not copied."""

    if depth > 8:
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_data(getattr(value, f.name), depth + 1) for f in dataclasses.fields(value)
                if not f.name.startswith("_")}
    if isinstance(value, dict):
        return {str(k): to_data(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_data(v, depth + 1) for v in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"bytes": len(value)}
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _entry_row(dto) -> dict[str, object]:
    return {
        "path": dto.path, "package": dto.package, "extension": dto.extension, "role": to_data(dto.role),
        "category": dto.category, "type": dto.type_display, "size": int(dto.original_size),
        "stored_size": int(dto.stored_size), "previewable": bool(dto.is_previewable),
        "known_name": dto.known_name, "active_override": bool(dto.is_active_override),
        "override_state": dto.override_state,
    }


def _strings(value: object) -> tuple[str, ...]:
    return tuple(str(v).strip() for v in (value or ()) if str(v).strip())


def _normal(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/")


# ----- commands ---------------------------------------------------------------------
def _commands_list(call) -> dict[str, object]:
    from cdmw.mcp.classification import USER_ONLY_COMMANDS
    from cdmw.mcp.tools import command_tool

    registry = call.context.command_registry()
    if registry is None:
        return {"commands": []}
    wanted = str(call.arguments.get("context") or "")
    query = str(call.arguments.get("query") or "").casefold()
    rows = []
    for command in registry.commands(*((wanted,) if wanted else ())):
        if query and query not in command.label.casefold() and query not in command.id.casefold():
            continue
        reason = registry.reason(command.id)
        tool = None if command.id in USER_ONLY_COMMANDS else command_tool(command)
        rows.append({"id": command.id, "label": command.label, "context": command.context, "keys": list(command.keys),
                     "effect": command.effect, "available": not reason, "reason": reason,
                     "tool": tool.wire if tool is not None and tool.built else None})
    return {"commands": rows}


# ----- search -----------------------------------------------------------------------
def _search_archive(call) -> dict[str, object]:
    from cdmw.domain.archives.catalogue import ArchiveEntryRole, ArchiveQuery
    from cdmw.domain.archives.catalogue_operations import FetchPageRequest

    a = call.arguments
    context = call.context
    session = context.archive_session()
    extensions = tuple(e if e.startswith(".") else "." + e for e in _strings(a.get("extensions")))
    query = ArchiveQuery(
        session.session_id,
        include_text=str(a.get("query") or "").strip() or None,
        exclude_text=str(a.get("exclude") or "").strip() or None,
        extensions=extensions, packages=_strings(a.get("packages")),
        folder=_normal(a.get("folder") or "") or None,
        roles=tuple(ArchiveEntryRole(r) for r in _strings(a.get("roles"))),
        minimum_size=int(a["minimum_size_kb"]) * 1024 if a.get("minimum_size_kb") else None,
        previewable_only=bool(a.get("previewable_only")), active_overrides_only=bool(a.get("active_only")),
    )
    handle = context.catalogue_call("create_query", query, cancel=call.cancel_event)
    wanted = min(int(a.get("max_results") or 1000), MAX_SEARCH_ROWS)
    rows: list[dict[str, object]] = []
    while len(rows) < min(wanted, handle.total_matches):
        call.check_cancelled()
        page = context.catalogue_call("fetch_page", FetchPageRequest(handle.query_id, len(rows),
                                                                     min(FETCH_PAGE, wanted - len(rows))),
                                      cancel=call.cancel_event)
        if not page.rows:
            break
        rows.extend(_entry_row(dto) for dto in page.rows)
        call.progress(len(rows), min(wanted, handle.total_matches), "")
    return {"entries": rows, "total_matches": int(handle.total_matches),
            "truncated": int(handle.total_matches) > len(rows)}


def _search_items(call) -> dict[str, object]:
    from cdmw.domain.archives.item_catalogue import ItemCatalogSearchRequest

    a = call.arguments
    context = call.context
    session = context.archive_session()
    # The Item Finder's name index is built once per session; the worker keeps it.
    context.catalogue_call("build_name_index", session.session_id, cancel=call.cancel_event)
    wanted = min(int(a.get("max_results") or 200), 1000)
    rows: list[object] = []
    total = 0
    while len(rows) < wanted:
        call.check_cancelled()
        result = context.catalogue_call("search_item_catalog", ItemCatalogSearchRequest(
            session.session_id, query=str(a.get("query") or ""), category=a.get("category") or None,
            page_start=len(rows), page_size=min(200, wanted - len(rows)), only_dlc=bool(a.get("only_dlc"))),
            cancel=call.cancel_event)
        total = int(result.total_matches)
        if not result.items:
            break
        rows.extend(to_data(item) for item in result.items)
        if len(rows) >= total:
            break
    return {"items": rows, "total_matches": total, "truncated": total > len(rows)}


def _search_characters(call) -> dict[str, object]:
    from cdmw.domain.archives.character_catalogue import CharacterCatalogSearchRequest

    a = call.arguments
    context = call.context
    session = context.archive_session()
    service = context.catalogue_service()
    if not context.ui_call(lambda: service.character_catalog_available):
        raise ToolError(UNAVAILABLE, "The Character Finder needs an updated archive helper.")
    context.catalogue_call("build_character_catalog", session.session_id, cancel=call.cancel_event)
    result = context.catalogue_call("search_character_catalog", CharacterCatalogSearchRequest(
        session.session_id, query=str(a.get("query") or ""), view=str(a.get("view") or "assets"),
        tab=str(a.get("tab") or "bodies"), page_size=min(int(a.get("max_results") or 200), 1000)),
        cancel=call.cancel_event)
    rows = [to_data(row) for row in getattr(result, "rows", ())]
    return {"characters": rows, "total_matches": int(getattr(result, "total_matches", len(rows)) or len(rows)),
            "warnings": list(getattr(result, "warnings", ()) or ())}


def _search_text(call) -> dict[str, object]:
    from cdmw.core.text_search import normalize_text_search_extensions
    from cdmw.domain.archives.catalogue_operations import ArchiveTextSearchRequest

    a = call.arguments
    context = call.context
    session = context.archive_session()
    extensions = normalize_text_search_extensions(" ".join(_strings(a.get("extensions"))))
    matches: dict[tuple, dict[str, object]] = {}
    state = {"scanned": 0, "matched": 0, "limit": False}

    def batch(payload) -> None:
        if payload is None:
            return
        state["scanned"] = max(state["scanned"], int(getattr(payload, "files_scanned", 0)))
        state["matched"] = max(state["matched"], int(getattr(payload, "files_matched", 0)))
        state["limit"] = state["limit"] or bool(getattr(payload, "limit_reached", False))
        for m in getattr(payload, "matches", ()):
            matches.setdefault((m.entry_id, m.line, m.column), {
                "path": m.path, "package": m.package, "line": m.line, "column": m.column, "length": m.length,
                "context": m.context})
        call.progress(state["scanned"], 0, f"{state['scanned']} files read")

    # Batches stream while it runs; the final answer may repeat the last matches.
    batch(context.catalogue_call("text_search", ArchiveTextSearchRequest(
        session.session_id, str(a["query"]), use_regular_expression=bool(a.get("regex")),
        case_sensitive=bool(a.get("case_sensitive")), path_filter=_normal(a.get("path_filter") or "") or None,
        extensions=tuple(extensions), maximum_matches=int(a.get("maximum_matches") or 2000)),
        cancel=call.cancel_event, on_batch=batch))
    return {"matches": list(matches.values()), "files_scanned": state["scanned"],
            "files_matched": state["matched"], "limit_reached": state["limit"]}


def _model_catalogue(context) -> Path:
    from cdmw.domain.workspace import workspace_paths

    configured = str(context.settings.value("model_library/catalogue_dir", "") or "").strip() if context.settings \
        is not None else ""
    folder = Path(configured).expanduser() if configured else workspace_paths(context.app_folder())[
        "model_catalogue_root"]
    return folder / "mirror_catalogue.sqlite"


def _search_models(call) -> dict[str, object]:
    from cdmw.services.model_library_service import ModelLibraryService

    a = call.arguments
    db = _model_catalogue(call.context)
    if not db.is_file():
        raise ToolError(UNAVAILABLE, "The Model Library has no catalogue yet: index one in Model Library first.")
    rows = ModelLibraryService().search_catalogue(
        db, str(a.get("query") or ""), limit=min(int(a.get("max_results") or 100), 1000),
        license_contains=str(a.get("license") or ""), creator_contains=str(a.get("creator") or ""),
        required_format=str(a.get("format") or ""))
    return {"models": [to_data(row) for row in rows]}


def _search_saved_work(call) -> dict[str, object]:
    from cdmw.domain.workspace import workspace_paths
    from cdmw.services.mesh_saved_work_service import list_saved_work

    root = workspace_paths(call.context.app_folder())["modify_original_sessions_root"]
    rows = list_saved_work(root, path_filter=str(call.arguments.get("filter") or ""))
    return {"saved_work": [to_data(row) for row in rows]}


# ----- questions about files ----------------------------------------------------------
def _lookup(call, path: str):
    """Every copy of an archive path (the copy the game reads first), as catalogue entries."""

    from cdmw.domain.archives.catalogue import ArchiveLookupKind, ArchiveLookupRequest

    wanted = _normal(path)
    if not wanted:
        raise ToolError(INVALID_ARGUMENTS, "path is required")
    session = call.context.archive_session()
    found: dict[int, object] = {}

    def batch(payload) -> None:
        # The worker streams lookup rows as batches; the final answer may hold the rest.
        for dto in getattr(payload, "entries", ()) or ():
            found[int(dto.entry_id)] = dto

    batch(call.context.catalogue_call("resolve_entries", ArchiveLookupRequest(
        session.session_id, ArchiveLookupKind.EXACT_PATHS, values=(wanted,), limit=64), cancel=call.cancel_event,
        on_batch=batch))
    copies = [dto for dto in found.values() if _normal(dto.path).casefold() == wanted.casefold()]
    if not copies:
        raise ToolError(NOT_FOUND, f"The archives have no {wanted}.")
    copies.sort(key=lambda dto: not dto.is_active_override)
    return session, copies


def _compat(call, dto):
    return call.context.catalogue_service().compatibility_entry(dto)


def _read(call, dto, *, stored: bool = False) -> bytes:
    from cdmw.core.archive_extraction import read_archive_entry_data, read_archive_entry_raw_data

    entry = _compat(call, dto)
    if stored:
        return bytes(read_archive_entry_raw_data(entry, stop_event=call.cancel_event))
    return bytes(read_archive_entry_data(entry, stop_event=call.cancel_event)[0])


def _files_describe(call) -> dict[str, object]:
    from cdmw.core.archive_extraction import build_archive_entry_metadata_summary

    _session, copies = _lookup(call, call.arguments["path"])
    entry = _compat(call, copies[0])
    return {"path": copies[0].path, "entry": _entry_row(copies[0]),
            "summary": build_archive_entry_metadata_summary(entry),
            "compressed": bool(getattr(entry, "compressed", False)),
            "encrypted": bool(getattr(entry, "encrypted", False)),
            "copies": [_entry_row(dto) for dto in copies]}


def _files_bytes(call) -> dict[str, object]:
    a = call.arguments
    _session, copies = _lookup(call, a["path"])
    data = _read(call, copies[0], stored=bool(a.get("stored")))
    offset = int(a.get("offset") or 0)
    length = int(a.get("length") or 65536)
    if length > MAX_BYTES:
        raise ToolError(TOO_LARGE, f"At most {MAX_BYTES} bytes a call; read the rest with a higher offset.")
    if offset > len(data):
        raise ToolError(INVALID_ARGUMENTS, f"offset is past the end ({len(data)} bytes)")
    chunk = data[offset:offset + length]
    return {"path": copies[0].path, "package": copies[0].package, "offset": offset, "length": len(chunk),
            "total_size": len(data), "stored": bool(a.get("stored")), "base64": base64.b64encode(chunk).decode("ascii"),
            "more": offset + len(chunk) < len(data)}


def _parse_paloc(data: bytes, name: str) -> dict[str, object]:
    from cdmw.core.paloc_format import parse_paloc

    table = parse_paloc(data, name=name)
    return {"kind": "localization", "entries": [{"category": e.category, "key": e.key, "text": e.text}
                                                for e in table.entries]}


def _files_parse(call) -> dict[str, object]:
    a = call.arguments
    session, copies = _lookup(call, a["path"])
    dto = copies[0]
    extension = str(dto.extension or Path(dto.path).suffix).casefold()
    base = {"path": dto.path, "package": dto.package, "extension": extension}
    if extension == ".paloc":
        return {**base, **_parse_paloc(_read(call, dto), dto.path)}
    if extension in TEXT_EXTENSIONS:
        data = _read(call, dto)
        text = data.decode("utf-8-sig", errors="replace")
        limit = int(a.get("max_characters") or MAX_TEXT_CHARS)
        return {**base, "kind": "text", "text": text[:limit], "characters": len(text),
                "truncated": len(text) > limit}
    from cdmw.domain.archives.catalogue_operations import PrepareEntryRequest

    prepared = call.context.catalogue_call("prepare_entry", PrepareEntryRequest(
        session.session_id, dto.entry_id, include_content_analysis=True), cancel=call.cancel_event)
    analysis: object = None
    text = ""
    json_path = getattr(prepared, "content_analysis_json_path", None)
    text_path = getattr(prepared, "content_analysis_text_path", None)
    if json_path and Path(json_path).is_file() and Path(json_path).stat().st_size <= 8 * MAX_BYTES:
        analysis = json.loads(Path(json_path).read_text(encoding="utf-8"))
    if text_path and Path(text_path).is_file():
        text = Path(text_path).read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_CHARS]
    if analysis is None and not text:
        return {**base, "kind": "unparsed", "size": int(dto.original_size),
                "note": "CDMW has no parser for this format yet; read its bytes with files_bytes."}
    return {**base, "kind": "analysis", "analysis": analysis, "text": text,
            "analyzer_version": getattr(prepared, "content_analysis_version", None)}


def _reference_row(reference) -> dict[str, object]:
    return {"reference": reference.reference_name, "material": reference.material_name,
            "texture_role": reference.texture_role, "semantic": reference.semantic_label,
            "status": reference.resolution_status, "resolved_path": reference.resolved_archive_path,
            "resolved_package": reference.resolved_package_label, "mesh": reference.linked_mesh_path,
            "part": reference.part_name}


def _files_references(call) -> dict[str, object]:
    from cdmw.services.archive_query_service import build_archive_relationship_references

    _session, copies = _lookup(call, call.arguments["path"])
    index = call.context.resident_index(call.cancel_event)
    references = build_archive_relationship_references(
        _compat(call, copies[0]), archive_entries_by_normalized_path=index.by_path,
        archive_entries_by_basename=index.by_basename)
    return {"path": copies[0].path, "references": [_reference_row(r) for r in references]}


def _files_used_by(call) -> dict[str, object]:
    session, copies = _lookup(call, call.arguments["path"])
    state = call.context.used_by(_compat(call, copies[0]), session.session_id, call.cancel_event,
                                 progress=call.progress)
    if state is None:
        raise ToolError(UNAVAILABLE, "The reference search could not start.")
    if getattr(state, "error", ""):
        from cdmw.mcp.errors import FAILED

        raise ToolError(FAILED, state.error)
    return {"path": copies[0].path, "used_by": [_reference_row(r) for r in state.references],
            "files_scanned": int(state.scanned), "files_considered": int(state.total),
            "limited": bool(state.limited), "note": state.note}


def _files_format_report(call) -> dict[str, object]:
    from tools.format_explorer.catalogue import load_rows

    a = call.arguments
    extension = str(a.get("extension") or Path(_normal(a.get("path") or "")).suffix).strip().casefold()
    if not extension:
        raise ToolError(INVALID_ARGUMENTS, "Give an extension or a path")
    extension = extension if extension.startswith(".") else "." + extension
    rows = [to_data(row) for row in load_rows() if str(row.extension).casefold() in (extension, extension[1:])]
    if not rows:
        raise ToolError(NOT_FOUND, f"The Format Explorer has no row for {extension}.")
    return {"extension": extension, "formats": rows}


# ----- tables and strings -------------------------------------------------------------
def _game_root(call) -> Path:
    try:
        root = call.context.archive_session().package_root
    except ToolError:
        root = call.context.game_folder()
    if not root or not Path(root).is_dir():
        raise ToolError(UNAVAILABLE, "Set the game folder in Settings > Paths first.")
    return Path(root)


def _tables_row(call) -> dict[str, object]:
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.static_table_records import DECODED_TABLES, decode_static_table
    from cdmw.services.game_table_edits import TableEditError, archive_table_layers

    a = call.arguments
    table = str(a["table"]).strip().casefold()
    if table not in DECODED_TABLES:
        raise ToolError(INVALID_ARGUMENTS, f"CDMW does not decode {table}. It decodes: {', '.join(sorted(DECODED_TABLES))}")
    index = call.context.resident_index(call.cancel_event)
    try:
        layers = archive_table_layers(
            _game_root(call), table, scan=lambda _root: index,
            read=lambda entry: read_archive_entry_data(entry, stop_event=call.cancel_event)[0],
            stop_event=call.cancel_event)
    except TableEditError as error:
        raise ToolError(NOT_FOUND, str(error)) from None
    key = a.get("key")
    name = str(a.get("name") or "").strip()
    if key is None and not name:
        raise ToolError(INVALID_ARGUMENTS, "Give key or name")
    found = []
    for layer in layers:
        call.check_cancelled()
        decoded = decode_static_table(table, layer.header, layer.body)
        for record in decoded.records:
            if (key is not None and record.key == int(key)) or (name and record.name == name):
                found.append({"layer": layer.stem, "key": record.key, "name": record.name,
                              "fields": to_data(record.fields), "members": to_data(record.members)})
    if not found:
        raise ToolError(NOT_FOUND, f"{table} has no row {key if key is not None else name}.")
    # The game reads the last layer that has the row (a DLC copy over the base).
    return {"table": table, "row": found[-1], "layers": [row["layer"] for row in found]}


_CATALOGUES: OrderedDict[tuple[str, str], object] = OrderedDict()
_CATALOGUE_LOCK = threading.Lock()


def _strings_catalogue(root: Path, language: str, cancel: threading.Event):
    from tools.translation_studio.catalogue import load_catalogue, read_language_tables

    key = (str(root).casefold(), language)
    with _CATALOGUE_LOCK:
        if key in _CATALOGUES:
            _CATALOGUES.move_to_end(key)
            return _CATALOGUES[key]
    catalogue = load_catalogue(read_language_tables(language, root, is_cancelled=cancel.is_set), language)
    with _CATALOGUE_LOCK:
        _CATALOGUES[key] = catalogue
        while len(_CATALOGUES) > 2:
            _CATALOGUES.popitem(last=False)
    return catalogue


def _strings_get(call) -> dict[str, object]:
    from cdmw.core.paloc_format import PalocFormatError
    from tools.translation_studio.catalogue import available_languages

    a = call.arguments
    root = _game_root(call)
    language = str(a.get("language") or "eng").strip()
    try:
        catalogue = _strings_catalogue(root, language, call.cancel_event)
    except (PalocFormatError, InterruptedError) as error:
        if isinstance(error, InterruptedError):
            from cdmw.mcp.errors import CANCELLED

            raise ToolError(CANCELLED, "Cancelled.") from None
        languages = ", ".join(available_languages(root)) or "none"
        raise ToolError(NOT_FOUND, f"{error}. The archives have: {languages}.") from None
    keys = set(_strings(a.get("keys")))
    if a.get("key"):
        keys.add(str(a["key"]).strip())
    search = str(a.get("search") or "").strip()
    if not keys and not search:
        raise ToolError(INVALID_ARGUMENTS, "Give key, keys or search")
    rows = []
    if keys:
        for index, entry in enumerate(catalogue.table.entries):
            if entry.key in keys:
                rows.append(to_data(catalogue.row(index)))
    if search:
        rows.extend(to_data(catalogue.row(index)) for index in catalogue.find(search, limit=MAX_SEARCH_ROWS))
    return {"language": language, "strings": rows}


# ----- the table ----------------------------------------------------------------------
_PATH = {"type": "string", "minLength": 1, "maxLength": 1024,
         "description": "An archive path, as Browse Archives shows it (character/model/x.pac)."}
_TEXT = {"type": "string", "maxLength": 512}
_LIST = {"type": "array", "items": {"type": "string", "maxLength": 128}, "maxItems": 64}


def _role_values() -> list[str]:
    from cdmw.domain.archives.catalogue import ArchiveEntryRole

    return [role.value for role in ArchiveEntryRole]


def _contexts() -> list[str]:
    from cdmw.ui.commands.registry import CONTEXTS

    return list(CONTEXTS)


def read_tools() -> list[Tool]:
    def tool(name, title, description, properties, required, handler, route, *, paged="", runs_on=ON_WORKER):
        return Tool(name=name, family=name.split(".")[0], title=title, description=description,
                    input_schema=object_schema(properties, required), effect=READ, route=route, handler=handler,
                    runs_on=runs_on, paged=paged)

    return [
        tool("commands.list", "Commands",
             "Every command of the interface with its id, label, context, keys and class, whether it can run now "
             "and, when not, the interface's reason. 'tool' names the AI tool that runs it, when one is built.",
             {"context": {"type": "string", "enum": ["", *_contexts()]}, "query": _TEXT}, [], _commands_list,
             "registry:CommandRegistry.commands", paged="commands", runs_on=ON_UI),
        tool("search.archive", "Search archives",
             "Searches the game's archives as Browse Archives does: words in the path, words to leave out, "
             "extensions, packages, a folder, roles, a minimum size, previewable files only, active overrides only.",
             {"query": _TEXT, "exclude": _TEXT, "extensions": _LIST, "packages": _LIST, "folder": _TEXT,
              "roles": {"type": "array", "items": {"type": "string", "enum": _role_values()}, "maxItems": 16},
              "minimum_size_kb": {"type": "integer", "minimum": 0}, "previewable_only": {"type": "boolean"},
              "active_only": {"type": "boolean"},
              "max_results": {"type": "integer", "minimum": 1, "maximum": MAX_SEARCH_ROWS, "default": 1000}},
             [], _search_archive, "service:ArchiveCatalogueService.create_query+fetch_page", paged="entries"),
        tool("search.items", "Item Finder",
             "Finds game items by name, internal name or id, as the Item Finder does: their category, models, "
             "icons and names in each language.",
             {"query": _TEXT, "category": _TEXT, "only_dlc": {"type": "boolean"},
              "max_results": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200}},
             [], _search_items, "service:ArchiveCatalogueService.search_item_catalog", paged="items"),
        tool("search.characters", "Character Finder",
             "Finds bodies, faces, hair and other character parts, as the Character Finder does.",
             {"query": _TEXT, "view": _TEXT, "tab": _TEXT,
              "max_results": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200}},
             [], _search_characters, "service:ArchiveCatalogueService.search_character_catalog",
             paged="characters"),
        tool("search.text", "Search file text",
             "Searches inside the archives' text files, as Search File Text does: plain words or a regular "
             "expression, case, a path filter and extensions. Returns each match with its line and context.",
             {"query": {"type": "string", "minLength": 1, "maxLength": 512}, "regex": {"type": "boolean"},
              "case_sensitive": {"type": "boolean"}, "path_filter": _TEXT, "extensions": _LIST,
              "maximum_matches": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 2000}},
             ["query"], _search_text, "service:ArchiveCatalogueService.text_search", paged="matches"),
        tool("search.models", "Model Library",
             "Searches the Model Library's indexed catalogue of downloadable models by words, licence, creator "
             "and format.",
             {"query": _TEXT, "license": _TEXT, "creator": _TEXT, "format": _TEXT,
              "max_results": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100}},
             [], _search_models, "service:ModelLibraryService.search_catalogue", paged="models"),
        tool("search.saved_work", "Drafts & Mods",
             "Lists saved work as Drafts & Mods does: drafts, built mods and item packages, newest first, "
             "optionally only those whose source path contains the filter.",
             {"filter": _TEXT}, [], _search_saved_work, "service:mesh_saved_work_service.list_saved_work",
             paged="saved_work"),
        tool("files.describe", "Describe a file",
             "What an archive file is: its type, size, package, compression, and every package that holds a "
             "copy (the copy the game reads first).",
             {"path": _PATH}, ["path"], _files_describe,
             "service:ArchiveCatalogueService.resolve_entries+build_archive_entry_metadata_summary"),
        tool("files.bytes", "Read file bytes",
             f"Raw bytes of an archive file, decoded (or as stored), as base64: up to {MAX_BYTES} bytes a call "
             "from an offset.",
             {"path": _PATH, "offset": {"type": "integer", "minimum": 0, "default": 0},
              "length": {"type": "integer", "minimum": 1, "maximum": MAX_BYTES, "default": 65536},
              "stored": {"type": "boolean", "default": False}},
             ["path"], _files_bytes, "service:archive_extraction.read_archive_entry_data"),
        tool("files.parse", "Parse a file",
             "An archive file's content: text files as text, localisation tables as entries, and other formats "
             "as the content analysis the interface's inspector shows.",
             {"path": _PATH, "max_characters": {"type": "integer", "minimum": 1, "maximum": MAX_TEXT_CHARS,
                                               "default": MAX_TEXT_CHARS}},
             ["path"], _files_parse, "service:ArchiveCatalogueService.prepare_entry(content analysis)",
             paged="entries"),
        tool("files.references", "References",
             "What an archive file refers to (textures, materials, meshes), resolved against the loaded archives, "
             "as the asset family view shows.",
             {"path": _PATH}, ["path"], _files_references,
             "service:archive_query_service.build_archive_relationship_references", paged="references"),
        tool("files.used_by", "Used by",
             "Which archive files refer to this one, as Find references does in Browse Archives.",
             {"path": _PATH}, ["path"], _files_used_by, "service:ArchiveReferenceSearchController", paged="used_by"),
        tool("files.format_report", "Format report",
             "The Format Explorer's row for a file type: what CDMW can read and write, its evidence and what is "
             "left.",
             {"path": _TEXT, "extension": _TEXT}, [], _files_format_report,
             "service:tools.format_explorer.catalogue.load_rows"),
        tool("tables.row", "Game table row",
             "One row of a game table (iteminfo, skill ...) by key or name, decoded field by field, from the copy "
             "the game reads.",
             {"table": {"type": "string", "minLength": 1, "maxLength": 64}, "key": {"type": "integer"},
              "name": _TEXT}, ["table"], _tables_row,
             "service:game_table_edits.archive_table_layers+static_table_records.decode_static_table"),
        tool("strings.get", "Localisation strings",
             "Game strings by key, several keys, or words in the key or text, in one language (eng by default), "
             "as Translation Studio reads them.",
             {"key": _TEXT, "keys": {"type": "array", "items": {"type": "string", "maxLength": 128},
                                      "maxItems": 100},
              "search": _TEXT, "language": {"type": "string", "maxLength": 16, "default": "eng"}},
             [], _strings_get, "service:tools.translation_studio.catalogue.read_language_tables", paged="strings"),
    ]
