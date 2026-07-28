"""Behaviour guards for adding and removing objects in the Prefab Inspector.

These drive the real dialog. The thing worth guarding is not that the menu
appears -- it is that a structural change and an offset-keyed change can never
be in flight together, because a splice moves every offset after it and a stale
one would still look plausible.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from cdmw.core.prefab_binary import decode_prefab_binary  # noqa: E402
from cdmw.ui.archive_browser.prefab_inspector_dialog import PrefabInspectorDialog  # noqa: E402
from cdmw.ui.archive_browser.prefab_inspector_editing import (  # noqa: E402
    EDIT_ROLE,
    OBJECT_ROLE,
)
from tests.prefab_collection_builder import build_with_collection  # noqa: E402


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dialog(names=("Alpha", "Beta", "Gamma")) -> PrefabInspectorDialog:
    return PrefabInspectorDialog(build_with_collection(names), title="test")


def _object_rows(dialog: PrefabInspectorDialog) -> list:
    rows = []
    for index in range(dialog.tree.topLevelItemCount()):
        item = dialog.tree.topLevelItem(index)
        if isinstance(item.data(0, OBJECT_ROLE), int):
            rows.append(item)
    return rows


def _row_named(dialog: PrefabInspectorDialog, label: str):
    return next(item for item in _object_rows(dialog) if item.text(0) == label)


def _menu_labels(dialog: PrefabInspectorDialog, item) -> list[str]:
    menu = QMenu()
    dialog.add_structure_actions(menu, item)
    return [action.text() for action in menu.actions() if action.text()]


def test_object_rows_carry_the_offset_that_finds_their_element(qt_app) -> None:
    """Without it a row cannot be turned into a collection element, and the
    menu has nothing to act on."""
    dialog = _dialog()

    rows = _object_rows(dialog)

    assert [item.text(0) for item in rows] == ["Alpha", "Beta", "Gamma"]
    assert all(item.data(0, OBJECT_ROLE) > 0 for item in rows)
    assert dialog._element_site_for(rows[1]).element_index == 1


def test_duplicating_an_object_adds_it_to_the_tree(qt_app) -> None:
    dialog = _dialog()
    site = dialog._element_site_for(_row_named(dialog, "Beta"))

    dialog._resize_at(site, "Beta", insert=True)

    assert [item.text(0) for item in _object_rows(dialog)] == [
        "Alpha", "Beta", "Beta", "Gamma",
    ]
    assert len(dialog._structural_changes) == 1
    assert dialog.apply_button.isEnabled(), "an object change is something to save"


def test_removing_an_object_takes_it_out_of_the_tree(qt_app, monkeypatch) -> None:
    dialog = _dialog()
    monkeypatch.setattr(dialog, "_confirm_removal", lambda label, site: True)
    site = dialog._element_site_for(_row_named(dialog, "Beta"))

    dialog._resize_at(site, "Beta", insert=False)

    assert [item.text(0) for item in _object_rows(dialog)] == ["Alpha", "Gamma"]


def test_a_cancelled_removal_changes_nothing(qt_app, monkeypatch) -> None:
    dialog = _dialog()
    monkeypatch.setattr(dialog, "_confirm_removal", lambda label, site: False)
    before = dialog._original
    site = dialog._element_site_for(_row_named(dialog, "Beta"))

    dialog._resize_at(site, "Beta", insert=False)

    assert dialog._original == before
    assert not dialog._structural_changes


def test_the_tree_is_rebuilt_from_the_new_bytes_not_patched(qt_app) -> None:
    """Every offset in the old rows came from the old payload. Re-decoding is
    the only way to be sure none of them survived."""
    dialog = _dialog()
    site = dialog._element_site_for(_row_named(dialog, "Alpha"))

    dialog._resize_at(site, "Alpha", insert=True)

    fresh = decode_prefab_binary(dialog._original)
    assert dialog._document.walk_complete
    assert [obj.offset for obj in dialog._document.objects] == [
        obj.offset for obj in fresh.objects
    ]


def test_a_pending_row_edit_blocks_a_structural_change(qt_app, monkeypatch) -> None:
    """A splice moves every offset after it, so a queued edit would land on the
    wrong field -- and on a field that still looks like a plausible target."""
    dialog = _dialog()
    warned: list[str] = []
    monkeypatch.setattr(
        "cdmw.ui.archive_browser.prefab_inspector_structure.QMessageBox.information",
        lambda *args, **kwargs: warned.append(args[1]),
    )
    edited = next(
        child
        for row in _object_rows(dialog)
        for child in (row.child(i) for i in range(row.childCount()))
        if isinstance(child.data(2, EDIT_ROLE), str)
    )
    edited.setText(2, "asset/something_else.pac")
    before = dialog._original
    site = dialog._element_site_for(_row_named(dialog, "Beta"))

    dialog._resize_at(site, "Beta", insert=True)

    assert warned, "the modder is told why, rather than the change silently failing"
    assert dialog._original == before
    assert not dialog._structural_changes


def test_undo_all_changes_puts_the_object_list_back(qt_app) -> None:
    dialog = _dialog()
    opened = dialog._opened
    site = dialog._element_site_for(_row_named(dialog, "Beta"))
    dialog._resize_at(site, "Beta", insert=True)

    dialog._revert_changes()

    assert dialog._original == opened
    assert not dialog._structural_changes
    assert [item.text(0) for item in _object_rows(dialog)] == ["Alpha", "Beta", "Gamma"]
    assert not dialog.apply_button.isEnabled()


def test_saving_a_structural_change_alone_hands_over_the_resized_bytes(qt_app, monkeypatch) -> None:
    """There is nothing left to rewrite -- the splice already happened -- so the
    save path must not fall through the 'nothing was changed' branch."""
    dialog = _dialog()
    monkeypatch.setattr(dialog, "_confirm_changes", lambda: True)
    site = dialog._element_site_for(_row_named(dialog, "Beta"))
    dialog._resize_at(site, "Beta", insert=True)

    dialog._apply_changes()

    assert dialog.result_payload is not None
    assert dialog.result_payload.data == dialog._original
    assert "object change" in dialog.result_payload.summary
    assert decode_prefab_binary(dialog.result_payload.data).walk_complete


def test_removing_the_last_object_is_offered_but_disabled(qt_app) -> None:
    """Refusing in the menu explains itself; refusing after the click does not."""
    dialog = _dialog(("Only",))
    row = _row_named(dialog, "Only")

    menu = QMenu()
    dialog.add_structure_actions(menu, row)
    actions = {action.text(): action for action in menu.actions() if action.text()}

    assert actions["Duplicate this object"].isEnabled()
    assert not actions["Remove this object"].isEnabled()
    assert "only object" in actions["Remove this object"].toolTip()


def test_a_field_row_offers_no_structural_actions(qt_app) -> None:
    """Only objects that are collection elements can be added or removed. A
    field is not one, and neither is an object nested inside another."""
    dialog = _dialog()
    row = _row_named(dialog, "Alpha")

    assert _menu_labels(dialog, row.child(0)) == []
    assert dialog._element_site_for(row.child(0)) is None


def test_a_prefab_that_does_not_decode_offers_nothing(qt_app) -> None:
    dialog = PrefabInspectorDialog(b"not a prefab", title="test")

    assert dialog._element_site_for(None) is None
    assert not dialog._can_edit()


def test_the_hint_says_the_row_menu_exists(qt_app) -> None:
    """A feature only reachable by right-click is a feature nobody finds."""
    dialog = _dialog()

    assert "Right-click" in dialog._objects_hint()
    assert "duplicate or remove" in dialog._objects_hint()


def test_the_hint_stays_quiet_when_nothing_can_be_resized(qt_app) -> None:
    dialog = PrefabInspectorDialog(b"not a prefab", title="test")

    assert not dialog._has_resizable_objects()
    assert "Right-click" not in dialog._objects_hint()
