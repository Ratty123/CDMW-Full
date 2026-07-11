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


def audit_prefab_json_import_sample(data: bytes, virtual_path: str, *, include_edit_probes: bool=True) -> dict[str, object]:
    from cdmw.core.prefab_corpus_audit_rows_0 import _build_audit_success_row
    from cdmw.core.prefab_corpus_audit_rows_1 import _build_audit_error_row
    from cdmw.core.prefab_corpus_audit_stages import _audit_prefab_json_import_sample_stage_0, _audit_prefab_json_import_sample_stage_1, _audit_prefab_json_import_sample_stage_2, _audit_prefab_json_import_sample_stage_3
    started = time.perf_counter()
    payload = bytes(data or b'')
    state = dict(locals())
    try:
        state.update(_audit_prefab_json_import_sample_stage_0(state))
        state.update(_audit_prefab_json_import_sample_stage_1(state))
        state.update(_audit_prefab_json_import_sample_stage_2(state))
        state.update(_audit_prefab_json_import_sample_stage_3(state))
        return _build_audit_success_row(state)
    except (OSError, PrefabEditJsonError, ValueError, TypeError) as exc:
        return _build_audit_error_row(state, exc)
