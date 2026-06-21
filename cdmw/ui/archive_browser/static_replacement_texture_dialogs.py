"""Texture override dialog helpers for static replacement UI."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


def texture_assignment_action_initial_state() -> dict[str, str]:
    return {"value": "cancel"}


def choose_texture_source_dialog(
    parent: QWidget,
    row_state: Mapping[str, object],
    choices: Sequence[tuple[str, str]],
    current_source: str,
    *,
    part_label: Callable[[object], str],
    role_label_for_slot: Callable[[str], str],
) -> str | None:
    picker_dialog = QDialog(parent)
    picker_dialog.setWindowTitle("Assign Override Source")
    picker_dialog.setModal(True)
    picker_dialog.resize(620, 520)
    picker_layout = QVBoxLayout(picker_dialog)
    picker_layout.setContentsMargins(12, 12, 12, 12)
    picker_layout.setSpacing(8)
    picker_label = QLabel(
        f"Assign a source texture to {part_label(row_state.get('target_name', ''))} / "
        f"{role_label_for_slot(str(row_state.get('slot_kind', '') or 'material'))}."
    )
    picker_label.setWordWrap(True)
    picker_label.setObjectName("HintLabel")
    picker_layout.addWidget(picker_label)
    source_list = QListWidget()
    source_list.setSelectionMode(QAbstractItemView.SingleSelection)
    selected_item: QListWidgetItem | None = None
    for label, source_path in choices:
        display_text = label if not source_path else f"{label}  -  {source_path}"
        item = QListWidgetItem(display_text)
        item.setData(Qt.UserRole, source_path)
        item.setToolTip(source_path or "Keep original")
        source_list.addItem(item)
        if str(source_path or "").strip() == current_source:
            selected_item = item
    if selected_item is None and source_list.count() > 0:
        selected_item = source_list.item(0)
    if selected_item is not None:
        source_list.setCurrentItem(selected_item)
    source_list.itemDoubleClicked.connect(lambda _item: picker_dialog.accept())
    picker_layout.addWidget(source_list, 1)
    button_row = QHBoxLayout()
    button_row.addStretch(1)
    assign_button = QPushButton("Assign Source")
    keep_button = QPushButton("Keep Original")
    cancel_button = QPushButton("Cancel")
    assign_button.clicked.connect(picker_dialog.accept)
    keep_button.clicked.connect(lambda: (source_list.setCurrentRow(0), picker_dialog.accept()))
    cancel_button.clicked.connect(picker_dialog.reject)
    button_row.addWidget(assign_button)
    button_row.addWidget(keep_button)
    button_row.addWidget(cancel_button)
    picker_layout.addLayout(button_row)
    if picker_dialog.exec() != QDialog.Accepted:
        return None
    current_item = source_list.currentItem()
    return str(current_item.data(Qt.UserRole) if current_item is not None else "").strip()


def confirm_texture_assignment_action(
    parent: QWidget,
    title: str,
    planned_rows: Sequence[tuple[dict[str, object], str, str]],
    *,
    reason: str,
    summary_html: Callable[..., str],
) -> bool:
    if not planned_rows:
        QMessageBox.information(
            parent,
            title,
            "No compatible suggested texture overrides were found for the selected part.",
        )
        return False
    confirm_dialog = QDialog(parent)
    confirm_dialog.setWindowTitle(title)
    confirm_dialog.setModal(True)
    confirm_dialog.resize(940, 540)
    confirm_layout = QVBoxLayout(confirm_dialog)
    confirm_layout.setContentsMargins(12, 12, 12, 12)
    confirm_layout.setSpacing(10)
    summary_browser = QTextBrowser()
    summary_browser.setReadOnly(True)
    summary_browser.setOpenExternalLinks(False)
    summary_browser.setTextInteractionFlags(Qt.TextSelectableByMouse)
    summary_browser.setHtml(summary_html(title, planned_rows, reason=reason))
    confirm_layout.addWidget(summary_browser, 1)
    button_row = QHBoxLayout()
    button_row.addStretch(1)
    apply_button = QPushButton("Apply These Overrides")
    cancel_button = QPushButton("Cancel")
    cancel_button.setDefault(True)
    apply_button.clicked.connect(confirm_dialog.accept)
    cancel_button.clicked.connect(confirm_dialog.reject)
    button_row.addWidget(apply_button)
    button_row.addWidget(cancel_button)
    confirm_layout.addLayout(button_row)
    return confirm_dialog.exec() == QDialog.Accepted


__all__ = [
    "choose_texture_source_dialog",
    "confirm_texture_assignment_action",
    "texture_assignment_action_initial_state",
]
