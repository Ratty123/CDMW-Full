"""Validate every built-in CDMW UI localization catalogue as one contract."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cdmw.domain.localization import (  # noqa: E402
    BUILTIN_LANGUAGES,
    TranslationEntry,
    required_plural_categories,
    validate_translation_entry,
)


RESOURCE_ROOT = ROOT / "cdmw" / "resources" / "localization"
MANIFEST_PATH = RESOURCE_ROOT / "source_manifest.json"
SOURCE_IDENTICAL_PATH = RESOURCE_ROOT / "source_identical_terms.json"
SOURCE_IDENTICAL_REASON = (
    "Reviewed as a product name, technical identifier, file-format term, "
    "or intentionally language-neutral interface label."
)
_TAG_RE = re.compile(r"</?\s*([A-Za-z][A-Za-z0-9]*)\b[^>]*>")
_HTML_ENTITY_RE = re.compile(r"&(?:[A-Za-z][A-Za-z0-9]+|#[0-9]+|#x[0-9A-Fa-f]+);")
_FILE_FILTER_SEGMENT_RE = re.compile(
    r"^(?P<label>.*?)(?P<patterns>\s*\([^()]*\*[^()]*\)\s*)$"
)
_ENCODING_DAMAGE_MARKERS = (
    "\ufffd",
    "â€",
    "Ãƒ",
    "Ã©",
    "Ã±",
    "Ð",
)
_QUESTION_MARK_DAMAGE_RE = re.compile(r"\?{3,}|[^\W\d_]\?[^\W\d_]", re.UNICODE)
_LINE_BREAK_RUN_RE = re.compile(r"(?:\r\n|\r|\n)+")


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Missing localization resource: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid UTF-8 JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Localization resource must be an object: {path}")
    return payload


def _catalog_entries(
    path: Path,
    expected_code: str,
    expected_name: str,
) -> dict[str, TranslationEntry]:
    payload = _read_json(path)
    if payload.get("schema_version") != 2:
        raise ValueError(f"{path.name}: schema_version must be 2")
    if payload.get("language_code") != expected_code:
        raise ValueError(
            f"{path.name}: language_code is {payload.get('language_code')!r}, "
            f"expected {expected_code!r}"
        )
    if payload.get("language_name") != expected_name:
        raise ValueError(
            f"{path.name}: language_name is {payload.get('language_name')!r}, "
            f"expected {expected_name!r}"
        )
    raw = payload.get("translations")
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name}: translations must be an object")
    entries: dict[str, TranslationEntry] = {}
    for source, value in raw.items():
        if not isinstance(source, str) or not source:
            raise ValueError(f"{path.name}: translation keys must be nonempty strings")
        try:
            entries[source] = validate_translation_entry(
                source,
                value,
                require_plural_other=isinstance(value, Mapping),
            )
        except ValueError as exc:
            raise ValueError(f"{path.name}/{source!r}: {exc}") from exc
        entry = entries[source]
        if isinstance(entry, dict):
            missing = required_plural_categories(expected_code) - set(entry)
            if missing:
                raise ValueError(
                    f"{path.name}/{source!r}: missing plural categories "
                    f"{sorted(missing)!r}"
                )
    return entries


def _leaf_values(entry: TranslationEntry) -> tuple[str, ...]:
    return (entry,) if isinstance(entry, str) else tuple(entry.values())


def _tag_signature(text: str) -> Counter[str]:
    return Counter(match.group(1).casefold() for match in _TAG_RE.finditer(text))


def _accelerator_count(text: str) -> int:
    without_entities = html.unescape(_HTML_ENTITY_RE.sub("", text))
    count = 0
    index = 0
    while index < len(without_entities):
        if without_entities[index] != "&":
            index += 1
            continue
        if index + 1 < len(without_entities) and without_entities[index + 1] == "&":
            index += 2
            continue
        if (
            index + 1 < len(without_entities)
            and not without_entities[index + 1].isspace()
            and without_entities[index + 1].isalnum()
        ):
            count += 1
        index += 1
    return count


def _has_encoding_damage(source: str, value: str) -> bool:
    if any(marker in value for marker in _ENCODING_DAMAGE_MARKERS):
        return True
    return (
        _QUESTION_MARK_DAMAGE_RE.search(value) is not None
        and _QUESTION_MARK_DAMAGE_RE.search(source) is None
    )


def _preserves_layout_whitespace(source: str, value: str) -> bool:
    source_leading = re.match(r"^\s*", source)
    value_leading = re.match(r"^\s*", value)
    source_trailing = re.search(r"\s*$", source)
    value_trailing = re.search(r"\s*$", value)
    return (
        source_leading is not None
        and value_leading is not None
        and source_leading.group(0) == value_leading.group(0)
        and source_trailing is not None
        and value_trailing is not None
        and source_trailing.group(0) == value_trailing.group(0)
        and _LINE_BREAK_RUN_RE.findall(source)
        == _LINE_BREAK_RUN_RE.findall(value)
    )


def _source_identical_payload(
    catalogs: Mapping[str, Mapping[str, TranslationEntry]],
) -> dict[str, object]:
    return {
        "schema": "cdmw_ui_source_identical_terms_v1",
        "entries": {
            code: {
                source: SOURCE_IDENTICAL_REASON
                for source, entry in sorted(entries.items())
                if isinstance(entry, str) and entry == source
            }
            for code, entries in catalogs.items()
            if code != "en"
        },
    }


def validate_catalogs() -> tuple[int, int]:
    manifest = _read_json(MANIFEST_PATH)
    raw_manifest_entries = manifest.get("entries")
    if not isinstance(raw_manifest_entries, list):
        raise ValueError("source_manifest.json: entries must be an array")
    manifest_keys = {
        str(entry.get("key"))
        for entry in raw_manifest_entries
        if isinstance(entry, dict) and isinstance(entry.get("key"), str)
    }

    catalogs: dict[str, dict[str, TranslationEntry]] = {}
    for language in BUILTIN_LANGUAGES:
        catalogs[language.code] = _catalog_entries(
            RESOURCE_ROOT / f"{language.code}.json",
            language.code,
            language.display_name,
        )
    english_keys = set(catalogs["en"])
    if english_keys != manifest_keys:
        raise ValueError(
            "English catalog and source manifest differ: "
            f"missing={len(manifest_keys - english_keys)}, "
            f"extra={len(english_keys - manifest_keys)}"
        )
    for code, entries in catalogs.items():
        if set(entries) != english_keys:
            raise ValueError(
                f"{code}: catalog key parity failed: "
                f"missing={len(english_keys - set(entries))}, "
                f"extra={len(set(entries) - english_keys)}"
            )
        for source, entry in entries.items():
            source_tags = _tag_signature(source)
            source_accelerators = _accelerator_count(source)
            for value in _leaf_values(entry):
                if _has_encoding_damage(source, value):
                    raise ValueError(
                        f"{code}/{source!r}: translation contains encoding damage"
                    )
                if not _preserves_layout_whitespace(source, value):
                    raise ValueError(
                        f"{code}/{source!r}: layout whitespace changed"
                    )
                if _tag_signature(value) != source_tags:
                    raise ValueError(
                        f"{code}/{source!r}: rich-text tag signature changed"
                    )
                if _accelerator_count(value) != source_accelerators:
                    raise ValueError(
                        f"{code}/{source!r}: accelerator marker count changed"
                    )
                source_filter = _FILE_FILTER_SEGMENT_RE.fullmatch(source)
                if source_filter is not None:
                    translated_filter = _FILE_FILTER_SEGMENT_RE.fullmatch(value)
                    if (
                        translated_filter is None
                        or translated_filter.group("patterns").strip()
                        != source_filter.group("patterns").strip()
                    ):
                        raise ValueError(
                            f"{code}/{source!r}: file-filter glob changed"
                        )

    expected_identical = _source_identical_payload(catalogs)
    actual_identical = _read_json(SOURCE_IDENTICAL_PATH)
    if actual_identical != expected_identical:
        raise ValueError(
            "source_identical_terms.json is stale; review source-identical terms "
            "and regenerate it explicitly."
        )
    return len(catalogs), len(english_keys)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write-source-identical",
        action="store_true",
        help="Write the reviewed source-identical-term inventory.",
    )
    args = parser.parse_args()
    if args.write_source_identical:
        catalogs = {
            language.code: _catalog_entries(
                RESOURCE_ROOT / f"{language.code}.json",
                language.code,
                language.display_name,
            )
            for language in BUILTIN_LANGUAGES
        }
        SOURCE_IDENTICAL_PATH.write_text(
            json.dumps(
                _source_identical_payload(catalogs),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"Wrote {SOURCE_IDENTICAL_PATH.relative_to(ROOT)}")
        return 0
    language_count, source_count = validate_catalogs()
    print(
        f"Validated {language_count} built-in UI languages "
        f"with {source_count:,} keys each."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
