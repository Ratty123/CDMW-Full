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
    editable_kind,
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
from cdmw.ui.archive_browser.prefab_inspector_editing import (
    CHANGED_COLOUR,
    EDIT_ROLE,
    OFFSET_ROLE,
    PLACEMENT_ROLE,
    PrefabEditingMixin,
    USED_ROLE,
    VALUE_ROLE,
    WARNING_COLOUR,
)
from cdmw.ui.archive_browser.prefab_inspector_review import PrefabChangeReview
from cdmw.ui.archive_browser.prefab_inspector_rows import PrefabRowsMixin
from cdmw.ui.archive_browser.prefab_inspector_structure import PrefabStructureMixin
from cdmw.ui.archive_browser.prefab_inspector_widgets import (
    AssetPickerDialog,
    PlacementEditDialog,
    ValueEditDialog,
)
from cdmw.services.prefab_structure_service import (
    asset_extension_for,
    decode_prefab_binary,
    walk_is_determined,
    path_is_known,
    PrefabPathEdit,
    PrefabRewriteResult,
    recover_pointee_strings,
    prefab_source_digest,
    rewrite_prefab_paths,
    rewrite_prefab_paths_same_length,
    rewrite_prefab_placements,
)

# Owned by the editing mixin; aliased so call sites and tests keep one spelling.
_EDIT_ROLE = EDIT_ROLE
_USED_ROLE = USED_ROLE
_PLACEMENT_ROLE = PLACEMENT_ROLE
_OFFSET_ROLE = OFFSET_ROLE
_VALUE_ROLE = VALUE_ROLE
_CHANGED_COLOUR = CHANGED_COLOUR
_WARNING_COLOUR = WARNING_COLOUR


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


