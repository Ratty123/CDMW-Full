"""Bounded language JSON parsing and atomic publication."""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cdmw.core.common import read_file_bytes_cancellable
from cdmw.domain.localization import (
    TranslationEntry,
    canonical_language_code,
    sanitize_language_code,
    translation_leaf_count,
    validate_translation_entry,
)
from cdmw.domain.cancellation import raise_if_cancelled


LANGUAGE_WARNING = (
    "Translate only values in the translations object and keep the English keys and named "
    "placeholders unchanged. Plural objects use CLDR category names. Longer text can make "
    "buttons, tabs, and dialogs look crowded or clipped."
)
LANGUAGE_SCHEMA_VERSION = 2
LANGUAGE_FILE_MAX_BYTES = 16 * 1024 * 1024
LANGUAGE_TRANSLATION_MAX_COUNT = 100_000
LANGUAGE_KEY_MAX_CHARS = 4_000
LANGUAGE_VALUE_MAX_CHARS = 100_000


def safe_language_code(code: object) -> str:
    return canonical_language_code(sanitize_language_code(code))


def _coerce_v2_entry(source: str, raw_value: object) -> TranslationEntry | None:
    if isinstance(raw_value, str):
        if not raw_value.strip():
            return None
        return validate_translation_entry(source, raw_value, require_plural_other=False)
    if not isinstance(raw_value, dict):
        raise ValueError(
            f"Translation for {source!r} must be a string or plural-category object."
        )
    present = {
        str(category): value
        for category, value in raw_value.items()
        if isinstance(value, str) and value.strip()
    }
    if not present:
        return None
    return validate_translation_entry(source, present, require_plural_other=False)


def coerce_translation_payload(payload: object) -> tuple[str, str, dict[str, TranslationEntry]]:
    if not isinstance(payload, dict):
        raise ValueError("Language file must be a JSON object.")
    raw_schema_version = payload.get("schema_version", 1)
    try:
        schema_version = int(raw_schema_version)
    except (TypeError, ValueError) as exc:
        raise ValueError("Language schema_version must be an integer.") from exc
    if schema_version not in {1, LANGUAGE_SCHEMA_VERSION}:
        raise ValueError(f"Unsupported language schema_version: {schema_version}.")
    code = str(payload.get("language_code") or payload.get("code") or "custom").strip() or "custom"
    name = str(payload.get("language_name") or payload.get("name") or code).strip() or code
    translations_raw = payload.get("translations", payload)
    if not isinstance(translations_raw, dict):
        raise ValueError("Language file must contain a translations object.")
    if len(translations_raw) > LANGUAGE_TRANSLATION_MAX_COUNT:
        raise ValueError(f"Language file exceeds the {LANGUAGE_TRANSLATION_MAX_COUNT:,}-translation safety limit.")
    translations: dict[str, TranslationEntry] = {}
    for raw_key, raw_value in translations_raw.items():
        if not isinstance(raw_key, str):
            continue
        key = str(raw_key)
        if not key or len(key) > LANGUAGE_KEY_MAX_CHARS:
            raise ValueError(f"Language key exceeds the {LANGUAGE_KEY_MAX_CHARS:,}-character safety limit.")
        if schema_version == 1:
            if not isinstance(raw_value, str):
                raise ValueError(
                    f"Version-1 translation for {key!r} must be a string."
                )
            value = raw_value
            if not value.strip():
                continue
            if len(value) > LANGUAGE_VALUE_MAX_CHARS:
                raise ValueError(
                    f"Translation for {key!r} exceeds the "
                    f"{LANGUAGE_VALUE_MAX_CHARS:,}-character safety limit."
                )
            translations[key] = validate_translation_entry(
                key,
                value,
                require_plural_other=False,
            )
            continue
        value = _coerce_v2_entry(key, raw_value)
        if value is None:
            continue
        leaves = (value,) if isinstance(value, str) else tuple(value.values())
        if any(len(leaf) > LANGUAGE_VALUE_MAX_CHARS for leaf in leaves):
            raise ValueError(
                f"Translation for {key!r} exceeds the "
                f"{LANGUAGE_VALUE_MAX_CHARS:,}-character safety limit."
            )
        translations[key] = value
    if translation_leaf_count(translations) > LANGUAGE_TRANSLATION_MAX_COUNT:
        raise ValueError(
            f"Language file exceeds the {LANGUAGE_TRANSLATION_MAX_COUNT:,}-translation safety limit."
        )
    return code, name, translations


