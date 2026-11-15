"""One store for the preview settings every viewport shares.

Browse Archives, preview dialogs, Create New Item and the Mesh Editor read the
same `preview/` keys and follow each other's changes while open. A viewport may
hold a local value only when the user chose one there explicitly (for example
Create New Item's Dark mode); it is shown as local and can return to the global
settings.
"""

from __future__ import annotations

from typing import Mapping, Optional

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication

LIGHTING_PRESETS = ("neutral_studio", "showcase", "dark", "studio_fixed")

#: name -> (settings key, default)
GLOBAL_PREVIEW_SETTINGS: dict[str, tuple[str, object]] = {
    "lighting_preset": ("preview/preview_lighting_preset", "neutral_studio"),
    "shadows": ("preview/preview_shadows", True),
    "ambient_occlusion": ("preview/preview_ambient_occlusion", True),
    "ground": ("preview/preview_ground_visible", True),
    "ground_grid": ("preview/preview_ground_grid_visible", True),
    # P4 V3: one view mode and one background for every viewport.
    "view_mode": ("preview/view_mode", "textured"),
    "background_color": ("preview/d3d11_background_color", "#3B3B3B"),
}


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _hex_color(value: object, default: str) -> str:
    text = str(value or "").strip()
    digits = text[1:] if text.startswith("#") else text
    if len(digits) == 6 and all(c in "0123456789abcdefABCDEF" for c in digits):
        return "#" + digits.upper()
    return default


def normalize_preview_settings(values: Mapping[str, object]) -> dict[str, object]:
    """Only known names, with validated values."""

    result: dict[str, object] = {}
    for name, (_key, default) in GLOBAL_PREVIEW_SETTINGS.items():
        if name not in values:
            continue
        value = values[name]
        if name == "lighting_preset":
            text = str(value or "").strip().lower()
            result[name] = text if text in LIGHTING_PRESETS else default
        elif name == "view_mode":
            from cdmw.domain.preview_view_modes import shared_view_mode

            result[name] = shared_view_mode(value)
        elif name == "background_color":
            result[name] = _hex_color(value, str(default))
        else:
            result[name] = _as_bool(value, bool(default))
    return result


class PreviewSettingsHub(QObject):
    changed = Signal(object)

    def __init__(self, settings: QSettings, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._last = self._read()

    def _read(self) -> dict[str, object]:
        from cdmw.domain.preview_view_modes import read_view_mode

        raw = {name: self._settings.value(key, default) for name, (key, default) in GLOBAL_PREVIEW_SETTINGS.items()}
        raw["view_mode"] = read_view_mode(self._settings)  # migrates preview/d3d11_view_mode
        return normalize_preview_settings(raw)

    def values(self) -> dict[str, object]:
        return dict(self._last)

    def update(self, **changes: object) -> bool:
        """Store changed global values and tell every viewport."""

        if "background_color" in changes and not _hex_color(changes["background_color"], ""):
            changes = {name: value for name, value in changes.items() if name != "background_color"}
        clean = normalize_preview_settings(changes)
        if not clean:
            return False
        current = self._read()
        if all(current.get(name) == value for name, value in clean.items()):
            self._last = current
            return False
        for name, value in clean.items():
            if name == "view_mode":
                from cdmw.domain.preview_view_modes import write_view_mode

                write_view_mode(self._settings, value)
                continue
            self._settings.setValue(GLOBAL_PREVIEW_SETTINGS[name][0], value)
        self._settings.sync()
        self._last = self._read()
        self.changed.emit(self.values())
        return True

    def refresh(self) -> bool:
        """Re-read after another writer (the Preview Settings dialog) saved."""

        current = self._read()
        if current == self._last:
            return False
        self._last = current
        self.changed.emit(self.values())
        return True


def preview_settings_hub() -> Optional[PreviewSettingsHub]:
    application = QApplication.instance()
    if application is None:
        return None
    hub = getattr(application, "_cdmw_preview_settings_hub", None)
    if hub is None:
        hub = PreviewSettingsHub(_open_settings(), application)
        application._cdmw_preview_settings_hub = hub
    return hub


def _open_settings() -> QSettings:
    """The app's settings file; tests replace this to stay isolated."""
    from cdmw.services.settings_service import resolve_settings_file_path

    return QSettings(str(resolve_settings_file_path()), QSettings.Format.IniFormat)


__all__ = [
    "GLOBAL_PREVIEW_SETTINGS",
    "LIGHTING_PRESETS",
    "PreviewSettingsHub",
    "normalize_preview_settings",
    "preview_settings_hub",
]
