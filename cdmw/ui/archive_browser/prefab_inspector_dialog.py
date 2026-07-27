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
from typing import Callable, Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QListWidget,
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

from cdmw.domain.archives.prefab_companions import companion_paths
from cdmw.domain.archives.prefab_values import describe_value
from cdmw.domain.archives.prefab_glossary import (
    asset_role,
    describe_component,
    describe_field,
    describe_fields,
    is_asset_path,
    value_kind_hint,
)
from cdmw.services.prefab_structure_service import (
    asset_extension_for,
    decode_prefab_binary,
    path_is_known,
    rewrite_prefab_paths,
)

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


class AssetPickerDialog(QDialog):
    """Pick an existing archive path, filtered to one kind of asset."""

    def __init__(self, candidates: Sequence[str], *, current: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose an asset")
        self.resize(760, 520)
        self._candidates = tuple(candidates)
        self.chosen = ""

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{len(self._candidates):,} file(s) of this kind exist in the archives."))
        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("Type part of a name to narrow the list...")
        self.filter_box.textChanged.connect(self._refresh)
        layout.addWidget(self.filter_box)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _item: self._accept_selection())
        layout.addWidget(self.list, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Seed with the current file's folder, not its name: the useful starting
        # point is its siblings, and its own name matches only itself.
        folder = current.rsplit("/", 1)[0] if "/" in current else ""
        self.filter_box.setText(folder)
        self._refresh(self.filter_box.text())

    def _refresh(self, text: str) -> None:
        needle = str(text or "").strip().lower()
        matches = [item for item in self._candidates if needle in item.lower()] if needle else list(self._candidates)
        self.list.clear()
        # A full list of thousands is unusable and slow to build; narrow instead.
        self.list.addItems(matches[:500])
        if len(matches) > 500:
            self.list.addItem(f"... {len(matches) - 500:,} more, keep typing to narrow")

    def _accept_selection(self) -> None:
        item = self.list.currentItem()
        if item is None or item.text().startswith("... "):
            return
        self.chosen = item.text()
        self.accept()


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
        known_paths: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(980, 660)
        self._original = bytes(data or b"")
        self._on_save = on_save
        self._known_paths: Mapping[str, Sequence[str]] = dict(known_paths or {})
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
        self.browse_button = QPushButton("Choose file...")
        self.browse_button.setToolTip("Pick an existing asset of the same kind from the archives.")
        self.browse_button.setEnabled(False)
        self.browse_button.clicked.connect(self._browse_for_selected_row)
        row.addWidget(self.browse_button)
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
        self.tree.itemSelectionChanged.connect(self._refresh_browse_state)
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
            self._add_number_rows(root_item, document.root_numbers)
            self._add_fields_row(
                root_item, document.root_members, document.root_values, document.root_numbers
            )
            root_item.setExpanded(True)
        for obj in document.objects:
            # A nested prefab instance has no name of its own; the prefab it
            # instantiates is its identity, so lead with that rather than
            # labelling every copy "(unnamed)".
            nested = obj.component_type.startswith("/")
            if nested:
                label = obj.name or obj.component_type.rsplit("/", 1)[-1]
                detail = "a copy of another prefab"
            else:
                label = obj.name or "(unnamed)"
                detail = describe_component(obj.component_type) or obj.component_type
            node = QTreeWidgetItem([label, detail, ""])
            if nested:
                # Keep the full path reachable without letting it crowd out the
                # values column, which is the part worth reading.
                node.setToolTip(0, obj.component_type)
                node.setToolTip(1, obj.component_type)
            self.tree.addTopLevelItem(node)
            for name, item in obj.values:
                self._add_value_row(node, name, item.text, editable)
            self._add_number_rows(node, obj.numbers)
            self._add_fields_row(node, obj.member_names, obj.values, obj.numbers)
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

    def _add_number_rows(
        self, parent: QTreeWidgetItem, numbers: tuple[tuple[str, str, bytes], ...]
    ) -> None:
        """Show the numeric values: placement, opacity, flags and the like."""
        for field_name, type_name, raw in numbers:
            rendered = describe_value(type_name, raw)
            if not rendered:
                continue
            meaning = describe_field(field_name)
            row = QTreeWidgetItem([meaning.label, meaning.detail, rendered])
            row.setToolTip(0, f"{field_name}  ({type_name})")
            parent.addChild(row)

    def _add_fields_row(
        self,
        parent: QTreeWidgetItem,
        names: tuple[str, ...],
        shown: tuple[tuple[str, object], ...],
        numbers: tuple[tuple[str, str, bytes], ...] = (),
    ) -> None:
        """List the set fields that carry no shown value, so nothing looks missing."""
        already = {name for name, _item in shown} | {name for name, _t, _r in numbers}
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
        warning = self._warning_for(original, current) if changed else ""
        colour = _WARNING_COLOUR if warning else _CHANGED_COLOUR if changed else None
        item.setForeground(2, QBrush(colour) if colour else QBrush())
        item.setToolTip(2, warning or ("Changed." if changed else ""))
        self._refresh_pending_state()

    def _companion_notes(self, mesh_path: str) -> list[str]:
        """What travels with a mesh but is not carried by this prefab.

        The prefab references only the mesh; material and physics are resolved
        by path convention, so a retarget silently swaps those too.
        """
        notes: list[str] = []
        for companion in companion_paths(mesh_path):
            known = path_is_known(self._known_paths, companion.path)
            if known is None:
                notes.append(f"{companion.role} ({companion.detail}) comes from {companion.path}")
            elif known:
                notes.append(f"{companion.role} ({companion.detail}) will come from {companion.path}")
            else:
                notes.append(
                    f"{companion.role} ({companion.detail}) is MISSING: nothing at {companion.path}"
                )
        return notes

    def _missing_companions(self, mesh_path: str) -> list[str]:
        return [
            companion.role
            for companion in companion_paths(mesh_path)
            if path_is_known(self._known_paths, companion.path) is False
        ]

    def _warning_for(self, original: str, replacement: str) -> str:
        """Shape check first, then existence when an index covers this kind."""
        shape = _retarget_warning(original, replacement)
        if shape:
            return shape
        if path_is_known(self._known_paths, replacement) is False:
            return "No file with that path exists in the archives."
        missing = self._missing_companions(replacement)
        if missing:
            joined = " and ".join(missing).lower()
            return f"That mesh has no {joined} file of its own, so its {joined} will not load."
        return ""

    def _refresh_browse_state(self) -> None:
        item = self.tree.currentItem()
        editable = bool(item and item.flags() & Qt.ItemFlag.ItemIsEditable)
        self.browse_button.setEnabled(editable and bool(self._candidates_for(item)))

    def _candidates_for(self, item: QTreeWidgetItem | None) -> tuple[str, ...]:
        if item is None:
            return ()
        original = item.data(2, _EDIT_ROLE)
        if not isinstance(original, str):
            return ()
        return tuple(self._known_paths.get(asset_extension_for(original), ()))

    def _browse_for_selected_row(self) -> None:
        item = self.tree.currentItem()
        candidates = self._candidates_for(item)
        if item is None or not candidates:
            return
        picker = AssetPickerDialog(candidates, current=item.text(2), parent=self)
        if picker.exec() and picker.chosen:
            item.setText(2, picker.chosen)

    def _refresh_pending_state(self) -> None:
        replacements = self.collect_replacements()
        warnings = [
            self._warning_for(old, new)
            for old, new in replacements.items()
            if self._warning_for(old, new)
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
            for note in self._companion_notes(edit.new_text):
                self.log.appendPlainText(f"    {note}")
        self.log.appendPlainText(summary)
        self.result_payload = PrefabInspectorResult(data=result.data, summary=summary)
        if self._on_save is not None:
            self._on_save(result.data, summary)


__all__ = ["PrefabInspectorDialog", "PrefabInspectorResult"]
