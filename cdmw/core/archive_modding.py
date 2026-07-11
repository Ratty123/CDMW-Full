"""Cached lazy compatibility facade for archive modding owners."""

from __future__ import annotations

from importlib import import_module

from cdmw.core.archive_modding_compat_exports import ARCHIVE_MODDING_EXPORTS


__all__ = tuple(name for name in ARCHIVE_MODDING_EXPORTS if not name.startswith("_"))


def __getattr__(name: str) -> object:
    try:
        module_name, attribute_name = ARCHIVE_MODDING_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(ARCHIVE_MODDING_EXPORTS))
