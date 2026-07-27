"""Prefab Inspector: read a ``.prefab``'s structure and edit its resource paths.

The dialog is deliberately built around what the decoder can *prove*. Objects,
their component types and every resource path come from the structural walk;
when that walk cannot finish, the banner says so and editing is disabled rather
than silently operating on a half-understood file.

Path edits go through :func:`rewrite_prefab_paths`, which relocates pointers by
the exact identity rule, so replacement paths are not restricted to the
original byte length.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.prefab_structure_service import decode_prefab_binary, rewrite_prefab_paths

_EDIT_ROLE = Qt.ItemDataRole.UserRole + 1


@dataclass(frozen=True, slots=True)
class PrefabInspectorResult:
    """What the dialog produced, if the user saved anything."""

    data: bytes
    summary: str


def _looks_like_asset_path(value: str) -> bool:
    """Whether a decoded string addresses another file.

    Some asset paths are stored inline rather than behind a pointer -- the
    ``.sockets.xml`` companion is the common case -- so editability follows the
    value's shape, not which record kind it came from.
    """
    text = str(value or "").strip()
    return "/" in text and "." in text.rsplit("/", 1)[-1]


def _value_label(value: str) -> str:
    """Row label for a decoded value: path-like values are the editable ones."""
    return "file path" if _looks_like_asset_path(value) else "text"


def _kind_hint(member: object) -> str:
    """A plain-English description of what a declared field holds."""
    kind = getattr(member, "kind_label", "value")
    fixed = {
        "reference": "points at another file",
        "text": "inline text",
        "list": "child objects",
        "enum": "fixed choice",
    }
    if kind in fixed:
        return fixed[kind]
    type_name = str(getattr(member, "type_name", "")).lower()
    if type_name == "bool":
        return "on/off flag"
    if "transform" in type_name:
        return "position / rotation / scale"
    if "uuid" in type_name or "uid" in type_name:
        return "identifier"
    return "number"


class PrefabInspectorDialog(QDialog):
    """Structure browser and path editor for a single prefab payload."""

    def __init__(
        self,
        data: bytes,
        *,
        title: str = "Prefab Inspector",
        parent: QWidget | None = None,
        on_save: Callable[[bytes, str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(940, 640)
        self._original = bytes(data or b"")
        self._on_save = on_save
        self.result_payload: PrefabInspectorResult | None = None
        self._document: object | None = None
        self._error = ""
        try:
            self._document = decode_prefab_binary(self._original)
        except Exception as exc:  # noqa: BLE001 - surfaced in the banner
            self._error = str(exc)
        self._build_ui()

    # -- construction ----------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.banner = QLabel(self._banner_text())
        self.banner.setWordWrap(True)
        layout.addWidget(self.banner)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_objects_tab(), "Objects && paths")
        tabs.addTab(self._build_schema_tab(), "Fields in this prefab")
        layout.addWidget(tabs, 1)

        row = QHBoxLayout()
        self.apply_button = QPushButton("Apply path changes")
        self.apply_button.setEnabled(self._can_edit())
        self.apply_button.clicked.connect(self._apply_changes)
        row.addWidget(self.apply_button)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.setPlaceholderText("Edits and their effect on the file appear here.")
        layout.addWidget(self.log)

    def _banner_text(self) -> str:
        if self._document is None:
            return f"This file could not be read as a prefab: {self._error}"
        document = self._document
        head = (
            f"Prefab v{document.version} (schema revision {document.revision}) - "
            f"{len(document.types)} declared types, {len(document.objects)} object(s), "
            f"{len(document.pointers)} internal pointer(s)."
        )
        if document.walk_complete:
            return head + " Fully decoded, so paths can be edited to any length."
        return (
            head
            + " Only partly decoded, so editing is disabled to avoid writing a file "
            + f"we do not fully understand ({document.walk_note})."
        )

    def _can_edit(self) -> bool:
        return self._document is not None and self._document.walk_complete

    # -- objects tab -----------------------------------------------------
    def _build_objects_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            QLabel(
                "Double-click a path to retarget it. Replacements may be longer or "
                "shorter than the original."
            )
        )
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Object / field", "Type", "Value"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.itemChanged.connect(self._note_pending_edit)
        self._populate_objects()
        box.addWidget(self.tree, 1)
        return page

    def _populate_objects(self) -> None:
        document = self._document
        if document is None:
            return
        editable = self._can_edit()
        if document.root_texts or document.root_resources:
            root_item = QTreeWidgetItem(["(prefab root)", document.root_type, ""])
            self.tree.addTopLevelItem(root_item)
            for item in document.root_resources + document.root_texts:
                self._add_value_row(root_item, _value_label(item.text), item.text, editable)
            root_item.setExpanded(True)
        for obj in document.objects:
            label = obj.name or "(unnamed object)"
            node = QTreeWidgetItem([label, obj.component_type, ""])
            self.tree.addTopLevelItem(node)
            for item in tuple(obj.resources) + tuple(obj.texts):
                self._add_value_row(node, _value_label(item.text), item.text, editable)
            if obj.member_names:
                node.addChild(QTreeWidgetItem(["fields set", "", ", ".join(obj.member_names)]))
            node.setExpanded(True)

    def _add_value_row(self, parent: QTreeWidgetItem, kind: str, value: str, editable: bool) -> None:
        row = QTreeWidgetItem([kind, "", value])
        row.setData(2, _EDIT_ROLE, value)
        if editable and _looks_like_asset_path(value):
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsEditable)
        parent.addChild(row)

    def _note_pending_edit(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 2:
            return
        original = item.data(2, _EDIT_ROLE)
        current = item.text(2)
        if isinstance(original, str) and current != original:
            self.log.appendPlainText(f"pending: {original} -> {current}")

    # -- schema tab ------------------------------------------------------
    def _build_schema_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            QLabel(
                "Every field this prefab declares, read from the file itself. "
                "Fields marked 'reference' point at other assets and are the ones "
                "worth retargeting."
            )
        )
        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("Filter fields...")
        self.filter_box.textChanged.connect(self._apply_filter)
        box.addWidget(self.filter_box)

        self.schema_tree = QTreeWidget()
        self.schema_tree.setColumnCount(4)
        self.schema_tree.setHeaderLabels(["Type / field", "Declared as", "Kind", "Bytes"])
        header = self.schema_tree.header()
        for column in (0, 1, 2):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self._populate_schema()
        box.addWidget(self.schema_tree, 1)
        return page

    def _populate_schema(self) -> None:
        document = self._document
        if document is None:
            return
        for declared in document.types:
            label = declared.type_name
            if declared.is_nested_prefab:
                label = f"{declared.type_name}  (nested prefab)"
            node = QTreeWidgetItem([label, f"{len(declared.members)} fields", "", ""])
            self.schema_tree.addTopLevelItem(node)
            for member in declared.members:
                node.addChild(
                    QTreeWidgetItem(
                        [
                            member.name,
                            member.type_name,
                            _kind_hint(member),
                            str(member.value_size),
                        ]
                    )
                )
            node.setExpanded(True)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for index in range(self.schema_tree.topLevelItemCount()):
            parent = self.schema_tree.topLevelItem(index)
            shown = 0
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                match = not needle or needle in child.text(0).lower() or needle in child.text(1).lower()
                child.setHidden(not match)
                shown += int(match)
            parent.setHidden(bool(needle) and shown == 0)
            parent.setExpanded(bool(needle))

    # -- editing ---------------------------------------------------------
    def collect_replacements(self) -> dict[str, str]:
        """Pending path changes as ``{original: replacement}``."""
        replacements: dict[str, str] = {}
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                original = child.data(2, _EDIT_ROLE)
                current = child.text(2).strip()
                if isinstance(original, str) and current and current != original:
                    replacements[original] = current
        return replacements

    def _apply_changes(self) -> None:
        if not self._can_edit():
            return
        replacements = self.collect_replacements()
        if not replacements:
            self.log.appendPlainText("Nothing to apply: no paths were changed.")
            return
        try:
            result = rewrite_prefab_paths(self._original, replacements)
        except Exception as exc:  # noqa: BLE001 - reported to the user
            self.log.appendPlainText(f"Refused: {exc}")
            return
        delta = result.byte_delta
        summary = (
            f"Applied {len(result.edits)} path change(s); file size "
            f"{'grew' if delta > 0 else 'shrank' if delta < 0 else 'unchanged'} by {abs(delta)} byte(s), "
            f"{result.relocated_pointers} pointer(s) relocated."
        )
        for line in result.proof_lines:
            self.log.appendPlainText(line)
        self.log.appendPlainText(summary)
        self.result_payload = PrefabInspectorResult(data=result.data, summary=summary)
        if self._on_save is not None:
            self._on_save(result.data, summary)


__all__ = ["PrefabInspectorDialog", "PrefabInspectorResult"]
