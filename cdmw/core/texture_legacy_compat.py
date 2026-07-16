from __future__ import annotations

import warnings
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any


OBSOLETE_CONFIG_KEY = "texconv_path"
OBSOLETE_SETTINGS_KEY = "paths/texconv_path"
OBSOLETE_CHAIN_TOKEN = "${texconv_path}"


def warn_obsolete_texture_argument(argument_name: str = OBSOLETE_CONFIG_KEY) -> None:
    warnings.warn(
        f"{argument_name} is obsolete and ignored; CDMW now uses the bundled native texture backend.",
        DeprecationWarning,
        stacklevel=3,
    )


def resolve_deprecated_preview_source(
    source_or_obsolete_backend: Path | str | None,
    source_path: Path | str | None,
) -> Path:
    if source_path is None:
        if source_or_obsolete_backend is None:
            raise TypeError("DDS source path is required")
        return Path(source_or_obsolete_backend)
    warn_obsolete_texture_argument()
    return Path(source_path)


def discard_obsolete_config_values(payload: MutableMapping[str, Any]) -> None:
    payload.pop(OBSOLETE_CONFIG_KEY, None)
    paths = payload.get("paths")
    if isinstance(paths, MutableMapping):
        paths.pop(OBSOLETE_CONFIG_KEY, None)


def sanitized_profile_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload)
    discard_obsolete_config_values(sanitized)
    config = sanitized.get("config")
    if isinstance(config, Mapping):
        config_copy = dict(config)
        discard_obsolete_config_values(config_copy)
        sanitized["config"] = config_copy
    settings = sanitized.get("settings")
    if isinstance(settings, Mapping):
        settings_copy = {
            str(key): value
            for key, value in settings.items()
            if str(key) != OBSOLETE_SETTINGS_KEY
        }
        sanitized["settings"] = settings_copy
    return sanitized


def obsolete_chain_token_error(text: str) -> str:
    if OBSOLETE_CHAIN_TOKEN not in str(text or ""):
        return ""
    return (
        f"{OBSOLETE_CHAIN_TOKEN} is obsolete. Remove it from the chaiNNer override; "
        "texture conversion is handled by the bundled native backend."
    )


__all__ = [
    "OBSOLETE_CHAIN_TOKEN",
    "OBSOLETE_CONFIG_KEY",
    "OBSOLETE_SETTINGS_KEY",
    "discard_obsolete_config_values",
    "obsolete_chain_token_error",
    "resolve_deprecated_preview_source",
    "sanitized_profile_mapping",
    "warn_obsolete_texture_argument",
]