def load_language_file(
    path: Path,
    *,
    stop_event: threading.Event | None = None,
    max_bytes: int = LANGUAGE_FILE_MAX_BYTES,
) -> tuple[str, str, dict[str, TranslationEntry]]:
    raw = read_file_bytes_cancellable(path, stop_event=stop_event, max_bytes=max_bytes)
    raise_if_cancelled(stop_event, "Language file read cancelled.")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Language file is not valid UTF-8 JSON: {exc}") from exc
    return coerce_translation_payload(payload)


def language_file_payload(
    *,
    language_code: str,
    language_name: str,
    translations: Mapping[str, TranslationEntry],
) -> dict[str, Any]:
    if len(translations) > LANGUAGE_TRANSLATION_MAX_COUNT:
        raise ValueError(f"Language output exceeds the {LANGUAGE_TRANSLATION_MAX_COUNT:,}-translation safety limit.")
    clean_translations: dict[str, TranslationEntry] = {}
    for raw_key, raw_value in translations.items():
        key = str(raw_key)
        if not key or len(key) > LANGUAGE_KEY_MAX_CHARS:
            raise ValueError(f"Language key exceeds the {LANGUAGE_KEY_MAX_CHARS:,}-character safety limit.")
        if isinstance(raw_value, str):
            value: TranslationEntry = raw_value
        elif isinstance(raw_value, Mapping):
            value = {str(category): str(text) for category, text in raw_value.items()}
        else:
            raise ValueError(
                f"Translation for {key!r} must be a string or plural-category object."
            )
        value = validate_translation_entry(
            key,
            value,
            require_plural_other=False,
        )
        leaves = (value,) if isinstance(value, str) else tuple(value.values())
        if any(len(leaf) > LANGUAGE_VALUE_MAX_CHARS for leaf in leaves):
            raise ValueError(
                f"Translation for {key!r} exceeds the "
                f"{LANGUAGE_VALUE_MAX_CHARS:,}-character safety limit."
            )
        clean_translations[key] = value
    if translation_leaf_count(clean_translations) > LANGUAGE_TRANSLATION_MAX_COUNT:
        raise ValueError(
            f"Language output exceeds the {LANGUAGE_TRANSLATION_MAX_COUNT:,}-translation safety limit."
        )
    return {
        "schema_version": LANGUAGE_SCHEMA_VERSION,
        "language_code": str(language_code),
        "language_name": str(language_name),
        "warning": LANGUAGE_WARNING,
        "translations": {
            key: (
                dict(sorted(value.items()))
                if isinstance(value, dict)
                else value
            )
            for key, value in sorted(clean_translations.items())
        },
    }


def write_language_file(
    path: Path,
    *,
    language_code: str,
    language_name: str,
    translations: Mapping[str, TranslationEntry],
    stop_event: threading.Event | None = None,
) -> None:
    payload = language_file_payload(
        language_code=language_code,
        language_name=language_name,
        translations=translations,
    )
    encoded = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    if len(encoded) > LANGUAGE_FILE_MAX_BYTES:
        raise ValueError(f"Language output exceeds the {LANGUAGE_FILE_MAX_BYTES:,}-byte safety limit.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            for offset in range(0, len(encoded), 1024 * 1024):
                raise_if_cancelled(stop_event, "Language file write cancelled.")
                handle.write(encoded[offset : offset + 1024 * 1024])
            handle.flush()
            os.fsync(handle.fileno())
        raise_if_cancelled(stop_event, "Language file write cancelled.")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "LANGUAGE_FILE_MAX_BYTES",
    "LANGUAGE_SCHEMA_VERSION",
    "LANGUAGE_KEY_MAX_CHARS",
    "LANGUAGE_TRANSLATION_MAX_COUNT",
    "LANGUAGE_VALUE_MAX_CHARS",
    "LANGUAGE_WARNING",
    "coerce_translation_payload",
    "language_file_payload",
    "load_language_file",
    "safe_language_code",
    "write_language_file",
]
