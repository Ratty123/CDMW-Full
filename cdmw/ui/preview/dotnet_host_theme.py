"""Application-theme bridge for the embedded .NET/Vortice host."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from cdmw.constants import DEFAULT_UI_THEME
from cdmw.ui.theme_schemes import UI_THEME_SCHEMES


_UI_THEME_CAPABILITY = "ui_theme_state_v1"
_PALETTE_KEYS = (
    "window",
    "surface",
    "surface_alt",
    "field",
    "border",
    "border_strong",
    "text",
    "text_muted",
    "text_strong",
    "button",
    "button_hover",
    "button_pressed",
    "button_border",
    "accent",
)


class DotNetPreviewHostThemeMixin:
    """Keep Qt host chrome and the resident WinForms editor on one palette."""

    def set_theme(self, theme_key: str) -> None:
        resolved = str(theme_key or "").strip()
        if not resolved:
            application = QApplication.instance()
            if application is not None:
                resolved = str(application.property("_cdmw_theme_key") or "").strip()
        if resolved not in UI_THEME_SCHEMES:
            resolved = DEFAULT_UI_THEME
        self._theme_key = resolved
        self._apply_qt_host_theme()
        self._sync_dotnet_theme()

    def _apply_qt_host_theme(self) -> None:
        theme = UI_THEME_SCHEMES[self._theme_key]
        self._status_panel.setStyleSheet(
            "QFrame#DotNetPreviewStatusPanel {"
            f" background: {theme['window']}; border: 1px solid {theme['border']};"
            " }"
            f"QLabel {{ color: {theme['text']}; }}"
        )
        self._resident_banner.setStyleSheet(
            "QFrame#DotNetPreviewResidentBanner {"
            f" background: {theme['surface_alt']}; border: 1px solid {theme['border_strong']};"
            " border-radius: 2px; }"
            f"QLabel {{ color: {theme['text_strong']}; }}"
        )

    def _theme_protocol_payload(self) -> dict[str, object]:
        theme = UI_THEME_SCHEMES[self._theme_key]
        return {
            "event": "ui_theme_state",
            "protocol_version": 2,
            "process_generation": int(getattr(self.controller, "process_generation", 0) or 0),
            "theme_key": self._theme_key,
            "palette": {key: theme[key] for key in _PALETTE_KEYS},
        }

    def _sync_dotnet_theme(self) -> bool:
        controller = getattr(self, "controller", None)
        if controller is None or _UI_THEME_CAPABILITY not in set(
            getattr(controller, "capabilities", ()) or ()
        ):
            return False
        marker = (
            int(getattr(controller, "process_generation", 0) or 0),
            self._theme_key,
        )
        if getattr(controller, "_cdmw_ui_theme_marker", None) == marker:
            return True
        sender = getattr(controller, "_send_json", None)
        if not callable(sender) or not bool(sender(self._theme_protocol_payload())):
            return False
        setattr(controller, "_cdmw_ui_theme_marker", marker)
        return True

    def _sync_theme_after_renderer_ready(self, _payload: object) -> None:
        self._sync_dotnet_theme()

    def _connect_theme_ready_signal(self) -> None:
        signal = getattr(self.controller, "renderer_ready", None)
        if signal is not None and hasattr(signal, "connect"):
            signal.connect(self._sync_theme_after_renderer_ready)


__all__ = ["DotNetPreviewHostThemeMixin"]
