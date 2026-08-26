"""Optional Compact Workspace presentation components."""

from cdmw.ui.shell.compact.activity import (
    ActivityEvent,
    ActivityHistory,
    CompactStatusSnapshot,
    ToolLogAdapter,
    tool_log_adapter_for,
)
from cdmw.ui.shell.compact.config import (
    APPLICATION_LAYOUT_SELECTOR_EXPOSED,
    COMPACT_SHELL_THEME_SETTING,
    COMPACT_SHELL_VARIANT,
    DEFAULT_COMPACT_SHELL_THEME,
    LEGACY_SHELL_VARIANT,
    SHELL_VARIANT_SETTING,
    active_shell_theme_key,
    active_shell_theme_setting,
    normalize_shell_variant,
    read_compact_shell_theme_key,
    read_shell_variant,
)
from cdmw.ui.shell.compact.registry import (
    COMPACT_CATEGORY_ORDER,
    COMPACT_TOOL_SPECS,
    CompactToolSpec,
    compact_tool_label,
    compact_tool_spec,
)
from cdmw.ui.shell.compact.snapshots import compact_status_snapshot_for
from cdmw.ui.shell.compact.workspace import CompactWorkspace

__all__ = [
    "APPLICATION_LAYOUT_SELECTOR_EXPOSED",
    "ActivityEvent",
    "ActivityHistory",
    "COMPACT_CATEGORY_ORDER",
    "COMPACT_SHELL_THEME_SETTING",
    "COMPACT_SHELL_VARIANT",
    "COMPACT_TOOL_SPECS",
    "CompactStatusSnapshot",
    "CompactToolSpec",
    "CompactWorkspace",
    "DEFAULT_COMPACT_SHELL_THEME",
    "LEGACY_SHELL_VARIANT",
    "SHELL_VARIANT_SETTING",
    "ToolLogAdapter",
    "active_shell_theme_key",
    "active_shell_theme_setting",
    "compact_tool_label",
    "compact_tool_spec",
    "compact_status_snapshot_for",
    "normalize_shell_variant",
    "read_compact_shell_theme_key",
    "read_shell_variant",
    "tool_log_adapter_for",
]
