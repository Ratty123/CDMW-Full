"""Empty states that say what to do next (P11 step 6).

An empty panel shows one short sentence and one button, and the button runs the next
step as a registry command (P12), so it shares the command's label, availability and
reason with the menus, the palette and the keys. The empty state replaces the panel's
controls: `EmptyStateSwitch` shows either the content or its empty state, never both.
Spacing comes from cdmw.ui.layout_metrics, recomputed when the font changes.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget


def _localize(widget: QWidget) -> None:
    app = QApplication.instance()
    localizer = app.property("_cdmw_ui_localizer") if app is not None else None
    apply = getattr(localizer, "apply", None)
    if callable(apply):
        apply(widget)


def _source_text(label, text: str) -> None:
    label.setText(text)
    label.setProperty("_i18n_source_text", text)
    label.setProperty("_i18n_rendered_text", None)


class ActionEmptyState(QWidget):
    """One sentence and one button that runs `command_id` through the command registry.

    `run` replaces the registry for a page whose next step has no command yet; the
    button then calls it directly. When the command cannot run, the button is disabled
    and its tooltip is the command's reason.
    """

    def __init__(self, sentence: str, button_text: str = "", command_id: str = "", *,
                 run: Callable[[], object] | None = None, registry=None, density: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyStatePanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._density = density
        self._registry = registry
        self._run = run
        self.command_id = command_id
        self.last_reason = ""

        self._layout = QVBoxLayout(self)
        self._layout.addStretch(1)
        self.sentence_label = QLabel(self)
        self.sentence_label.setObjectName("EmptyStateTitle")
        self.sentence_label.setAlignment(Qt.AlignCenter)
        self.sentence_label.setWordWrap(True)
        self._layout.addWidget(self.sentence_label)
        row = QHBoxLayout()
        row.addStretch(1)
        self.button = QPushButton(self)
        self.button.setObjectName("EmptyStateAction")
        self.button.clicked.connect(self._clicked)
        row.addWidget(self.button)
        row.addStretch(1)
        self._layout.addLayout(row)
        self.reason_label = QLabel(self)
        self.reason_label.setObjectName("EmptyStateDetail")
        self.reason_label.setAlignment(Qt.AlignCenter)
        self.reason_label.setWordWrap(True)
        self.reason_label.setVisible(False)
        self._layout.addWidget(self.reason_label)
        self._layout.addStretch(1)
        self._apply_metrics()
        self.set_state(sentence, button_text, command_id, run=run)
        registry = self._commands()
        if registry is not None:
            registry.changed.connect(lambda _context: self.refresh())

    # ----- state ---------------------------------------------------------------
    def set_state(self, sentence: str, button_text: str = "", command_id: str = "", *,
                  run: Callable[[], object] | None = None) -> None:
        """Change what the state says and runs (for example "no game folder" to "not scanned")."""
        self.command_id = command_id
        self._run = run
        _source_text(self.sentence_label, sentence)
        label = button_text or self._command_label()
        _source_text(self.button, label)
        self.button.setVisible(bool(label) and bool(command_id or run))
        self.reason_label.setVisible(False)
        self.last_reason = ""
        _localize(self)
        self.refresh()

    def refresh(self) -> None:
        reason = self._reason()
        self.button.setEnabled(not reason)
        self.button.setToolTip(reason)

    def _commands(self):
        if self._registry is not None:
            return self._registry
        from cdmw.ui.commands.registry import command_registry

        return command_registry()

    def _command_label(self) -> str:
        registry = self._commands()
        if not self.command_id or registry is None or self.command_id not in registry:
            return ""
        from cdmw.ui.commands.registry import display_label

        return display_label(registry.get(self.command_id).label)

    def _reason(self) -> str:
        if self._run is not None or not self.command_id:
            return ""
        registry = self._commands()
        if registry is None or self.command_id not in registry:
            return ""  # registered later by the shell; running it then gives the real reason
        return registry.reason(self.command_id)

    def _clicked(self) -> None:
        if self._run is not None:
            self._run()
            reason = ""
        else:
            registry = self._commands()
            if registry is None:
                return
            reason = registry.run_or_reason(self.command_id)
        self.last_reason = reason
        _source_text(self.reason_label, reason)
        self.reason_label.setVisible(bool(reason))
        if reason:
            _localize(self.reason_label)

    # ----- sizes -----------------------------------------------------------------
    def _apply_metrics(self) -> None:
        from cdmw.constants import DEFAULT_UI_DENSITY
        from cdmw.ui.layout_metrics import layout_metrics

        points = self.font().pointSizeF()
        metrics = layout_metrics(self._density or DEFAULT_UI_DENSITY, points if points > 0 else 10.0)
        pad_x, pad_y = metrics.window_pad
        spacing = metrics.item_spacing[1]
        # A little more air than a panel's own padding: the state is the panel's content.
        self._layout.setContentsMargins(pad_x * 3, pad_y * 3, pad_x * 3, pad_y * 3)
        self._layout.setSpacing(spacing * 2)
        self.button.setMinimumHeight(metrics.control_height + metrics.frame_pad[1] * 2)

    def changeEvent(self, event) -> None:
        if event.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._apply_metrics()
        super().changeEvent(event)


class EmptyStateSwitch(QStackedWidget):
    """The panel's content, or its empty state in its place; never one above the other."""

    def __init__(self, content: QWidget, empty: ActionEmptyState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyStateSwitch")
        self.content = content
        self.empty = empty
        self.addWidget(content)
        self.addWidget(empty)

    def set_empty(self, empty: bool) -> None:
        self.setCurrentWidget(self.empty if empty else self.content)

    def is_empty(self) -> bool:
        return self.currentWidget() is self.empty


__all__ = ["ActionEmptyState", "EmptyStateSwitch"]