class PrefabInspectorDialog(PrefabRowsMixin, PrefabEditingMixin, PrefabStructureMixin, QDialog):
    """Structure browser and path editor for a single prefab payload."""

    def __init__(
        self,
        data: bytes,
        *,
        title: str = "Prefab Inspector",
        parent: QWidget | None = None,
        on_save: Callable[[bytes, str], None] | None = None,
        known_paths: Mapping[str, Sequence[str]] | None = None,
        find_users: Callable[[str], Sequence[str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(980, 660)
        # `_opened` is the file as it arrived and never changes; `_original` is
        # the bytes the current rows were read from. They differ once an object
        # has been added or removed, because that is applied immediately rather
        # than held as a pending edit -- see prefab_inspector_structure.
        self._opened = bytes(data or b"")
        self._original = self._opened
        self._structural_changes: list[str] = []
        self._on_save = on_save
        self._known_paths: Mapping[str, Sequence[str]] = dict(known_paths or {})
        # Supplied by the caller, which owns archive access and threading. The
        # dialog is modal, so it must not go reading archives itself.
        self._find_users = find_users
        # (expected_old, new) per offset, for every fixed-size value: the
        # expected bytes are what makes the staleness check able to fail.
        self._value_edits: dict[int, tuple[bytes, bytes]] = {}
        self.result_payload: PrefabInspectorResult | None = None
        self._document: object | None = None
        self._error = ""
        # Computed once: it costs a second decode, and nothing about it changes
        # while the dialog is open.
        self._determined = True
        try:
            self._document = decode_prefab_binary(self._original)
            self._determined = walk_is_determined(self._original)
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
        if not self._determined:
            # ~1% of prefabs. Both collection readings close the blob, so the
            # walk looks clean while the offsets could belong to either parse.
            return (
                f"{_count(objects, 'object')}. Editing is off for this one: the file does "
                "not settle how its collections are sized, and two different readings of "
                "it are equally valid. The values below are one of them, so an edit could "
                "land on the wrong field without anything looking wrong."
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
        # Where it stopped, not just that it stopped: "cannot follow this
        # structure" is not something a modder can report or act on.
        where = ""
        if document.walk_stop_offset >= 0:
            where = (
                f" It got {document.walk_progress:.0%} of the way through and stopped at "
                f"byte {document.walk_stop_offset:,} ({document.walk_note})."
            )
        return (
            f"Partly read. {head}{where} What is shown was read from the file; the rest "
            "uses a structure this tool cannot follow yet. You can still swap a file for "
            "another whose name is exactly the same length - that moves nothing in the "
            f"file - but anything that would resize it is refused.{caveat}"
        )

    def _can_edit(self) -> bool:
        """Full editing, which needs the structure to relocate bytes.

        `_determined` excludes the roughly 1% of prefabs whose collection widths
        the file itself does not decide: both readings close the blob, so the
        walk looks clean while the offsets could belong to either parse. Editing
        one would write a plausible byte to a wrong place, which is precisely the
        failure that is impossible to notice afterwards.
        """
        return (
            self._document is not None
            and self._document.walk_complete
            and self._determined
        )

    def _can_swap_same_length(self) -> bool:
        """Retargets that move nothing, which need no structure at all.

        A replacement of identical byte length leaves every pointer, pointee
        length and header size exactly where it was, so it is safe on a prefab
        the walk could not finish. Verified on 669 partly-read prefabs.
        """
        return self._document is not None

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
        # Wrapped, or the sentence sets the dialog's minimum width: an unwrapped
        # QLabel demands its whole line, and this one grew past 1,000px when the
        # row-menu note was added -- which silently made the window unshrinkable
        # on a laptop screen. Wrapping costs a known trap in return, that a
        # wrapped label reports a one-line height, so the height is set too.
        self.objects_hint = QLabel(self._objects_hint())
        self.objects_hint.setWordWrap(True)
        self.objects_hint.setMinimumHeight(self.objects_hint.fontMetrics().height() * 2)
        box.addWidget(self.objects_hint)
        # Most prefabs are one object and two rows, so the filter stays out of
        # the way -- but the tail runs to 1,126 objects and 2,252 rows, and 87
        # of the 6,522 readable prefabs carry more than 50 objects. Those are
        # unusable without this.
        controls = QHBoxLayout()
        self.object_filter = QLineEdit()
        self.object_filter.setPlaceholderText("Filter by name, field, value or path...")
        self.object_filter.setClearButtonEnabled(True)
        self.object_filter.textChanged.connect(lambda _text: self._apply_object_filter())
        controls.addWidget(self.object_filter, 1)
        self.changeable_only_box = QCheckBox("Only rows I can change")
        self.changeable_only_box.setToolTip(
            "Hide everything that is read-only, so what is left is what you can edit."
        )
        self.changeable_only_box.toggled.connect(lambda _on: self._apply_object_filter())
        controls.addWidget(self.changeable_only_box)
        box.addLayout(controls)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Object / field", "What it is", "Value"])
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.itemChanged.connect(self._note_pending_edit)
        self.tree.itemSelectionChanged.connect(self._refresh_browse_state)
        self.tree.itemDoubleClicked.connect(self._edit_value_row)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_row_menu)
        copy = QShortcut(QKeySequence.StandardKey.Copy, self.tree)
        copy.activated.connect(self._copy_selected_value)
        self._populate_objects()
        box.addWidget(self.tree, 1)
        self.match_count = QLabel("")
        self.match_count.setWordWrap(True)
        box.addWidget(self.match_count)
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
        if any(
            read_placement(number.raw) is None and editable_kind(number.type_name, number.raw)
            for number in self._all_numbers()
        ):
            actions.append("a setting to change it")
        how = f"Double-click {' or '.join(actions)}. " if actions else ""
        # Adding an object is only reachable from the row menu, and a feature
        # nobody right-clicks to find is a feature nobody has.
        add = (
            "Right-click an object heading to duplicate or remove it. "
            if self._has_resizable_objects()
            else ""
        )
        return (
            f"Each row is one piece of this prefab. {how}{add}"
            "Ctrl+C copies the selected value."
        )

    def _has_resizable_objects(self) -> bool:
        """Is any object here a collection element the resizer can act on?"""
        document = self._document
        if document is None or not self._can_edit():
            return False
        return any(
            len(item.elements) == item.count and item.elements
            for item in getattr(document, "collections", ())
        )

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
        if item.data(0, PLACEMENT_ROLE):
            move = QAction("Move, rotate or rescale...", menu)
            move.triggered.connect(lambda: self._edit_placement(item, 2))
            menu.addAction(move)
        if item.data(0, VALUE_ROLE):
            change = QAction("Change this value...", menu)
            change.triggered.connect(lambda: self._edit_number(item, 2))
            menu.addAction(change)
        original = item.data(2, _EDIT_ROLE)
        if self._find_users is not None and isinstance(original, str) and is_asset_path(original):
            users = QAction("Where else is this used?", menu)
            users.setToolTip("Which other prefabs reference this same file.")
            users.triggered.connect(lambda: self._show_other_users(original))
            menu.addAction(users)
        if self.row_has_pending_change(item):
            undo = QAction("Undo this row", menu)
            undo.setToolTip("Put this one row back, keeping your other changes.")
            undo.triggered.connect(lambda: self._revert_row(item))
            menu.addAction(undo)
        if self._can_edit():
            self.add_structure_actions(menu, item)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _edit_placement(self, item: QTreeWidgetItem, _column: int) -> None:
        """Open the placement editor for a transform row."""
        stored = item.data(0, _PLACEMENT_ROLE)
        if not stored:
            return
        offset, type_name, original_raw, member_name = stored
        pending = self._value_edits.get(offset)
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
            self._value_edits.pop(offset, None)
        else:
            self._value_edits[offset] = (original_raw, new_raw)
        item.setText(2, describe_value(type_name, new_raw))
        item.setForeground(
            2, QBrush(_CHANGED_COLOUR) if offset in self._value_edits else QBrush()
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
        candidates = tuple(self._known_paths.get(asset_extension_for(original), ()))
        if self._can_edit():
            return candidates
        # Only same-length replacements can be written on a partly-read prefab.
        # Offering the rest means the modder picks one, works through the
        # review, and is refused at the last step for a reason they were given
        # no chance to see.
        width = len(original.encode("utf-8"))
        return tuple(item for item in candidates if len(item.encode("utf-8")) == width)

    def _browse_for_selected_row(self) -> None:
        item = self.tree.currentItem()
        candidates = self._candidates_for(item)
        if item is None or not candidates:
            return
        picker = AssetPickerDialog(
            candidates,
            current=item.text(2),
            note=(
                ""
                if self._can_edit()
                else (
                    "This prefab is only partly readable, so the list is limited to "
                    "names of exactly the same length - those are the swaps that move "
                    "nothing in the file."
                )
            ),
            parent=self,
        )
        if picker.exec() and picker.chosen:
            item.setText(2, picker.chosen)

    def _show_other_users(self, path: str) -> None:
        """Report which other prefabs reference the same file.

        Retargeting one prefab tells a modder nothing about whether the change
        covers a set or is one of twenty, and the answer decides whether the
        mod works.
        """
        if self._find_users is None:
            return
        try:
            users = tuple(self._find_users(path))
        except Exception as exc:  # noqa: BLE001 - reported, never raised at a modal
            self._log(f"Could not check what else uses {path}: {exc}")
            return
        others = tuple(item for item in users if item)
        name = path.rsplit("/", 1)[-1]
        if not others:
            self._log(f"No other prefab in the archives references {name}.")
            return
        self._log(f"{_count(len(others), 'other prefab')} also reference {name}:")
        for item in others[:40]:
            self._log(f"    {item}")
        if len(others) > 40:
            self._log(f"    ... and {len(others) - 40:,} more")

    def _refresh_pending_state(self) -> None:
        replacements = self.collect_replacements()
        warnings = [
            self._warning_for(old, new)
            for old, new in replacements.items()
            if self._warning_for(old, new)
        ]
        pending = len(replacements) + len(self._value_edits)
        # A structural change is already in the working payload, so it counts as
        # something to save even with no row edited -- otherwise adding an object
        # and pressing Save would report "nothing was changed".
        structural = len(self._structural_changes)
        self.apply_button.setEnabled(
            self._can_swap_same_length() and bool(pending or structural)
        )
        self.revert_button.setEnabled(bool(pending or structural))
        if not pending and not structural:
            self.status.setText("")
            return
        parts = []
        if structural:
            parts.append(f"{structural} object change{'' if structural == 1 else 's'}")
        if replacements:
            parts.append(f"{len(replacements)} path change{'' if len(replacements) == 1 else 's'}")
        if self._value_edits:
            moved = len(self._value_edits)
            parts.append(f"{moved} value{'' if moved == 1 else 's'} changed in place")
        note = " and ".join(parts) + " ready to apply."
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
                stored = child.data(0, _PLACEMENT_ROLE) or child.data(0, _VALUE_ROLE)
                if stored:
                    offset, type_name, original_raw, member_name = stored
                    if offset in self._value_edits:
                        child.setText(2, describe_value(type_name, original_raw))
                        child.setForeground(2, QBrush())
        self._value_edits.clear()
        self._log("Reverted to the values stored in the file.")
        # Last: it rebuilds the tree, so the row work above has to be done with
        # the rows that are currently there.
        self.revert_structural_changes()
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

    def _confirm_changes(self) -> bool:
        """Show the review and report whether the modder went ahead.

        Kept separate from :meth:`_apply_changes` so it can be driven without a
        modal loop. ``_apply_changes`` is signal-connected; this is not, so
        replacing it on an instance is safe.
        """
        lines, warnings = self._pending_changes()
        return bool(PrefabChangeReview(lines, warnings, parent=self).exec())

    def _apply_changes(self) -> None:
        if not self._can_swap_same_length():
            return
        replacements = self.collect_path_edits()
        if not replacements and not self._value_edits and not self._structural_changes:
            self._log("Nothing to apply: nothing was changed.")
            return
        if not self._confirm_changes():
            self._log("Nothing written: you cancelled at the review step.")
            return
        if not replacements and not self._value_edits:
            # Structural changes only. They are already in the working payload,
            # applied when the modder made them, so there is nothing left to
            # rewrite -- handing the payload straight over is the whole job.
            self._finish_apply(
                PrefabRewriteResult(
                    data=self._original,
                    edits=(),
                    byte_delta=len(self._original) - len(self._opened),
                    relocated_pointers=0,
                    proof_lines=(),
                )
            )
            return
        try:
            # Placements first: they are fixed-size, so their byte offsets are
            # still valid. Path edits move bytes and would invalidate them.
            payload = self._original
            if not self._can_edit():
                # Nothing may move, so the same-length path is the only one that
                # is provably safe here -- and it needs no structure.
                result = rewrite_prefab_paths_same_length(payload, replacements)
                self._finish_apply(result)
                return
            if self._value_edits:
                moved = rewrite_prefab_placements(
                    payload,
                    self._value_edits,
                    source_digest=prefab_source_digest(self._original),
                )
                payload = moved.data
                for line in moved.proof_lines:
                    self._log(line)
            result = rewrite_prefab_paths(payload, replacements)
        except Exception as exc:  # noqa: BLE001 - reported to the user
            self._log(f"Refused: {exc}")
            return
        self._finish_apply(result)

    def _finish_apply(self, result) -> None:
        """Report what was written and hand the payload back."""
        delta = len(result.data) - len(self._opened)
        movement = "grew" if delta > 0 else "shrank" if delta < 0 else "stayed the same"
        structural = (
            f"{len(self._structural_changes)} object change(s), "
            if self._structural_changes
            else ""
        )
        summary = (
            f"Applied {structural}{len(result.edits)} path change(s) and "
            f"{len(self._value_edits)} in-place value(s); file {movement}"
            f"{f' by {abs(delta)} byte(s)' if delta else ''}, "
            f"{result.relocated_pointers} internal reference(s) rewritten to match."
        )
        for description in self._structural_changes:
            self._log(description)
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
