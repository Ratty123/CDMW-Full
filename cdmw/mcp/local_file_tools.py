"""Read local file information using the same decoders as Browse Archives."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, TOO_LARGE, ToolError
from cdmw.mcp.names import READ
from cdmw.mcp.rail_actions import PATH, ROW, tool
from cdmw.mcp.read_tools import MAX_BYTES, MAX_TEXT_CHARS, TEXT_EXTENSIONS
from cdmw.mcp.tools import ON_WORKER


def _path(call):
    path = Path(call.arguments["path"])
    if not path.is_absolute() or (os.name == "nt" and not path.drive):
        raise ToolError(INVALID_ARGUMENTS, "The local file path must be absolute.")
    try:
        path = path.resolve(strict=True)
        if path.is_file():
            return path
    except OSError:
        pass
    raise ToolError(NOT_FOUND, f"No regular file exists at {path}.")


def _describe(call):
    from cdmw.core.archive_extraction import format_byte_size

    path = _path(call)
    size = path.stat().st_size
    return {"path": str(path), "name": path.name, "extension": path.suffix.casefold(), "size": size,
            "summary": f"Loose file | {path.name} | {format_byte_size(size)}"}


def _bytes(call):
    args = call.arguments
    path = _path(call)
    offset = args.get("offset", 0)
    with path.open("rb") as file:
        size = os.fstat(file.fileno()).st_size
        if offset > size:
            raise ToolError(INVALID_ARGUMENTS, f"offset is past the end ({size} bytes).")
        file.seek(offset)
        chunk = file.read(args.get("length", 65536))
    return {"path": str(path), "offset": offset, "length": len(chunk), "total_size": size,
            "base64": base64.b64encode(chunk).decode("ascii"), "more": offset + len(chunk) < size}


def _parse(call):
    from cdmw.core.archive_data_table_preview import build_paloc_preview
    from cdmw.core.archive_structured_preview import build_archive_binary_preview_payload
    from cdmw.models import ArchiveEntry

    path = _path(call)
    extension = path.suffix.casefold()
    limit = call.arguments.get("max_characters", MAX_TEXT_CHARS)
    with path.open("rb") as source:
        data = source.read(32 * MAX_BYTES + 1 if extension == ".paloc" else max(MAX_BYTES, limit * 4) + 1)
        size = os.fstat(source.fileno()).st_size
    if extension == ".paloc":
        if len(data) < size:
            raise ToolError(TOO_LARGE, "The loose language table is too large for a single parse.")
        result = build_paloc_preview(data, path.name)
        kind, text, detail = "localization", result.preview_text, "\n".join(result.detail_lines)
    elif extension in TEXT_EXTENSIONS:
        kind, text, detail = "text", data.decode("utf-8-sig", errors="replace"), ""
    else:
        # The generic preview uses only the entry's extension for content sniffing.
        entry = ArchiveEntry(path=path.name, pamt_path=path, paz_file=path, paz_index=0, offset=0,
                             comp_size=size, orig_size=size, flags=0)
        kind, text, detail = build_archive_binary_preview_payload(entry, data)
    return {"path": str(path), "extension": extension, "kind": kind, "text": text[:limit],
            "detail": detail[:limit], "truncated": len(data) < size or len(text) > limit or len(detail) > limit}


def local_file_tools():
    return [
        tool("local_file.describe", READ, "Describe a loose file by absolute path.", "file:Path.stat", _describe,
             {"path": PATH}, ("path",), runs_on=ON_WORKER),
        tool("local_file.bytes", READ, "Read a bounded range of a loose file as base64.", "file:Path.open", _bytes,
             {"path": PATH, "offset": ROW, "length": {"type": "integer", "minimum": 1, "maximum": MAX_BYTES}},
             ("path",), runs_on=ON_WORKER),
        tool("local_file.parse", READ, "Read text or structured preview information for a loose file.",
             "service:archive_structured_preview.build_archive_binary_preview_payload", _parse,
             {"path": PATH, "max_characters": {"type": "integer", "minimum": 1, "maximum": MAX_TEXT_CHARS}},
             ("path",), runs_on=ON_WORKER),
    ]
