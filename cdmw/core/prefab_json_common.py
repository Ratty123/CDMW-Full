from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from cdmw.domain.archives.prefab import (
    PREFAB_EDIT_JSON_FORMAT,
    PREFAB_EDIT_JSON_VERSION,
    SUPPORTED_PREFAB_EDIT_ROLES,
    SUPPORTED_PREFAB_PLACEMENT_FIELDS,
    PrefabEditJsonError,
)
from cdmw.core.archive_attachment_patches import (
    build_prefab_attachment_profile_patch,
    inspect_prefab_attachment_profile_fields,
)
from cdmw.core.crimson_formats import (
    build_prefab_resource_path_patch,
    decode_prefab,
    rebuild_prefab_resized_strings,
)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(bytes(data or b'')).hexdigest()


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PrefabEditJsonError(f'{label} must be a JSON object.')
    return value


def _as_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise PrefabEditJsonError(f'{label} must be a JSON array.')
    return value


def _as_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise PrefabEditJsonError(f'{label} must be a string.')
    return value


def _as_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PrefabEditJsonError(f'{label} must be an integer.')
    return value


def _as_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise PrefabEditJsonError(f'{label} must be a boolean.')
    return value


def _require_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    keys = set(value.keys())
    missing = sorted(allowed - keys)
    if missing:
        raise PrefabEditJsonError(f"{label} is missing required field(s): {', '.join(missing)}.")
    extra = sorted(keys - allowed)
    if extra:
        raise PrefabEditJsonError(f"{label} contains unsupported field(s): {', '.join(extra)}.")


def _normalize_path(value: str) -> str:
    return str(value or '').replace('\\', '/').strip()


def _resource_path_extension(value: str) -> str:
    return PurePosixPath(_normalize_path(value)).suffix.lower()


def _validate_resource_replacement_path(original: str, value: str, role: str, extension: str) -> None:
    normalized = _normalize_path(value)
    if not normalized or any((ord(char) < 32 for char in normalized)):
        raise PrefabEditJsonError('Prefab replacement path is invalid.')
    if normalized.startswith('/') or ':' in normalized or '//' in normalized:
        raise PrefabEditJsonError('Prefab replacement path is invalid.')
    parts = normalized.split('/')
    if any((part in {'', '.', '..'} for part in parts)):
        raise PrefabEditJsonError('Prefab replacement path is invalid.')
    if '/' not in normalized:
        raise PrefabEditJsonError('Prefab replacement path must stay relative to game data.')
    expected_extension = str(extension or '').strip().lower()
    if _resource_path_extension(normalized) != expected_extension:
        raise PrefabEditJsonError('Prefab replacement path must keep the same extension in V1.')
    if str(original or '').casefold().endswith('.sockets.xml') and (not normalized.casefold().endswith('.sockets.xml')):
        raise PrefabEditJsonError('Prefab socket descriptor replacement must keep the .sockets.xml suffix in V1.')
    if role == 'model' and expected_extension not in {'.pac', '.pam', '.pamlod'}:
        raise PrefabEditJsonError('Prefab model replacement path has an unsupported extension.')
    if role == 'texture' and expected_extension != '.dds':
        raise PrefabEditJsonError('Prefab texture replacement path has an unsupported extension.')
