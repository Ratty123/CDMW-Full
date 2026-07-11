"""Cached lazy service boundary for Replace Assistant workflows."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    name: ("cdmw.core.replace_assistant", name)
    for name in (
        "ReplaceAssistantArchiveIndex",
        "build_replace_assistant_archive_index",
        "build_replace_assistant_items",
        "build_replace_assistant_package",
        "build_replace_assistant_preview_assets",
        "match_replace_assistant_item_to_archive_entry",
        "match_replace_assistant_item_to_local_original",
        "match_replace_assistant_original",
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
