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

from dataclasses import dataclass, replace
from typing import Callable, Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.archives.prefab_companions import companion_paths
from cdmw.domain.archives.prefab_values import (
    Placement,
    placement_space,
    describe_value,
    read_placement,
    write_placement,
)
from cdmw.domain.archives.prefab_glossary import (
    asset_role,
    describe_component,
    describe_field,
    describe_fields,
    is_asset_path,
    value_kind_hint,
)
from cdmw.ui.archive_browser.prefab_inspector_review import ChangeLine, PrefabChangeReview
from cdmw.ui.archive_browser.prefab_inspector_widgets import (
    AssetPickerDialog,
    PlacementEditDialog,
)
from cdmw.services.prefab_structure_service import (
    asset_extension_for,
    decode_prefab_binary,
    path_is_known,
    PrefabPathEdit,
    prefab_source_digest,
    rewrite_prefab_paths,
    rewrite_prefab_placements,
)

_EDIT_ROLE = Qt.ItemDataRole.UserRole + 1
_USED_ROLE = Qt.ItemDataRole.UserRole + 2
_PLACEMENT_ROLE = Qt.ItemDataRole.UserRole + 3
#: Byte offset of the string a row shows, so an edit names one occurrence
#: rather than every copy of the same path in the file.
_OFFSET_ROLE = Qt.ItemDataRole.UserRole + 4

_CHANGED_COLOUR = QColor("#7ec8ff")
_WARNING_COLOUR = QColor("#ffb86b")


