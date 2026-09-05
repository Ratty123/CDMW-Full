"""Worker-side source revisions for durable New Item material packages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.preview_rendering_service import (
    find_native_preview_core_binary,
    render_settings_to_native_preview_core_dict,
)


def _file_stamp(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
        return str(path), stat.st_size, stat.st_mtime_ns
    except OSError:
        return str(path), -1, -1


def template_preview_cache_identity(entry, dependencies, template_key, render_settings, stop_event) -> str:
    """Include source archives that Preview Core may discover beyond the PAC.

    This runs on the package worker. Stat the small archive-file inventory,
    never the millions of indexed entries or their payloads.
    """

    raise_if_cancelled(stop_event)
    root = Path(entry.pamt_path).parent.parent
    archive_paths = {path for path in root.glob("*/*") if path.suffix.lower() in {".pamt", ".paz"}}
    for dependency in dependencies:
        pamt = Path(dependency.pamt_path)
        archive_paths.add(pamt)
        if dependency.paz_file:
            archive_paths.add(pamt.parent / dependency.paz_file)
        if prepared := getattr(dependency, "prepared_path", None):
            archive_paths.add(Path(prepared))
    archives = []
    for path in sorted(archive_paths):
        raise_if_cancelled(stop_event)
        archives.append(_file_stamp(path))
    binary = find_native_preview_core_binary()
    payload = {
        "schema": 2,
        "template_key": template_key,
        "primary": entry.path,
        "dependencies": [
            (item.path, str(item.pamt_path), str(item.paz_file), item.offset, item.comp_size,
             str(getattr(item, "prepared_path", None) or ""), str(getattr(item, "prepared_sha256", "") or ""))
            for item in dependencies
        ],
        "archives": archives,
        "native_binary": _file_stamp(Path(binary)) if binary is not None else None,
        "render_settings": render_settings_to_native_preview_core_dict(render_settings),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "new_item_native:" + hashlib.sha256(encoded).hexdigest()
