"""Cached lazy service boundary for cancellable text-search workflows."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    name: ("cdmw.core.text_search", name)
    for name in (
        "DEFAULT_TEXT_SEARCH_EXTENSIONS",
        "TextSearchPreview",
        "TextSearchResult",
        "TextSearchRunStats",
        "export_text_search_results",
        "load_text_search_preview",
        "normalize_text_search_extensions",
        "search_archive_text_entries",
        "search_loose_text_files",
    )
}
__all__ = tuple(_EXPORTS)


def __getattr__(name: str) -> object:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