def _count(number: int, noun: str, plural: str = "") -> str:
    """``1 object`` / ``2 objects`` -- never ``1 object(s)``."""
    word = noun if number == 1 else (plural or f"{noun}s")
    return f"{number:,} {word}"


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
        known_paths: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(980, 660)
        self._original = bytes(data or b"")
        self._on_save = on_save
        self._known_paths: Mapping[str, Sequence[str]] = dict(known_paths or {})
        # (expected_old, new) per offset: the expected bytes are what makes
        # the staleness check in rewrite_prefab_placements able to fail.
        self._placement_edits: dict[int, tuple[bytes, bytes]] = {}
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

        # A modder meeting a prefab for the first time needs to know what kind
        # of thing it is before any of the rows mean anything.
        self.intro = QLabel(
            "A prefab is a parts list: which files an object is built from, and where each "
            "part sits. Saving writes a separate mod package - your game files are never "
            "changed."
        )
        self.intro.setWordWrap(True)
        # No hard-coded colour: the app follows the system light/dark theme, and a
        # fixed grey turns unreadable in one of them.
        font = self.intro.font()
        font.setItalic(True)
        self.intro.setFont(font)
        self.intro.setMinimumHeight(self.intro.fontMetrics().height() * 2)
        layout.addWidget(self.intro)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_objects_tab(), "What this prefab contains")
        tabs.addTab(self._build_schema_tab(), "Fields explained")
        layout.addWidget(tabs, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        row = QHBoxLayout()
        # The ellipsis is load-bearing: this builds the edited file but does not
        # write anything. The destination is chosen after the window closes, and
        # the old label ("Save changes", "Write the changes into a copy") read as
        # if the save had already happened.
        self.apply_button = QPushButton("Save changes...")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._apply_changes)
        self.apply_button.setToolTip(
            "Build the edited file. You choose where to save the mod package after "
            "closing this window; the game files are never touched."
        )
        row.addWidget(self.apply_button)
        self.revert_button = QPushButton("Undo all changes")
        self.revert_button.setEnabled(False)
        self.revert_button.clicked.connect(self._revert_changes)
        self.revert_button.setToolTip("Put every row back to the value stored in the file.")
        row.addWidget(self.revert_button)
        self.browse_button = QPushButton("Swap for another file...")
        self.browse_button.setEnabled(False)
        self.browse_button.clicked.connect(self._browse_for_selected_row)
        row.addWidget(self.browse_button)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)

        # Hidden until there is something to say: an empty box that large just
        # pushes the content the modder came for off the screen.
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        self.log.hide()
        layout.addWidget(self.log)

        # Last, so the selection can drive button state that now exists.
        self._select_first_editable_row()

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
        placements = sum(
            1
            for number in self._all_numbers()
            if read_placement(number.raw) is not None
        )
        parts = [_count(objects, "object")]
        if paths:
            parts.append(_count(paths, "asset reference"))
        if placements:
            parts.append(_count(placements, "placement"))
        head = ", ".join(parts) + "."
        # Never claim the contents are accurate. Where the file does not state
        # an object's kind the walk infers it from declaration order, and an
        # inferred object looks exactly as tidy as a correct one.
        guessed = len(document.inferred_objects)
        caveat = (
            ""
            if not guessed
            else (
                f" {_count(guessed, 'object')} marked \"best guess\" below: the file does "
                f"not say what {'it is' if guessed == 1 else 'they are'}, so "
                f"{'its' if guessed == 1 else 'their'} fields may belong to something else."
            )
        )
        if document.walk_complete:
            return f"Fully read. {head} Everything below can be changed.{caveat}"
        return (
            f"Partly read - saving is switched off. {head} What is shown was read from "
            "the file; the rest uses a structure this tool cannot follow yet, so it will "
            f"not write a file it does not fully understand.{caveat}"
        )

    def _can_edit(self) -> bool:
        return self._document is not None and self._document.walk_complete

    def _all_numbers(self) -> tuple[object, ...]:
        """Every inline numeric value in the file."""
        document = self._document
        if document is None:
            return ()
        found = list(document.root_numbers)
        for obj in document.objects:
            found.extend(obj.numbers)
        return tuple(found)

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
        box.addWidget(QLabel(self._objects_hint()))
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Object / field", "What it is", "Value"])
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.itemChanged.connect(self._note_pending_edit)
        self.tree.itemSelectionChanged.connect(self._refresh_browse_state)
        self.tree.itemDoubleClicked.connect(self._edit_placement)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_row_menu)
        copy = QShortcut(QKeySequence.StandardKey.Copy, self.tree)
        copy.activated.connect(self._copy_selected_value)
        self._populate_objects()
        box.addWidget(self.tree, 1)
        return page

    def _select_first_editable_row(self) -> None:
        """Start on something changeable, so the buttons are live on open.

        Otherwise every action button is greyed until the modder guesses that a
        row has to be selected first.
        """
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                if child.flags() & Qt.ItemFlag.ItemIsEditable or child.data(0, _PLACEMENT_ROLE):
                    self.tree.setCurrentItem(child)
                    return

    def _objects_hint(self) -> str:
        """Say what can be done here, which depends on whether editing is on."""
        if self._document is None:
            return "Nothing could be read from this file."
        if not self._can_edit():
            return (
                "Each row is one piece of this prefab. This file is read-only because it "
                "was only partly read - you can look, copy and compare, but not save."
            )
        actions = []
        if any(is_asset_path(item.text) for _name, item in self._all_values()):
            actions.append("a file to swap it for another")
        if any(read_placement(number.raw) is not None for number in self._all_numbers()):
            actions.append("a placement to move or resize it")
        how = f"Double-click {' or '.join(actions)}. " if actions else ""
        return f"Each row is one piece of this prefab. {how}Ctrl+C copies the selected value."

    def _populate_objects(self) -> None:
        document = self._document
        if document is None:
            return
        editable = self._can_edit()
        if document.root_texts or document.root_resources:
            root_item = QTreeWidgetItem(["This prefab", "Placement and sockets", ""])
            self.tree.addTopLevelItem(root_item)
            for name, item in document.root_values:
                self._add_value_row(root_item, name, item.text, editable, item.offset)
            self._add_number_rows(root_item, document.root_numbers)
            self._add_fields_row(
                root_item,
                document.root_members,
                document.root_values,
                document.root_numbers,
                self._collection_members(document.root_type),
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
            if obj.type_is_inferred:
                # The file never said what this is. It decoded cleanly, which
                # is not the same as being right, and the warning has to travel
                # with the row -- a banner at the top does not tell you which
                # of eight objects is the guess.
                detail = f"{detail} - best guess, the file does not say what this is"
            node = QTreeWidgetItem([label, detail, ""])
            if obj.type_is_inferred:
                node.setToolTip(
                    1,
                    "This object's kind was worked out from its position in the file, "
                    "not read from it. The fields below may belong to something else.",
                )
            if nested:
                # Keep the full path reachable without letting it crowd out the
                # values column, which is the part worth reading.
                node.setToolTip(0, obj.component_type)
                node.setToolTip(1, obj.component_type)
            self.tree.addTopLevelItem(node)
            for name, item in obj.values:
                self._add_value_row(node, name, item.text, editable, item.offset)
            self._add_number_rows(node, obj.numbers)
            self._add_fields_row(
                node,
                obj.member_names,
                obj.values,
                obj.numbers,
                self._collection_members(obj.component_type),
            )
            node.setExpanded(True)

    def _add_value_row(
        self,
        parent: QTreeWidgetItem,
        field_name: str,
        value: str,
        editable: bool,
        offset: int = -1,
    ) -> None:
        meaning = describe_field(field_name)
        path_like = is_asset_path(value)
        detail = meaning.detail or (f"a {asset_role(value).lower()} file" if path_like else "")
        row = QTreeWidgetItem([meaning.label, detail, value])
        row.setData(2, _EDIT_ROLE, value)
        row.setData(2, _OFFSET_ROLE, int(offset))
        row.setToolTip(0, field_name)
        row.setToolTip(2, value)
        if editable and path_like:
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsEditable)
            row.setToolTip(2, "Double-click to swap this for a different file. Any name length is fine.")
        parent.addChild(row)

    def _collection_members(self, type_name: str) -> frozenset[str]:
        """Members that hold child objects, which appear as rows of their own."""
        document = self._document
        if document is None:
            return frozenset()
        for declared in document.types:
            if declared.type_name == type_name:
                return frozenset(
                    member.name for member in declared.members if member.is_collection
                )
        return frozenset()

    def _add_number_rows(self, parent: QTreeWidgetItem, numbers: tuple[object, ...]) -> None:
        """Show the numeric values: placement, opacity, flags and the like."""
        seen_placements: dict[str, str] = {}
        for number in numbers:
            rendered = describe_value(number.type_name, number.raw)
            if not rendered:
                continue
            if read_placement(number.raw) is not None:
                # World and tiled placement usually hold identical values;
                # printing both in full doubles the rows and says nothing new.
                match = seen_placements.get(rendered)
                if match:
                    rendered = f"same as {match.lower()}"
                else:
                    seen_placements[describe_value(number.type_name, number.raw)] = (
                        describe_field(number.name).label
                    )
            meaning = describe_field(number.name)
            row = QTreeWidgetItem([meaning.label, meaning.detail, rendered])
            row.setToolTip(0, f"{number.name}  ({number.type_name})")
            if self._can_edit() and read_placement(number.raw) is not None:
                row.setData(
                    0,
                    _PLACEMENT_ROLE,
                    (number.offset, number.type_name, number.raw, number.name),
                )
                row.setToolTip(2, "Double-click to move, rotate or rescale this.")
            parent.addChild(row)

    def _add_fields_row(
        self,
        parent: QTreeWidgetItem,
        names: tuple[str, ...],
        shown: tuple[tuple[str, object], ...],
        numbers: tuple[object, ...] = (),
        collections: frozenset[str] = frozenset(),
    ) -> None:
        """List set fields with nothing else to show, so none look missing.

        Collections are excluded: their contents are the child rows, so listing
        them as having no value to show contradicts what is on screen.
        """
        already = (
            {name for name, _item in shown}
            | {number.name for number in numbers}
            | set(collections)
        )
        remaining = tuple(name for name in names if name not in already)
        if not remaining:
            return
        row = QTreeWidgetItem(
            ["Also set", "on, but with no value to show", ", ".join(describe_fields(remaining))]
        )
        row.setToolTip(2, ", ".join(remaining))
        parent.addChild(row)

    def _log(self, text: str) -> None:
        """Append to the activity log, revealing it on first use."""
        self.log.show()
        self.log.appendPlainText(text)

    def _copy_selected_value(self) -> None:
        """Copy the selected row's value, so a path can be pasted elsewhere."""
        item = self.tree.currentItem()
        if item is None:
            return
        text = item.text(2) or item.text(0)
        if text:
            QGuiApplication.clipboard().setText(text)
            self._log(f"Copied: {text}")

    def _show_row_menu(self, position) -> None:
        item = self.tree.itemAt(position)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        menu = QMenu(self.tree)
        copy_action = QAction("Copy value", menu)
        copy_action.triggered.connect(self._copy_selected_value)
        menu.addAction(copy_action)
        if item.flags() & Qt.ItemFlag.ItemIsEditable:
            retarget = QAction("Swap for another file...", menu)
            retarget.triggered.connect(self._browse_for_selected_row)
            retarget.setEnabled(bool(self._candidates_for(item)))
            menu.addAction(retarget)
        if item.data(0, _PLACEMENT_ROLE):
            move = QAction("Move, rotate or rescale...", menu)
            move.triggered.connect(lambda: self._edit_placement(item, 2))
            menu.addAction(move)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _edit_placement(self, item: QTreeWidgetItem, _column: int) -> None:
        """Open the placement editor for a transform row."""
        stored = item.data(0, _PLACEMENT_ROLE)
        if not stored:
            return
        offset, type_name, original_raw, member_name = stored
        pending = self._placement_edits.get(offset)
        current = pending[1] if pending else original_raw
        placement = read_placement(current)
        if placement is None:
            return
        editor = PlacementEditDialog(
            placement, title=item.text(0), space=placement_space(member_name), parent=self
        )
        if not editor.exec() or editor.result_placement is None:
            return
        new_raw = write_placement(editor.result_placement)
        if new_raw == original_raw:
            self._placement_edits.pop(offset, None)
        else:
            self._placement_edits[offset] = (original_raw, new_raw)
        item.setText(2, describe_value(type_name, new_raw))
        item.setForeground(
            2, QBrush(_CHANGED_COLOUR) if offset in self._placement_edits else QBrush()
        )
        self._sync_twin_placements(item, placement, editor.result_placement)
        self._refresh_pending_state()

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
        """Enable Choose file..., and have it say why when it cannot help."""
        item = self.tree.currentItem()
        editable = bool(item and item.flags() & Qt.ItemFlag.ItemIsEditable)
        candidates = self._candidates_for(item)
        self.browse_button.setEnabled(editable and bool(candidates))
        if not self._can_edit():
            reason = "This file is read-only because it was only partly read."
        elif not editable:
            reason = "Select a row with a file in it, then pick a replacement."
        elif not candidates:
            reason = "No index of this asset kind is loaded, so there is nothing to pick from."
        else:
            reason = f"Pick from the {len(candidates):,} files of this kind that exist in the game."
        self.browse_button.setToolTip(reason)

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
        pending = len(replacements) + len(self._placement_edits)
        self.apply_button.setEnabled(self._can_edit() and bool(pending))
        self.revert_button.setEnabled(bool(pending))
        if not pending:
            self.status.setText("")
            return
        parts = []
        if replacements:
            parts.append(f"{len(replacements)} path change{'' if len(replacements) == 1 else 's'}")
        if self._placement_edits:
            moved = len(self._placement_edits)
            parts.append(f"{moved} placement{'' if moved == 1 else 's'}")
        note = " and ".join(parts) + " ready to apply."
        if warnings:
            verb = "looks" if len(warnings) == 1 else "look"
            note += f"  {len(warnings)} {verb} wrong: " + " ".join(dict.fromkeys(warnings))
        self.status.setText(note)

    def _sync_twin_placements(
        self, edited: QTreeWidgetItem, was: Placement, now: Placement
    ) -> None:
        """Move the object's other transform to match, when they were identical.

        Objects carry ``_worldTransform`` and ``_tiledTransform`` as a pair, and
        in all 5,228 shipped objects that have both, the two hold the same
        scale, rotation and position. Moving one and not the other leaves a
        combination the game's own data never contains, and the tree collapses
        the duplicate to "same as ...", so the second one is not even visible to
        correct by hand.
        """
        parent = edited.parent()
        if parent is None:
            return
        for index in range(parent.childCount()):
            sibling = parent.child(index)
            stored = sibling.data(0, _PLACEMENT_ROLE)
            if sibling is edited or not stored:
                continue
            offset, type_name, original_raw, _name = stored
            pending = self._placement_edits.get(offset)
            current = read_placement(pending[1] if pending else original_raw)
            if current is None or current != was:
                continue
            # Keep each copy's own tile index; only TiledTransform carries one.
            twin = write_placement(replace(now, tile=current.tile))
            if twin == original_raw:
                self._placement_edits.pop(offset, None)
            else:
                self._placement_edits[offset] = (original_raw, twin)
            sibling.setText(2, describe_value(type_name, twin))
            sibling.setForeground(
                2, QBrush(_CHANGED_COLOUR) if offset in self._placement_edits else QBrush()
            )
            self._log(
                f"Moved {describe_field(_name).label.lower()} to match: the two are "
                "identical in every shipped object that carries both."
            )

    def _revert_changes(self) -> None:
        """Put every edited row back to the value the file actually holds."""
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                original = child.data(2, _EDIT_ROLE)
                if isinstance(original, str) and child.text(2) != original:
                    child.setText(2, original)
                stored = child.data(0, _PLACEMENT_ROLE)
                if stored:
                    offset, type_name, original_raw, member_name = stored
                    if offset in self._placement_edits:
                        child.setText(2, describe_value(type_name, original_raw))
                        child.setForeground(2, QBrush())
        self._placement_edits.clear()
        self._log("Reverted to the values stored in the file.")
        self._refresh_pending_state()

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
    def collect_path_edits(self) -> tuple[PrefabPathEdit, ...]:
        """Pending path changes, one per edited row, addressed by byte offset.

        Addressing by offset rather than by the old text is what lets two rows
        that happen to share a path be retargeted to different files. Keyed by
        text, the second row silently overwrote the first.
        """
        edits: list[PrefabPathEdit] = []
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                original = child.data(2, _EDIT_ROLE)
                offset = child.data(2, _OFFSET_ROLE)
                current = child.text(2).strip()
                if not isinstance(original, str) or not current or current == original:
                    continue
                if not isinstance(offset, int) or offset < 0:
                    continue
                edits.append(
                    PrefabPathEdit(offset=offset, old_text=original, new_text=current)
                )
        return tuple(edits)

    def collect_replacements(self) -> dict[str, str]:
        """The same pending changes as ``{original: replacement}``, for display."""
        return {edit.old_text: edit.new_text for edit in self.collect_path_edits()}

    def _pending_changes(self) -> tuple[list[ChangeLine], list[str]]:
        """Everything the modder is about to write, with anything that looks wrong.

        Built by walking the tree so each line carries the label the modder saw,
        not the declared member name.
        """
        lines: list[ChangeLine] = []
        warnings: list[str] = []
        counts: dict[str, int] = {}
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                original = child.data(2, _EDIT_ROLE)
                if isinstance(original, str):
                    counts[original] = counts.get(original, 0) + 1
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                original = child.data(2, _EDIT_ROLE)
                current = child.text(2).strip()
                if isinstance(original, str) and current and current != original:
                    note = ""
                    others = counts.get(original, 1) - 1
                    if others:
                        # The edit is addressed by offset, so the copies stay
                        # put. Say so; the opposite is what a modder expects.
                        note = f"{_count(others, 'other row')} still points at the old file"
                    companions = self._companion_notes(current)
                    if companions:
                        note = (note + "; " if note else "") + companions[0]
                    lines.append(
                        ChangeLine(field=child.text(0), before=original, after=current, note=note)
                    )
                    problem = self._warning_for(original, current)
                    if problem:
                        warnings.append(f"{child.text(0)}: {problem}")
                stored = child.data(0, _PLACEMENT_ROLE)
                if stored:
                    offset, type_name, original_raw, _member = stored
                    pending = self._placement_edits.get(offset)
                    if pending:
                        lines.append(
                            ChangeLine(
                                field=child.text(0),
                                before=describe_value(type_name, pending[0]),
                                after=describe_value(type_name, pending[1]),
                            )
                        )
        return lines, warnings

    def _confirm_changes(self) -> bool:
        """Show the review and report whether the modder went ahead.

        Kept separate from :meth:`_apply_changes` so it can be driven without a
        modal loop. ``_apply_changes`` is signal-connected; this is not, so
        replacing it on an instance is safe.
        """
        lines, warnings = self._pending_changes()
        return bool(PrefabChangeReview(lines, warnings, parent=self).exec())

    def _apply_changes(self) -> None:
        if not self._can_edit():
            return
        replacements = self.collect_path_edits()
        if not replacements and not self._placement_edits:
            self._log("Nothing to apply: nothing was changed.")
            return
        if not self._confirm_changes():
            self._log("Nothing written: you cancelled at the review step.")
            return
        try:
            # Placements first: they are fixed-size, so their byte offsets are
            # still valid. Path edits move bytes and would invalidate them.
            payload = self._original
            if self._placement_edits:
                moved = rewrite_prefab_placements(
                    payload,
                    self._placement_edits,
                    source_digest=prefab_source_digest(self._original),
                )
                payload = moved.data
                for line in moved.proof_lines:
                    self._log(line)
            result = rewrite_prefab_paths(payload, replacements)
        except Exception as exc:  # noqa: BLE001 - reported to the user
            self._log(f"Refused: {exc}")
            return
        delta = result.byte_delta
        movement = "grew" if delta > 0 else "shrank" if delta < 0 else "stayed the same"
        summary = (
            f"Applied {len(result.edits)} path change(s) and "
            f"{len(self._placement_edits)} placement(s); file {movement}"
            f"{f' by {abs(delta)} byte(s)' if delta else ''}, "
            f"{result.relocated_pointers} internal reference(s) rewritten to match."
        )
        for edit in result.edits:
            self._log(f"{edit.old_text} -> {edit.new_text}")
            for note in self._companion_notes(edit.new_text):
                self._log(f"    {note}")
        self._log(summary)
        # Say plainly that nothing is on disk yet. Without this the log reads
        # like a completed save, and the export prompt that appears on close
        # comes as a surprise.
        self._log(
            "Nothing has been written yet. Close this window and you will be asked "
            "where to save the mod package."
        )
        self.result_payload = PrefabInspectorResult(data=result.data, summary=summary)
        if self._on_save is not None:
            self._on_save(result.data, summary)


__all__ = ["PrefabInspectorDialog", "PrefabInspectorResult"]
