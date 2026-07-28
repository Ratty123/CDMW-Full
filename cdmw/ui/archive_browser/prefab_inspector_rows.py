"""Turning a decoded prefab into the rows a modder reads.

Separate from the dialog because it is a separate job: the dialog is a window
with tabs and buttons, this decides what a prefab *looks* like -- which objects
become headings, which fields become rows, what each row is called, which rows
can be changed, and what to show for a file the walk could not finish reading.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from cdmw.domain.archives.prefab_glossary import (
    asset_role,
    describe_component,
    describe_field,
    describe_fields,
    is_asset_path,
    value_kind_hint,
)
from cdmw.domain.archives.prefab_values import describe_value, editable_kind, read_placement
from cdmw.services.prefab_structure_service import recover_pointee_strings
from cdmw.ui.archive_browser.prefab_inspector_editing import (
    EDIT_ROLE,
    OFFSET_ROLE,
    PLACEMENT_ROLE,
    USED_ROLE,
    VALUE_ROLE,
)


def _count(number: int, noun: str, plural: str = "") -> str:
    """``1 object`` / ``2 objects`` -- never ``1 object(s)``."""
    word = noun if number == 1 else (plural or f"{noun}s")
    return f"{number:,} {word}"


class PrefabRowsMixin:
    """Builds the object tree for :class:`PrefabInspectorDialog`."""

    def _populate_objects(self) -> None:
        document = self._document
        if document is None:
            return
        editable = self._can_edit()
        self._add_recovered_rows(document)
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
            self._add_number_rows(
                node, obj.numbers, stated_type=getattr(obj, "type_source", "stated") == "stated"
            )
            self._add_fields_row(
                node,
                obj.member_names,
                obj.values,
                obj.numbers,
                self._collection_members(obj.component_type),
            )
            node.setExpanded(True)

    def _add_recovered_rows(self, document: object) -> None:
        """List the files a partly-read prefab references.

        The walk stops at the first structure it cannot follow, and 45.6% of
        shipped prefabs stop somewhere -- until now those showed only the
        handful of rows read before the stop, which reads as "this prefab
        barely references anything" rather than "this tool stopped early".
        Pointer sites are found by the exact identity test instead, which does
        not depend on the walk reaching them.
        """
        if document.walk_complete:
            return
        known = {item.offset for item in document.all_strings()}
        recovered = [
            item
            for item in recover_pointee_strings(
                self._original, document.blob_offset, document.blob_length
            )
            if item.offset not in known and is_asset_path(item.text)
        ]
        if not recovered:
            return
        parent = QTreeWidgetItem(
            [
                "Files found past the stop",
                f"{_count(len(recovered), 'reference')} recovered without the walk",
                "",
            ]
        )
        parent.setToolTip(
            1,
            "These come from the file's own pointer records rather than from reading "
            "its structure, so they are the paths this prefab uses even though the "
            "tool could not follow the whole file.",
        )
        self.tree.addTopLevelItem(parent)
        for item in recovered:
            # No member name exists for these -- the walk never reached them, so
            # nothing says which field they belong to, and inventing one would
            # be the sort of plausible lie the rest of this dialog avoids. The
            # file's own name is what identifies it, and a column of bare
            # basenames is scannable where a column of full paths is not.
            row = QTreeWidgetItem(
                [
                    item.text.rsplit("/", 1)[-1],
                    f"a {asset_role(item.text).lower()} file",
                    item.text,
                ]
            )
            row.setData(2, EDIT_ROLE, item.text)
            row.setData(2, OFFSET_ROLE, int(item.offset))
            if self._can_swap_same_length():
                row.setFlags(row.flags() | Qt.ItemFlag.ItemIsEditable)
                row.setToolTip(
                    2,
                    "Double-click to swap this. Because the tool could not read the "
                    "whole file, the new name has to be exactly the same length - "
                    "then nothing in the file moves.",
                )
            else:
                row.setToolTip(2, item.text)
            parent.addChild(row)
        parent.setExpanded(True)

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
        row.setData(2, EDIT_ROLE, value)
        row.setData(2, OFFSET_ROLE, int(offset))
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

    def _add_number_rows(
        self,
        parent: QTreeWidgetItem,
        numbers: tuple[object, ...],
        *,
        stated_type: bool = True,
    ) -> None:
        """Show the numeric values: placement, opacity, flags and the like.

        `stated_type` is False when the walk had to infer this object's component
        type rather than read it from the file. Such an object can be entirely wrong
        while still looking complete -- see `PrefabObject.type_source` -- so its rows
        are shown but never made editable. The edit would be byte-safe and land on a
        field we cannot name with confidence, which is the worse failure: a modder
        would have no way to tell it went to the wrong place.
        """
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
            if stated_type and self._can_edit() and read_placement(number.raw) is not None:
                row.setData(
                    0,
                    PLACEMENT_ROLE,
                    (number.offset, number.type_name, number.raw, number.name),
                )
                row.setToolTip(2, "Double-click to move, rotate or rescale this.")
            elif stated_type and self._can_edit() and editable_kind(number.type_name, number.raw):
                # Only members whose declared type and byte width agree. Writing
                # a value whose type is unconfirmed is how a readable file
                # becomes a broken one.
                row.setData(
                    0,
                    VALUE_ROLE,
                    (number.offset, number.type_name, number.raw, number.name),
                )
                row.setToolTip(2, "Double-click to change this value.")
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
