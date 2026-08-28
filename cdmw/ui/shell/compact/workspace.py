"""Compact presentation wrapper around the authoritative nested tab hierarchy."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from cdmw.constants import DEFAULT_UI_THEME
from cdmw.ui.shell.compact.activity import ActivityHistory, CompactStatusSnapshot, tool_log_adapter_for
from cdmw.ui.shell.compact.config import active_shell_theme_setting, theme_change_field
from cdmw.ui.shell.compact.drawer import CompactActivityDrawer
from cdmw.ui.shell.compact.rail import CompactWorkspaceRail
from cdmw.ui.shell.compact.snapshots import compact_status_snapshot_for
from cdmw.ui.shell.compact.status_strip import CompactBottomStatusStrip
from cdmw.ui.themes import UI_THEME_SCHEMES


class CompactWorkspace(QWidget):
    def __init__(self, owner: object, main_tabs: QTabWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CompactWorkspace")
        self.owner = owner
        self.main_tabs = main_tabs
        self._active_tool_key = ""
        self._explicit_snapshot_keys: set[str] = set()
        self.activity_history = ActivityHistory(parent=self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.rail = CompactWorkspaceRail(owner, owner.settings, self)
        layout.addWidget(self.rail)
        right = QWidget()
        right.setObjectName("CompactWorkspaceContent")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(main_tabs, stretch=1)
        self.drawer = CompactActivityDrawer(self.activity_history, right)
        self.drawer.setVisible(False)
        right_layout.addWidget(self.drawer)
        self.status_strip = CompactBottomStatusStrip(
            owner.archive_scan_progress_label,
            owner.archive_scan_progress_bar,
            owner.archive_cache_status_chip,
            right,
        )
        right_layout.addWidget(self.status_strip)
        layout.addWidget(right, stretch=1)

        self.rail.tool_requested.connect(owner._activate_tool_key)
        self.status_strip.drawer_requested.connect(self.drawer.setVisible)

    def set_active_tool(self, tool_key: str) -> None:
        key = str(tool_key or "")
        self._active_tool_key = key
        self.rail.set_active_tool(key)
        self.status_strip.set_active_tool(key)
        self.drawer.set_tool_log(tool_log_adapter_for(self.owner, key))
        self._refresh_status_snapshot(key)

    def notify_tool_widget_ready(self, tool_key: str) -> None:
        key = str(tool_key or "")
        if self.rail.tool_buttons.get(key, None) is not None:
            checked = self.rail.tool_buttons[key].isChecked()
            if checked:
                self.drawer.set_tool_log(tool_log_adapter_for(self.owner, key))
                self._refresh_status_snapshot(key)
        self.refresh_tool_enabled_states()

    def refresh_tool_enabled_states(self) -> None:
        containers = getattr(self.owner, "_tool_widgets_by_key", {})
        for key, button in self.rail.tool_buttons.items():
            widget = containers.get(key) if isinstance(containers, dict) else None
            if widget is not None:
                button.setEnabled(widget.isEnabled())

    def append_activity(
        self,
        message: str,
        *,
        tool_key: str = "",
        source: str = "status",
        severity: str = "info",
    ) -> None:
        key = str(tool_key or self._active_tool_key)
        self.activity_history.append(
            message,
            tool_key=key,
            source=source,
            severity=severity,
        )
        self.status_strip.set_status_message(key, message, severity)
        if key == self._active_tool_key:
            self._refresh_status_snapshot(key)

    def set_status_snapshot(self, snapshot: CompactStatusSnapshot) -> None:
        self._explicit_snapshot_keys.add(snapshot.tool_key)
        self.status_strip.set_snapshot(snapshot)

    def _refresh_status_snapshot(self, tool_key: str) -> None:
        key = str(tool_key or "")
        if not key or key in self._explicit_snapshot_keys:
            return
        self.status_strip.set_snapshot(compact_status_snapshot_for(self.owner, key))

    def refresh_palette(self) -> None:
        self.rail.refresh_palette()
        self.status_strip.refresh_palette()


def sync_compact_workspace_selection(owner: object, tool_key: str | None = None) -> str:
    workspace = getattr(owner, "compact_workspace", None)
    if not isinstance(workspace, CompactWorkspace):
        return ""
    key = str(tool_key or "")
    if not key:
        current_widget = owner._current_navigation_widget()  # type: ignore[attr-defined]
        key = owner._tool_key_for_widget(current_widget)  # type: ignore[attr-defined]
    workspace.set_active_tool(key)
    return key


def append_compact_activity(
    owner: object,
    message: str,
    *,
    tool_key: str = "",
    source: str = "status",
    severity: str = "info",
) -> None:
    workspace = getattr(owner, "compact_workspace", None)
    if isinstance(workspace, CompactWorkspace):
        workspace.append_activity(
            message,
            tool_key=tool_key,
            source=source,
            severity=severity,
        )


def appearance_theme_target(owner: object) -> str:
    return active_shell_theme_setting(getattr(owner, "shell_variant", "legacy"))


def theme_change_payload(owner: object, theme_key: str) -> dict[str, object]:
    label = UI_THEME_SCHEMES.get(theme_key, UI_THEME_SCHEMES[DEFAULT_UI_THEME]).get(
        "label", "Theme"
    )
    changed_field = theme_change_field(appearance_theme_target(owner))
    return {
        "theme_key": theme_key,
        "theme_target": appearance_theme_target(owner),
        "changed": (changed_field,),
        "requires_theme_apply": True,
        "requires_ui_fonts": True,
        "requires_data_fonts": False,
        "requires_text_colors": False,
        "title": f"Applying {label} theme",
        "detail": "Updating app colors and preview panes...",
    }


def normalize_appearance_payload(
    owner: object,
    data: dict[str, object],
    theme_key: str,
    changed: tuple[str, ...],
) -> tuple[str, tuple[str, ...]]:
    _ = owner
    data["requires_theme_apply"] = bool(
        data.get("requires_theme_apply", False)
        and any(item in {"theme", "ui_density"} for item in changed)
    )
    return theme_key, changed


def settings_controls_theme_key(owner: object) -> str:
    return str(owner.current_theme_key)  # type: ignore[attr-defined]


def sync_settings_appearance_controls(owner: object) -> None:
    owner.settings_tab.sync_appearance_controls(  # type: ignore[attr-defined]
        settings_controls_theme_key(owner)
    )


def theme_applied(owner: object) -> None:
    owner.compact_shell_theme_key = owner.current_theme_key  # type: ignore[attr-defined]
    owner.classic_theme_key = owner.current_theme_key  # type: ignore[attr-defined]
    workspace = getattr(owner, "compact_workspace", None)
    if isinstance(workspace, CompactWorkspace):
        workspace.refresh_palette()


def save_theme_setting(owner: object) -> None:
    owner.settings.setValue(  # type: ignore[attr-defined]
        appearance_theme_target(owner),
        owner.current_theme_key,  # type: ignore[attr-defined]
    )


__all__ = [
    "CompactWorkspace",
    "append_compact_activity",
    "appearance_theme_target",
    "normalize_appearance_payload",
    "save_theme_setting",
    "settings_controls_theme_key",
    "sync_settings_appearance_controls",
    "sync_compact_workspace_selection",
    "theme_applied",
    "theme_change_payload",
]
