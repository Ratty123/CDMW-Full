"""Pure language identity, plural, and translation-entry contracts."""

from __future__ import annotations

import math
import re
import string
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Mapping, TypeAlias


PLURAL_CATEGORIES = ("zero", "one", "two", "few", "many", "other")
_PLURAL_CATEGORY_SET = frozenset(PLURAL_CATEGORIES)
_SAFE_LANGUAGE_CODE_RE = re.compile(r"[^0-9A-Za-z_-]+")


@dataclass(frozen=True, slots=True)
class BuiltinLanguage:
    code: str
    display_name: str
    plural_rule: str
    qt_locale: str
    font_families: tuple[str, ...] = ()


BUILTIN_LANGUAGES = (
    BuiltinLanguage("en", "English", "one_other", "en_US"),
    BuiltinLanguage("de", "Deutsch", "one_other", "de_DE"),
    BuiltinLanguage("es-ES", "Español (España)", "spanish_million", "es_ES"),
    BuiltinLanguage("es-419", "Español (Latinoamérica)", "spanish_million", "es_419"),
    BuiltinLanguage("fr", "Français", "zero_one_million", "fr_FR"),
    BuiltinLanguage("it", "Italiano", "italian_million", "it_IT"),
    BuiltinLanguage("pt-BR", "Português (Brasil)", "zero_one_million", "pt_BR"),
    BuiltinLanguage("pl", "Polski", "polish", "pl_PL"),
    BuiltinLanguage("ru", "Русский", "russian", "ru_RU"),
    BuiltinLanguage("tr", "Türkçe", "other", "tr_TR"),
    BuiltinLanguage(
        "ja",
        "日本語",
        "other",
        "ja_JP",
        ("Yu Gothic UI", "Meiryo UI", "Meiryo"),
    ),
    BuiltinLanguage(
        "ko",
        "한국어",
        "other",
        "ko_KR",
        ("Malgun Gothic", "Malgun Gothic Semilight"),
    ),
    BuiltinLanguage(
        "zh-Hans",
        "简体中文",
        "other",
        "zh_CN",
        ("Microsoft YaHei UI", "Microsoft YaHei"),
    ),
    BuiltinLanguage(
        "zh-Hant",
        "繁體中文",
        "other",
        "zh_TW",
        ("Microsoft JhengHei UI", "Microsoft JhengHei"),
    ),
)

BUILTIN_LANGUAGE_CODES = tuple(language.code for language in BUILTIN_LANGUAGES)
BUILTIN_LANGUAGE_BY_CODE = MappingProxyType(
    {language.code: language for language in BUILTIN_LANGUAGES}
)

_CANONICAL_BY_CASEFOLD = {
    language.code.casefold(): language.code for language in BUILTIN_LANGUAGES
}
_LANGUAGE_ALIASES = {
    "es": "es-ES",
    "es-es": "es-ES",
    "es-419": "es-419",
    "pt-br": "pt-BR",
    "zh-cn": "zh-Hans",
    "zh-sg": "zh-Hans",
    "zh-hans": "zh-Hans",
    "zh-tw": "zh-Hant",
    "zh-hk": "zh-Hant",
    "zh-mo": "zh-Hant",
    "zh-hant": "zh-Hant",
}

TranslationEntry: TypeAlias = str | dict[str, str]
FrozenTranslationEntry: TypeAlias = str | tuple[tuple[str, str], ...]


def sanitize_language_code(code: object) -> str:
    """Return a bounded filesystem-safe BCP-47-like code."""

    text = str(code or "custom").strip().replace("_", "-")[:64]
    text = _SAFE_LANGUAGE_CODE_RE.sub("", text).strip("-")
    return text or "custom"


def canonical_language_code(code: object) -> str:
    """Normalize built-in aliases while preserving distinct custom identities."""

    safe = sanitize_language_code(code)
    folded = safe.casefold()
    alias = _LANGUAGE_ALIASES.get(folded)
    if alias:
        return alias
    canonical = _CANONICAL_BY_CASEFOLD.get(folded)
    if canonical:
        return canonical
    return folded


def language_for_code(code: object) -> BuiltinLanguage | None:
    return BUILTIN_LANGUAGE_BY_CODE.get(canonical_language_code(code))


def language_name_for_code(code: object) -> str:
    language = language_for_code(code)
    return language.display_name if language is not None else str(code or "Custom")


def plural_rule_for_code(code: object) -> str:
    language = language_for_code(code)
    return language.plural_rule if language is not None else "one_other"


def required_plural_categories(code: object) -> frozenset[str]:
    rule = plural_rule_for_code(code)
    if rule == "other":
        return frozenset({"other"})
    if rule == "one_other":
        return frozenset({"one", "other"})
    if rule in {"spanish_million", "italian_million"}:
        return frozenset({"one", "many", "other"})
    if rule == "zero_one_million":
        return frozenset({"one", "many", "other"})
    if rule in {"polish", "russian"}:
        return frozenset({"one", "few", "many", "other"})
    raise ValueError(f"Unsupported plural rule: {rule}")


def _decimal_parts(value: int | float | Decimal) -> tuple[Decimal, int, int]:
    try:
        number = Decimal(str(value)).copy_abs()
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Plural count must be numeric: {value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"Plural count must be finite: {value!r}")
    exponent = number.as_tuple().exponent
    visible_fraction_digits = max(0, -int(exponent))
    integer = int(number.to_integral_value(rounding="ROUND_FLOOR"))
    return number, integer, visible_fraction_digits


