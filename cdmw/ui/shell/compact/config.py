"""Saved-setting contracts for the optional compact workspace shell."""

from __future__ import annotations

from cdmw.constants import DEFAULT_UI_THEME
from cdmw.ui.themes import UI_THEME_SCHEMES


SHELL_VARIANT_SETTING = "ui/shell_variant"
LEGACY_SHELL_VARIANT = "legacy"
COMPACT_SHELL_VARIANT = "compact_rail"
SHELL_VARIANTS = (COMPACT_SHELL_VARIANT,)

# Compatibility names for settings written before Classic and Compact shared one theme.
COMPACT_SHELL_THEME_SETTING = "appearance/compact_shell_theme"
DEFAULT_COMPACT_SHELL_THEME = DEFAULT_UI_THEME

# Classic Workspace is retired; Compact Workspace is the single active shell.
APPLICATION_LAYOUT_SELECTOR_EXPOSED = False


def normalize_shell_variant(value: object) -> str:
    _ = value
    return COMPACT_SHELL_VARIANT


def read_shell_variant(settings: object) -> str:
    raw = settings.value(SHELL_VARIANT_SETTING, None)  # type: ignore[attr-defined]
    if raw is not None and str(raw).strip().lower() != COMPACT_SHELL_VARIANT:
        setter = getattr(settings, "setValue", None)
        if callable(setter):
            setter(SHELL_VARIANT_SETTING, COMPACT_SHELL_VARIANT)
    return COMPACT_SHELL_VARIANT


def normalize_theme_key(value: object, *, default: str) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate in UI_THEME_SCHEMES else default


def read_classic_theme_key(settings: object) -> str:
    legacy_compact_theme = settings.value(  # type: ignore[attr-defined]
        COMPACT_SHELL_THEME_SETTING,
        DEFAULT_UI_THEME,
    )
    return normalize_theme_key(
        settings.value("appearance/theme", legacy_compact_theme),  # type: ignore[attr-defined]
        default=DEFAULT_UI_THEME,
    )


def read_compact_shell_theme_key(settings: object) -> str:
    """Compatibility wrapper for callers that still use the former name."""

    return read_classic_theme_key(settings)


def active_shell_theme_key(settings: object, shell_variant: object | None = None) -> str:
    _ = shell_variant
    return read_classic_theme_key(settings)


def active_shell_theme_setting(shell_variant: object) -> str:
    _ = shell_variant
    return "appearance/theme"


def theme_change_field(setting_key: object) -> str:
    return str(setting_key or "").rsplit("/", 1)[-1].rsplit("_", 1)[-1]


def compact_category_expanded_setting(category: str) -> str:
    return f"ui/compact_rail/categories/{str(category).strip().lower()}/expanded"


__all__ = [
    "APPLICATION_LAYOUT_SELECTOR_EXPOSED",
    "COMPACT_SHELL_THEME_SETTING",
    "COMPACT_SHELL_VARIANT",
    "DEFAULT_COMPACT_SHELL_THEME",
    "LEGACY_SHELL_VARIANT",
    "SHELL_VARIANT_SETTING",
    "SHELL_VARIANTS",
    "active_shell_theme_key",
    "active_shell_theme_setting",
    "compact_category_expanded_setting",
    "normalize_shell_variant",
    "normalize_theme_key",
    "read_classic_theme_key",
    "read_compact_shell_theme_key",
    "read_shell_variant",
    "theme_change_field",
]
