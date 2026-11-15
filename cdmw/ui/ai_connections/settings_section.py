"""Settings > AI connections: the switch, the approvals per class, Full access, and how to connect.

Every control writes the settings file at once and asks the app's
controller to apply it. These are the only controls that change these
values: no tool can (``approvals.refuse_protected_setting``).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from cdmw.mcp import approvals
from cdmw.mcp.names import DESTRUCTIVE, EDIT, OUTPUT

APPROVAL_CHOICES = (("Ask first", approvals.ASK), ("Allow without asking", approvals.ALLOW))
CLASS_ROWS = (
    (EDIT, "Edit tools", "Change an open session or document; undoable."),
    (DESTRUCTIVE, "Destructive tools", "Delete a draft or saved work row in the CDMW folder."),
    (OUTPUT, "Output tools", "Write a mod, an export or a draft folder outside the session."),
)


class AiConnectionsSettingsSection(QGroupBox):
    def __init__(self, settings, parent: QWidget | None = None, *, controller_lookup=None) -> None:
        super().__init__("AI connections", parent)
        self.setObjectName("AiConnectionsSettings")
        self.settings = settings
        self._controller_lookup = controller_lookup
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(8)

        self.enabled_checkbox = QCheckBox("Allow AI connections")
        self.enabled_checkbox.setObjectName("AiConnectionsEnabled")
        hint = QLabel("Lets AI apps on this computer, such as Claude and Codex CLI, search the archives and "
                      "answer questions about files through CDMW's tools. Off by default; while it is off "
                      "nothing listens.")
        hint.setWordWrap(True)
        hint.setObjectName("HintLabel")
        self.status_label = QLabel()
        self.status_label.setObjectName("AiConnectionsStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.enabled_checkbox)
        layout.addWidget(hint)
        layout.addWidget(self.status_label)

        form = QFormLayout()
        self.approval_combos: dict[str, QComboBox] = {}
        for effect, label, tooltip in CLASS_ROWS:
            combo = QComboBox()
            combo.setObjectName(f"AiApproval_{effect}")
            for text, value in APPROVAL_CHOICES:
                combo.addItem(text, value)
            combo.setToolTip(tooltip)
            self.approval_combos[effect] = combo
            form.addRow(label, combo)
        layout.addLayout(form)
        read_hint = QLabel("Read tools, which change nothing, always run without asking.")
        read_hint.setWordWrap(True)
        read_hint.setObjectName("HintLabel")
        layout.addWidget(read_hint)

        self.full_access_checkbox = QCheckBox("Full access: run every tool without asking")
        self.full_access_checkbox.setObjectName("AiFullAccess")
        self.keep_full_access_checkbox = QCheckBox("Keep Full access after CDMW closes")
        self.keep_full_access_checkbox.setObjectName("AiFullAccessKeep")
        refusal = QLabel("Whatever you choose here, no tool writes into the game, and no tool can change these "
                         "settings or the game folder.")
        refusal.setWordWrap(True)
        refusal.setObjectName("HintLabel")
        layout.addWidget(self.full_access_checkbox)
        layout.addWidget(self.keep_full_access_checkbox)
        layout.addWidget(refusal)

        setup_label = QLabel("To connect an AI app, add CDMW to it with one of these:")
        setup_label.setWordWrap(True)
        self.setup_text = QPlainTextEdit()
        self.setup_text.setObjectName("AiConnectionsSetup")
        self.setup_text.setReadOnly(True)
        self.setup_text.setPlainText(self._setup_text())
        self.setup_text.setMinimumHeight(140)
        layout.addWidget(setup_label)
        layout.addWidget(self.setup_text)

        self.load()
        self.enabled_checkbox.toggled.connect(self._save)
        self.full_access_checkbox.toggled.connect(self._save)
        self.keep_full_access_checkbox.toggled.connect(self._save)
        for combo in self.approval_combos.values():
            combo.currentIndexChanged.connect(self._save)
        controller = self._controller()
        if controller is not None:
            controller.state_changed.connect(self.refresh_status)

    @staticmethod
    def _setup_text() -> str:
        from cdmw.mcp.setup_lines import client_setup_lines

        return "\n\n".join(f"{client}:\n{line}" for client, line in client_setup_lines().items())

    def _controller(self):
        if self._controller_lookup is not None:
            return self._controller_lookup()
        from cdmw.ui.ai_connections.controller import ai_connections_controller

        return ai_connections_controller()

    def load(self) -> None:
        self._loading = True
        try:
            self.enabled_checkbox.setChecked(approvals.connections_enabled(self.settings))
            for effect, combo in self.approval_combos.items():
                combo.setCurrentIndex(max(0, combo.findData(approvals.approval_mode(self.settings, effect))))
            self.full_access_checkbox.setChecked(approvals.full_access(self.settings))
            self.keep_full_access_checkbox.setChecked(
                approvals._bool(self.settings.value(approvals.FULL_ACCESS_KEEP_KEY, False)))
        finally:
            self._loading = False
        self._sync_enabled_state()
        self.refresh_status()

    def _sync_enabled_state(self) -> None:
        self.keep_full_access_checkbox.setEnabled(self.full_access_checkbox.isChecked())

    def _save(self, *_args) -> None:
        if self._loading:
            return
        self.settings.setValue(approvals.ENABLED_KEY, self.enabled_checkbox.isChecked())
        for effect, combo in self.approval_combos.items():
            self.settings.setValue(approvals.APPROVAL_KEY.format(effect=effect), combo.currentData())
        self.settings.setValue(approvals.FULL_ACCESS_KEY, self.full_access_checkbox.isChecked())
        self.settings.setValue(approvals.FULL_ACCESS_KEEP_KEY,
                               self.full_access_checkbox.isChecked() and self.keep_full_access_checkbox.isChecked())
        sync = getattr(self.settings, "sync", None)
        if callable(sync):
            sync()
        self._sync_enabled_state()
        controller = self._controller()
        if controller is None and self.enabled_checkbox.isChecked():
            # The shell has not installed it (or not yet): install it now.
            from cdmw.ui.ai_connections.controller import install_ai_connections

            controller = install_ai_connections(self.window() if self.window() is not self else None, self.settings)
            controller.state_changed.connect(self.refresh_status)
        elif controller is not None:
            controller.apply()
        self.refresh_status()

    def refresh_status(self) -> None:
        controller = self._controller()
        if controller is not None:
            text = controller.status_text()
        elif approvals.connections_enabled(self.settings):
            text = "On. AI connections start with the next start of CDMW."
        else:
            text = "Off. Nothing listens and no AI app can reach CDMW."
        self.status_label.setText(text)
