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
from cdmw.domain.cancellation import raise_if_cancelled


LANGUAGE_WARNING = (
    "Translate only the values in the translations object. Keep the English keys unchanged. "
    "Longer text can make buttons, tabs, and dialogs look crowded or clipped."
)
LANGUAGE_FILE_MAX_BYTES = 16 * 1024 * 1024
LANGUAGE_TRANSLATION_MAX_COUNT = 100_000
LANGUAGE_KEY_MAX_CHARS = 4_000
LANGUAGE_VALUE_MAX_CHARS = 100_000


def safe_language_code(code: object) -> str:
    return "".join(ch for ch in str(code or "custom").strip().lower()[:64] if ch.isalnum() or ch in {"-", "_"}) or "custom"


def coerce_translation_payload(payload: object) -> tuple[str, str, dict[str, str]]:
    if not isinstance(payload, dict):
        raise ValueError("Language file must be a JSON object.")
    code = str(payload.get("language_code") or payload.get("code") or "custom").strip() or "custom"
    name = str(payload.get("language_name") or payload.get("name") or code).strip() or code
    translations_raw = payload.get("translations", payload)
    if not isinstance(translations_raw, dict):
        raise ValueError("Language file must contain a translations object.")
    if len(translations_raw) > LANGUAGE_TRANSLATION_MAX_COUNT:
        raise ValueError(f"Language file exceeds the {LANGUAGE_TRANSLATION_MAX_COUNT:,}-translation safety limit.")
    translations: dict[str, str] = {}
    for raw_key, raw_value in translations_raw.items():
        if not isinstance(raw_key, str):
            continue
        key = str(raw_key)
        value = str(raw_value)
        if not value.strip():
            continue
        if not key or len(key) > LANGUAGE_KEY_MAX_CHARS:
            raise ValueError(f"Language key exceeds the {LANGUAGE_KEY_MAX_CHARS:,}-character safety limit.")
        if len(value) > LANGUAGE_VALUE_MAX_CHARS:
            raise ValueError(f"Translation for {key!r} exceeds the {LANGUAGE_VALUE_MAX_CHARS:,}-character safety limit.")
        translations[key] = value
    return code, name, translations


def load_language_file(
    path: Path,
    *,
    stop_event: threading.Event | None = None,
    max_bytes: int = LANGUAGE_FILE_MAX_BYTES,
) -> tuple[str, str, dict[str, str]]:
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
    translations: Mapping[str, str],
) -> dict[str, Any]:
    if len(translations) > LANGUAGE_TRANSLATION_MAX_COUNT:
        raise ValueError(f"Language output exceeds the {LANGUAGE_TRANSLATION_MAX_COUNT:,}-translation safety limit.")
    clean_translations: dict[str, str] = {}
    for raw_key, raw_value in translations.items():
        key, value = str(raw_key), str(raw_value)
        if not key or len(key) > LANGUAGE_KEY_MAX_CHARS:
            raise ValueError(f"Language key exceeds the {LANGUAGE_KEY_MAX_CHARS:,}-character safety limit.")
        if len(value) > LANGUAGE_VALUE_MAX_CHARS:
            raise ValueError(f"Translation for {key!r} exceeds the {LANGUAGE_VALUE_MAX_CHARS:,}-character safety limit.")
        clean_translations[key] = value
    return {
        "language_code": str(language_code),
        "language_name": str(language_name),
        "warning": LANGUAGE_WARNING,
        "translations": dict(sorted(clean_translations.items())),
    }


def write_language_file(
    path: Path,
    *,
    language_code: str,
    language_name: str,
    translations: Mapping[str, str],
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
