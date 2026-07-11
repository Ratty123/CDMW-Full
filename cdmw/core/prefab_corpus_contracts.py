from __future__ import annotations

from typing import TypeVar


PREFAB_JSON_IMPORT_CORPUS_FORMAT = "cdmw_prefab_json_import_corpus_v1"
EDIT_PROBES_DISABLED_REASON = "Edit probes disabled for no-edit-only corpus scan."
NO_SAFE_RESOURCE_LENGTH_PROBE_REASON = "No editable resource reference with a safe length-changing probe candidate."
NO_SAFE_PLACEMENT_LENGTH_PROBE_REASON = "No editable placement field with a safe length-changing probe candidate."
OVERLAPPING_OFFSET_CANDIDATES_REASON = "Prefab offset candidates overlap; length-changing rebuild is ambiguous."
T = TypeVar("T")


__all__ = [
    "EDIT_PROBES_DISABLED_REASON",
    "NO_SAFE_PLACEMENT_LENGTH_PROBE_REASON",
    "NO_SAFE_RESOURCE_LENGTH_PROBE_REASON",
    "OVERLAPPING_OFFSET_CANDIDATES_REASON",
    "PREFAB_JSON_IMPORT_CORPUS_FORMAT",
    "T",
]
