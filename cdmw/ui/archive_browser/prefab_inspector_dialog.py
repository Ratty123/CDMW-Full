"""Prefab Inspector: read a ``.prefab``'s structure and edit its resource paths.

The dialog is built around what the decoder can *prove*. Objects, their
component types and every resource path come from the structural walk; when
that walk cannot finish, the banner says so and editing is disabled rather than
silently operating on a half-understood file.

Declared names like ``_shrinkMaskDistance`` are translated through
:mod:`cdmw.domain.archives.prefab_glossary`, and the field list defaults to the
fields this prefab actually uses -- a prefab declares far more than it sets, and
showing all of them buries the handful that matter.

Path edits go through :func:`rewrite_prefab_paths`, which relocates pointers by
the exact identity rule, so replacements are not restricted to the original
byte length.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
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

from cdmw.domain.archives.prefab_glossary import (
    asset_role,
    describe_component,
    describe_field,
    describe_fields,
    is_asset_path,
    value_kind_hint,
)
from cdmw.services.prefab_structure_service import decode_prefab_binary, rewrite_prefab_paths

_EDIT_ROLE = Qt.ItemDataRole.UserRole + 1
_USED_ROLE = Qt.ItemDataRole.UserRole + 2

_CHANGED_COLOUR = QColor("#7ec8ff")
_WARNING_COLOUR = QColor("#ffb86b")


def _retarget_warning(original: str, replacement: str) -> str:
    """Why a replacement path looks wrong, or empty when it looks fine.

    These are shape checks, not existence checks -- the dialog has no archive
    to look the path up in, so it flags what it can prove from the text alone
    rather than implying the target was verified.
    """
    text = replacement.strip()
    if not text:
        return "Path is empty."
    if not is_asset_path(text):
        return "That does not look like a file path (expected folders and a file extension)."
    was, now = asset_role(original), asset_role(text)
    if was != now:
        return f"This field held a {was.lower()} file; the replacement looks like a {now.lower()} file."
    return ""


@dataclass(frozen=True, slots=True)
class PrefabInspectorResult:
    """What the dialog produced, if the user applied anything."""

    data: bytes
    summary: str


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
        self.resize(980, 660)
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
        tabs.addTab(self._build_objects_tab(), "What this prefab contains")
        tabs.addTab(self._build_schema_tab(), "All fields")
        layout.addWidget(tabs, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        row = QHBoxLayout()
        self.apply_button = QPushButton("Apply path changes")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply_changes)
        row.addWidget(self.apply_button)
        self.revert_button = QPushButton("Undo changes")
        self.revert_button.setEnabled(False)
        self.revert_button.clicked.connect(self._revert_changes)
        row.addWidget(self.revert_button)
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
        objects = len(document.objects)
        paths = sum(
            1
            for _name, item in self._all_values()
            if is_asset_path(item.text)
        )
        head = f"{objects} object(s), {paths} asset reference(s)."
        if document.walk_complete:
            return (
                head
                + " Fully decoded - you can repoint any asset path below, to a name of any length."
            )
        return (
            head
            + " Only partly decoded, so editing is switched off rather than risk writing a file"
            + f" we do not fully understand ({document.walk_note})."
        )

    def _can_edit(self) -> bool:
        return self._document is not None and self._document.walk_complete

    def _all_values(self) -> tuple[tuple[str, object], ...]:
        """Every recovered value, paired with the field it came from."""
        document = self._document
        if document is None:
            return ()
        pairs: list[tuple[str, object]] = list(document.root_values)
        for obj in document.objects:
            pairs.extend(obj.values)
        return tuple(pairs)

    # -- objects tab -----------------------------------------------------
    def _build_objects_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            QLabel(
                "Each object below is one piece of this prefab. Double-click an asset "
                "path to point it somewhere else."
            )
        )
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Object / field", "What it is", "Value"])
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
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
            root_item = QTreeWidgetItem(["This prefab", "Placement and sockets", ""])
            self.tree.addTopLevelItem(root_item)
            for name, item in document.root_values:
                self._add_value_row(root_item, name, item.text, editable)
            self._add_fields_row(root_item, document.root_members, document.root_values)
            root_item.setExpanded(True)
        for obj in document.objects:
            node = QTreeWidgetItem(
                [obj.name or "(unnamed)", describe_component(obj.component_type) or obj.component_type, ""]
            )
            self.tree.addTopLevelItem(node)
            for name, item in obj.values:
                self._add_value_row(node, name, item.text, editable)
            self._add_fields_row(node, obj.member_names, obj.values)
            node.setExpanded(True)

    def _add_value_row(
        self, parent: QTreeWidgetItem, field_name: str, value: str, editable: bool
    ) -> None:
        meaning = describe_field(field_name)
        path_like = is_asset_path(value)
        detail = meaning.detail or (f"a {asset_role(value).lower()} file" if path_like else "")
        row = QTreeWidgetItem([meaning.label, detail, value])
        row.setData(2, _EDIT_ROLE, value)
        row.setToolTip(0, field_name)
        if editable and path_like:
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsEditable)
            row.setToolTip(2, "Double-click to repoint this asset. Any length is allowed.")
        parent.addChild(row)

    def _add_fields_row(
        self,
        parent: QTreeWidgetItem,
        names: tuple[str, ...],
        shown: tuple[tuple[str, object], ...],
    ) -> None:
        """List the set fields that carry no text value, so nothing looks missing."""
        already = {name for name, _item in shown}
        remaining = tuple(name for name in names if name not in already)
        if not remaining:
            return
        row = QTreeWidgetItem(["Also set", "values not shown here", ", ".join(describe_fields(remaining))])
        row.setToolTip(2, ", ".join(remaining))
        parent.addChild(row)

    def _note_pending_edit(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 2:
            return
        original = item.data(2, _EDIT_ROLE)
        if not isinstance(original, str):
            return
        current = item.text(2)
        changed = current != original
        warning = _retarget_warning(original, current) if changed else ""
        colour = _WARNING_COLOUR if warning else _CHANGED_COLOUR if changed else None
        item.setForeground(2, QBrush(colour) if colour else QBrush())
        item.setToolTip(2, warning or ("Changed." if changed else ""))
        self._refresh_pending_state()

    def _refresh_pending_state(self) -> None:
        replacements = self.collect_replacements()
        warnings = [
            _retarget_warning(old, new)
            for old, new in replacements.items()
            if _retarget_warning(old, new)
        ]
        self.apply_button.setEnabled(self._can_edit() and bool(replacements))
        self.revert_button.setEnabled(bool(replacements))
        if not replacements:
            self.status.setText("")
            return
        count = len(replacements)
        note = f"{count} path change{'' if count == 1 else 's'} ready to apply."
        if warnings:
            verb = "looks" if len(warnings) == 1 else "look"
            note += f"  {len(warnings)} {verb} wrong: " + " ".join(dict.fromkeys(warnings))
        self.status.setText(note)

    def _revert_changes(self) -> None:
        """Put every edited row back to the value the file actually holds."""
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                original = child.data(2, _EDIT_ROLE)
                if isinstance(original, str) and child.text(2) != original:
                    child.setText(2, original)
        self.log.appendPlainText("Reverted to the paths stored in the file.")

    # -- schema tab ------------------------------------------------------
    def _build_schema_tab(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.addWidget(
            QLabel(
                "Every field this prefab declares, read from the file itself. "
                "Fields that point at another file are the ones worth repointing."
            )
        )
        controls = QHBoxLayout()
        self.used_only_box = QCheckBox("Only fields this prefab actually uses")
        self.used_only_box.setChecked(True)
        self.used_only_box.setToolTip(
            "A prefab declares far more fields than it sets. Untick to see the full declaration."
        )
        self.used_only_box.toggled.connect(lambda _checked: self._apply_filter(self.filter_box.text()))
        controls.addWidget(self.used_only_box)
        controls.addStretch(1)
        box.addLayout(controls)

        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("Search fields...")
        self.filter_box.textChanged.connect(self._apply_filter)
        box.addWidget(self.filter_box)

        self.schema_tree = QTreeWidget()
        self.schema_tree.setColumnCount(4)
        self.schema_tree.setHeaderLabels(["Field", "What it controls", "Holds", "Declared as"])
        header = self.schema_tree.header()
        for column in (0, 1, 2):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self._populate_schema()
        box.addWidget(self.schema_tree, 1)
        self._apply_filter("")
        return page

    def _used_field_names(self) -> set[str]:
        document = self._document
        if document is None:
            return set()
        used = set(document.root_members)
        for obj in document.objects:
            used.update(obj.member_names)
        return used

    def _populate_schema(self) -> None:
        document = self._document
        if document is None:
            return
        used = self._used_field_names()
        for declared in document.types:
            label = declared.type_name
            if declared.is_nested_prefab:
                label = f"{declared.type_name}  (another prefab)"
            node = QTreeWidgetItem([label, describe_component(declared.type_name), "", f"{len(declared.members)} fields"])
            self.schema_tree.addTopLevelItem(node)
            for member in declared.members:
                meaning = describe_field(member.name)
                child = QTreeWidgetItem(
                    [
                        meaning.label,
                        meaning.detail,
                        value_kind_hint(member.type_name, member.kind_label),
                        f"{member.name}  ({member.type_name})",
                    ]
                )
                child.setData(0, _USED_ROLE, member.name in used)
                node.addChild(child)
            node.setExpanded(True)

    def _apply_filter(self, text: str) -> None:
        needle = str(text or "").strip().lower()
        used_only = getattr(self, "used_only_box", None) is not None and self.used_only_box.isChecked()
        for index in range(self.schema_tree.topLevelItemCount()):
            parent = self.schema_tree.topLevelItem(index)
            shown = 0
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                matches = not needle or any(
                    needle in child.text(column).lower() for column in range(4)
                )
                if used_only and not bool(child.data(0, _USED_ROLE)):
                    matches = False
                child.setHidden(not matches)
                shown += int(matches)
            parent.setHidden(shown == 0)

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
        movement = "grew" if delta > 0 else "shrank" if delta < 0 else "stayed the same"
        summary = (
            f"Applied {len(result.edits)} path change(s); file {movement}"
            f"{f' by {abs(delta)} byte(s)' if delta else ''}, "
            f"{result.relocated_pointers} internal reference(s) rewritten to match."
        )
        for edit in result.edits:
            self.log.appendPlainText(f"{edit.old_text} -> {edit.new_text}")
        self.log.appendPlainText(summary)
        self.result_payload = PrefabInspectorResult(data=result.data, summary=summary)
        if self._on_save is not None:
            self._on_save(result.data, summary)


__all__ = ["PrefabInspectorDialog", "PrefabInspectorResult"]
