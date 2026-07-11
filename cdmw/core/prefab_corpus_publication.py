from __future__ import annotations

import json
import math
import struct
import time
from bisect import bisect_right
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, TypeVar

from cdmw.core.common import raise_if_cancelled
from cdmw.core.archive_attachment_patches import (
    build_prefab_attachment_profile_patch,
    inspect_prefab_attachment_profile_fields,
)
from cdmw.core.crimson_formats import decode_prefab, rebuild_prefab_no_edit
from cdmw.core.prefab_json import (
    PrefabEditJsonError,
    apply_prefab_edit_document,
    build_prefab_edit_document,
    rebuild_prefab_no_edit_from_edit_document,
)
from cdmw.models import ArchiveEntry
from cdmw.core.prefab_corpus_contracts import (
    EDIT_PROBES_DISABLED_REASON,
    NO_SAFE_PLACEMENT_LENGTH_PROBE_REASON,
    NO_SAFE_RESOURCE_LENGTH_PROBE_REASON,
    OVERLAPPING_OFFSET_CANDIDATES_REASON,
    PREFAB_JSON_IMPORT_CORPUS_FORMAT,
    T,
)


def discover_prefab_archive_entries(entries: Sequence[ArchiveEntry], *, discovery_limit: Optional[int]=None) -> list[ArchiveEntry]:
    limit = int(discovery_limit) if discovery_limit is not None and int(discovery_limit) > 0 else None
    prefabs = [entry for entry in entries if str(entry.extension or '').lower() == '.prefab']
    prefabs.sort(key=lambda entry: str(entry.path or '').casefold())
    return prefabs[:limit] if limit is not None else prefabs


def _read_archive_entry_payload(entry: ArchiveEntry, read_entry_data: Callable[..., tuple[bytes, bool, str]], stop_event: object=None) -> bytes:
    try:
        data, _decompressed, _note = read_entry_data(entry, stop_event=stop_event)
    except TypeError:
        data, _decompressed, _note = read_entry_data(entry)
    return bytes(data or b'')


def build_prefab_json_import_archive_entry_json(entries: Sequence[ArchiveEntry], *, read_entry_data: Optional[Callable[..., tuple[bytes, bool, str]]]=None, source_label: str='archive_entries', discovery_limit: Optional[int]=None, detail_scan_limit: Optional[int]=1000, scan_offset: int=0, scan_count: Optional[int]=None, include_edit_probes: bool=True, stop_event: object=None, progress_callback: Optional[Callable[[int, int, str], None]]=None) -> str:
    from cdmw.core.prefab_corpus_loading import build_prefab_json_import_archive_entry_report
    return json.dumps(build_prefab_json_import_archive_entry_report(entries, read_entry_data=read_entry_data, source_label=source_label, discovery_limit=discovery_limit, detail_scan_limit=detail_scan_limit, scan_offset=scan_offset, scan_count=scan_count, include_edit_probes=include_edit_probes, stop_event=stop_event, progress_callback=progress_callback), indent=2)


def build_prefab_json_import_corpus_json(source_paths: Sequence[Path], *, discovery_limit: Optional[int]=None, detail_scan_limit: Optional[int]=1000, scan_offset: int=0, scan_count: Optional[int]=None, include_edit_probes: bool=True, stop_event: object=None, progress_callback: Optional[Callable[[int, int, str], None]]=None) -> str:
    from cdmw.core.prefab_corpus_loading import build_prefab_json_import_corpus_report
    return json.dumps(build_prefab_json_import_corpus_report(source_paths, discovery_limit=discovery_limit, detail_scan_limit=detail_scan_limit, scan_offset=scan_offset, scan_count=scan_count, include_edit_probes=include_edit_probes, stop_event=stop_event, progress_callback=progress_callback), indent=2)