def plural_category(code: object, count: int | float | Decimal) -> str:
    """Select a CLDR-compatible cardinal category for a supported UI locale."""

    number, integer, fraction_digits = _decimal_parts(count)
    rule = plural_rule_for_code(code)
    if rule == "other":
        return "other"
    if rule == "one_other":
        return "one" if number == 1 and fraction_digits == 0 else "other"
    if rule == "spanish_million":
        if number == 1:
            return "one"
        if integer != 0 and integer % 1_000_000 == 0 and fraction_digits == 0:
            return "many"
        return "other"
    if rule == "italian_million":
        if integer == 1 and fraction_digits == 0:
            return "one"
        if integer != 0 and integer % 1_000_000 == 0 and fraction_digits == 0:
            return "many"
        return "other"
    if rule == "zero_one_million":
        if integer in {0, 1}:
            return "one"
        if integer != 0 and integer % 1_000_000 == 0 and fraction_digits == 0:
            return "many"
        return "other"
    if fraction_digits != 0:
        return "other"
    mod10 = integer % 10
    mod100 = integer % 100
    if rule == "polish":
        if integer == 1:
            return "one"
        if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
            return "few"
        if integer != 1 and (
            mod10 in {0, 1}
            or 5 <= mod10 <= 9
            or 12 <= mod100 <= 14
        ):
            return "many"
        return "other"
    if rule == "russian":
        if mod10 == 1 and mod100 != 11:
            return "one"
        if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
            return "few"
        if mod10 == 0 or 5 <= mod10 <= 9 or 11 <= mod100 <= 14:
            return "many"
        return "other"
    raise ValueError(f"Unsupported plural rule: {rule}")


def placeholder_names(template: str) -> frozenset[str]:
    names: set[str] = set()
    try:
        parsed = string.Formatter().parse(str(template))
        for _literal, field_name, _format_spec, _conversion in parsed:
            if field_name is None:
                continue
            normalized = str(field_name).strip()
            if not normalized or normalized.isdigit():
                raise ValueError("Translation templates require named placeholders.")
            root = re.split(r"[.[]", normalized, maxsplit=1)[0]
            if not root:
                raise ValueError(f"Invalid translation placeholder: {field_name!r}")
            names.add(root)
    except ValueError:
        raise
    return frozenset(names)


def validate_translation_entry(
    source: str,
    entry: object,
    *,
    require_plural_other: bool,
) -> TranslationEntry:
    """Validate one version-2 value and return a detached normalized entry."""

    source_placeholders = placeholder_names(source)
    if isinstance(entry, str):
        if not entry.strip():
            raise ValueError(f"Translation for {source!r} is blank.")
        if placeholder_names(entry) != source_placeholders:
            raise ValueError(f"Translation placeholders do not match {source!r}.")
        return entry
    if not isinstance(entry, Mapping):
        raise ValueError(f"Translation for {source!r} must be a string or plural object.")
    plural: dict[str, str] = {}
    for raw_category, raw_value in entry.items():
        category = str(raw_category).strip().lower()
        if category not in _PLURAL_CATEGORY_SET:
            raise ValueError(f"Unknown plural category {raw_category!r} for {source!r}.")
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ValueError(f"Plural translation {category!r} for {source!r} is blank.")
        if placeholder_names(raw_value) != source_placeholders:
            raise ValueError(
                f"Plural translation {category!r} placeholders do not match {source!r}."
            )
        plural[category] = raw_value
    if not plural:
        raise ValueError(f"Plural translation for {source!r} has no categories.")
    if require_plural_other and "other" not in plural:
        raise ValueError(f"Plural translation for {source!r} requires an 'other' category.")
    return plural


def freeze_translation_entry(entry: TranslationEntry) -> FrozenTranslationEntry:
    if isinstance(entry, str):
        return entry
    return tuple(sorted((str(category), str(value)) for category, value in entry.items()))


def thaw_translation_entry(entry: FrozenTranslationEntry | object) -> TranslationEntry:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, Mapping):
        return {str(category): str(value) for category, value in entry.items()}
    if isinstance(entry, (tuple, list)):
        return {str(category): str(value) for category, value in entry}
    raise ValueError(f"Unsupported frozen translation entry: {entry!r}")


def translation_leaf_count(translations: Mapping[str, TranslationEntry]) -> int:
    return sum(1 if isinstance(value, str) else len(value) for value in translations.values())


def finite_number(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


__all__ = [
    "BUILTIN_LANGUAGES",
    "BUILTIN_LANGUAGE_BY_CODE",
    "BUILTIN_LANGUAGE_CODES",
    "BuiltinLanguage",
    "FrozenTranslationEntry",
    "PLURAL_CATEGORIES",
    "TranslationEntry",
    "canonical_language_code",
    "finite_number",
    "freeze_translation_entry",
    "language_for_code",
    "language_name_for_code",
    "placeholder_names",
    "plural_category",
    "plural_rule_for_code",
    "required_plural_categories",
    "sanitize_language_code",
    "thaw_translation_entry",
    "translation_leaf_count",
    "validate_translation_entry",
]
