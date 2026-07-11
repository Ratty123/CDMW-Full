"""Cached lazy service boundary for startup-splash process artifacts."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    name: ("cdmw.core.startup_splash_protocol", name)
    for name in (
        "STARTUP_SPLASH_COMMAND_FILE_ENV",
        "cleanup_startup_splash_artifacts",
        "write_startup_splash_payload",
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
