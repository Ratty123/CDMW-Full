"""Bottom status strip that reuses the shell's existing status widgets."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from cdmw.ui.shell.compact.activity import CompactStatusSnapshot
from cdmw.ui.shell.compact.icons import compact_line_icon
from cdmw.ui.shell.compact.registry import compact_tool_label


class CompactBottomStatusStrip(QFrame):
    drawer_requested = Signal(bool)

    def __init__(
        self,
        ready_label: QLabel,
        progress_bar: QProgressBar,
        cache_label: QLabel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CompactBottomStatusStrip")
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedHeight(42)
        self._active_tool_key = ""
        self._snapshots: dict[str, CompactStatusSnapshot] = {}
        self._messages: dict[str, tuple[str, str]] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)
        self.ready_label = ready_label
        self.progress_bar = progress_bar
        self.cache_label = cache_label
        ready_label.setFixedWidth(72)
        ready_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        progress_bar.setFixedSize(76, 10)
        # Qt style-sheet heights describe the content box; the themed 1 px border
        # brings this to the intended 10 px outer height.
        progress_bar.setStyleSheet(
            "min-height: 8px; max-height: 8px; "
            "border: 1px solid palette(mid); border-radius: 0;"
        )
        progress_bar.setTextVisible(False)
        cache_label.setObjectName("CompactCacheStatusLabel")
        cache_label.setFixedWidth(110)
        cache_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(ready_label)
        layout.addWidget(progress_bar)
        layout.addWidget(cache_label)
        layout.addStretch(1)

        self.snapshot_label = QLabel("")
        self.snapshot_label.setObjectName("CompactStatusSnapshotLabel")
        self.snapshot_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.snapshot_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.snapshot_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.snapshot_label, stretch=1)
        self.activity_button = QPushButton("Activity")
        self.activity_button.setObjectName("CompactActivityToggle")
        self.activity_button.setCheckable(True)
        self.activity_button.setFlat(True)
        self.activity_button.setFixedHeight(28)
        self.activity_button.setStyleSheet("border-radius: 0; padding: 2px 7px;")
        self.activity_button.setIcon(compact_line_icon("activity", self.palette()))
        self.activity_button.setToolTip("Show or hide session Activity and the current tool's log.")
        self.activity_button.toggled.connect(self.drawer_requested.emit)
        layout.addWidget(self.activity_button)

    def set_active_tool(self, tool_key: str) -> None:
        self._active_tool_key = str(tool_key or "")
        self._refresh_text()

    def set_snapshot(self, snapshot: CompactStatusSnapshot) -> None:
        self._snapshots[snapshot.tool_key] = snapshot
        if snapshot.tool_key == self._active_tool_key:
            self._refresh_text()

    def set_status_message(self, tool_key: str, message: str, severity: str = "info") -> None:
        key = str(tool_key or "")
        self._messages[key] = (str(message or ""), str(severity or "info"))
        if key == self._active_tool_key:
            self._refresh_text()

    def _refresh_text(self) -> None:
        key = self._active_tool_key
        snapshot = self._snapshots.get(key)
        label = snapshot.label if snapshot is not None and snapshot.label else compact_tool_label(key, key)
        detail = snapshot.display_text() if snapshot is not None else ""
        if not detail:
            detail = self._messages.get(key, ("", "info"))[0]
        text = "  |  ".join(part for part in (label, detail) if part)
        self.snapshot_label.setText(text)
        self.snapshot_label.setToolTip(text)

    def refresh_palette(self) -> None:
        self.activity_button.setIcon(compact_line_icon("activity", self.palette()))


__all__ = ["CompactBottomStatusStrip"]
