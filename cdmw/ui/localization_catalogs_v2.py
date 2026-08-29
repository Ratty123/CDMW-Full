"""Packaged UTF-8 UI catalogs for the built-in interface languages."""

from __future__ import annotations

import hashlib
import json
import string
import sys
from collections import OrderedDict
from collections.abc import Iterable, Iterator, Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from cdmw.domain.localization import (
    BUILTIN_LANGUAGES as BUILTIN_LANGUAGE_SPECS,
    TranslationEntry,
    placeholder_names,
    required_plural_categories,
    validate_translation_entry,
)


def localization_resource_root() -> Path:
    frozen_root = str(getattr(sys, "_MEIPASS", "") or "").strip()
    if frozen_root:
        return Path(frozen_root) / "cdmw" / "resources" / "localization"
    return Path(__file__).resolve().parents[1] / "resources" / "localization"


def _read_catalog(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Packaged UI language catalog is missing: {path.name}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read packaged UI language catalog {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Packaged UI language catalog {path.name} is not a JSON object.")
    return payload


def _normalized_entries(
    code: str,
    payload: Mapping[str, object],
) -> dict[str, TranslationEntry]:
    if int(payload.get("schema_version", 0) or 0) != 2:
        raise RuntimeError(f"Built-in UI language {code} must use schema_version 2.")
    raw = payload.get("translations")
    if not isinstance(raw, dict):
        raise RuntimeError(f"Built-in UI language {code} has no translations object.")
    entries: dict[str, TranslationEntry] = {}
    for raw_source, raw_entry in raw.items():
        source = str(raw_source)
        try:
            entries[source] = validate_translation_entry(
                source,
                raw_entry,
                require_plural_other=isinstance(raw_entry, Mapping),
            )
        except ValueError as exc:
            raise RuntimeError(f"Invalid built-in UI translation {code}/{source!r}: {exc}") from exc
    return entries


_BUILTIN_LANGUAGE_SPEC_BY_CODE = {
    spec.code: spec
    for spec in BUILTIN_LANGUAGE_SPECS
}
_loaded_builtin_catalog_codes: set[str] = set()


@lru_cache(maxsize=None)
def load_builtin_catalog(code: str) -> dict[str, object]:
    normalized_code = str(code)
    spec = _BUILTIN_LANGUAGE_SPEC_BY_CODE.get(normalized_code)
    if spec is None:
        raise KeyError(normalized_code)
    root = localization_resource_root()
    path = root / f"{spec.code}.json"
    payload = _read_catalog(path)
    payload_code = str(payload.get("language_code", "") or "")
    if payload_code != spec.code:
        raise RuntimeError(
            f"Built-in UI catalog {path.name} declares {payload_code!r}, expected {spec.code!r}."
        )
    entries = _normalized_entries(spec.code, payload)
    for source, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        missing_categories = required_plural_categories(spec.code) - set(entry)
        if missing_categories:
            raise RuntimeError(
                f"Built-in UI plural {spec.code}/{source!r} is missing "
                f"{sorted(missing_categories)!r}."
            )
    _loaded_builtin_catalog_codes.add(spec.code)
    return {
        "language_name": spec.display_name,
        "translations": entries,
        "plural_rule": spec.plural_rule,
        "qt_locale": spec.qt_locale,
        "font_families": spec.font_families,
        "path": path,
    }


class _BuiltinLanguageCatalogs(Mapping[str, dict[str, object]]):
    def __getitem__(self, code: str) -> dict[str, object]:
        return load_builtin_catalog(str(code))

    def __iter__(self) -> Iterator[str]:
        return iter(_BUILTIN_LANGUAGE_SPEC_BY_CODE)

    def __len__(self) -> int:
        return len(_BUILTIN_LANGUAGE_SPEC_BY_CODE)


def _load_builtin_catalogs() -> OrderedDict[str, dict[str, object]]:
    catalogs: OrderedDict[str, dict[str, object]] = OrderedDict()
    expected_keys: frozenset[str] | None = None
    for spec in BUILTIN_LANGUAGE_SPECS:
        catalog = load_builtin_catalog(spec.code)
        entries = catalog["translations"]
        if not isinstance(entries, dict):
            raise RuntimeError(f"Built-in UI language {spec.code} has no translations object.")
        keys = frozenset(entries)
        if expected_keys is None:
            expected_keys = keys
        elif keys != expected_keys:
            missing = sorted(expected_keys - keys)
            extra = sorted(keys - expected_keys)
            detail = []
            if missing:
                detail.append(f"missing {len(missing):,}: {missing[:3]!r}")
            if extra:
                detail.append(f"extra {len(extra):,}: {extra[:3]!r}")
            raise RuntimeError(
                f"Built-in UI catalog {spec.code} does not match English: " + "; ".join(detail)
            )
        catalogs[spec.code] = catalog
    return catalogs


BUILTIN_LANGUAGES: Mapping[str, dict[str, object]] = _BuiltinLanguageCatalogs()
SOURCE_STRING_CATALOGUE = tuple(
    load_builtin_catalog("en")["translations"].keys()  # type: ignore[union-attr]
)

# Compatibility names retained for importers while the heuristic fallback is retired.
_FALLBACK_EXACT_TRANSLATIONS: dict[str, dict[str, str]] = {}
_FALLBACK_WORD_TRANSLATIONS: dict[str, dict[str, str]] = {}


def builtin_translation_entries(code: str) -> Mapping[str, TranslationEntry]:
    payload = BUILTIN_LANGUAGES.get(str(code))
    if not isinstance(payload, dict):
        return MappingProxyType({})
    translations = payload.get("translations")
    if not isinstance(translations, dict):
        return MappingProxyType({})
    return MappingProxyType(translations)


def translation_catalog_hash(
    code: str,
    entries: Mapping[str, TranslationEntry] | None = None,
    *,
    keys: Iterable[str] | None = None,
) -> str:
    source_entries = entries if entries is not None else builtin_translation_entries(code)
    selected_keys = tuple(sorted(str(key) for key in (keys if keys is not None else source_entries)))
    payload = {
        key: source_entries[key]
        for key in selected_keys
        if key in source_entries
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_template_fields(source: str) -> tuple[str, ...]:
    return tuple(sorted(placeholder_names(source)))


def template_literals(source: str) -> tuple[str, ...]:
    return tuple(literal for literal, _field, _spec, _conversion in string.Formatter().parse(source))


__all__ = [
    "BUILTIN_LANGUAGES",
    "SOURCE_STRING_CATALOGUE",
    "_FALLBACK_EXACT_TRANSLATIONS",
    "_FALLBACK_WORD_TRANSLATIONS",
    "builtin_translation_entries",
    "load_builtin_catalog",
    "localization_resource_root",
    "source_template_fields",
    "template_literals",
    "translation_catalog_hash",
]
