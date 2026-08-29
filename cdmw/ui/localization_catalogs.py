"""Compatibility exports for packaged UI localization catalogs."""

from __future__ import annotations

from cdmw.ui.localization_catalogs_v2 import (
    BUILTIN_LANGUAGES,
    SOURCE_STRING_CATALOGUE,
    _FALLBACK_EXACT_TRANSLATIONS,
    _FALLBACK_WORD_TRANSLATIONS,
    builtin_translation_entries,
    load_builtin_catalog,
    localization_resource_root,
    source_template_fields,
    template_literals,
    translation_catalog_hash,
)

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
