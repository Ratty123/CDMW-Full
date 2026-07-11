"""Cached lazy compatibility facade for archive owners."""

from __future__ import annotations

from importlib import import_module

from cdmw.core.archive_compat_exports import ARCHIVE_EXPORTS


__all__ = tuple(name for name in ARCHIVE_EXPORTS if not name.startswith("_"))


def __getattr__(name: str) -> object:
    try:
        module_name, attribute_name = ARCHIVE_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(ARCHIVE_EXPORTS))
