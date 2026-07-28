"""Guards for the editors the Prefab Inspector opens.

A separate subject from the inspector itself: these are the small dialogs a
modder is handed once they act on a row -- the transform editor, the value
editor, the file picker and the change review -- and they carry their own
rules about what may be written and what has to be acknowledged first.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cdmw.domain.archives.prefab_values import Placement, write_placement  # noqa: E402
from cdmw.ui.archive_browser.prefab_inspector_widgets import (  # noqa: E402
    AssetPickerDialog,
    PlacementEditDialog,
)


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pole_placement() -> Placement:
    """A weapon child socket: pitch 90, where the Euler round trip is worst."""
    return Placement(
        scale=(1.0, 1.0, 1.0),
        rotation=(0.5, 0.5, -0.5, 0.5),
        position=(1.25, -3.5, 0.75),
    )


def test_position_only_edit_leaves_rotation_and_scale_untouched(qt_app: QApplication) -> None:
    """The 90-degree silent rotation. Editing position must not touch rotation."""
    source = _pole_placement()
    dialog = PlacementEditDialog(source, title="socket")
    dialog._position[0].setValue(9.5)
    dialog._accept()

    result = dialog.result_placement
    assert result is not None
    assert result.position[0] == 9.5
    assert result.rotation == source.rotation
    assert result.scale == source.scale
    assert write_placement(result)[12:28] == write_placement(source)[12:28]


def test_rotation_only_edit_leaves_position_untouched(qt_app: QApplication) -> None:
    source = _pole_placement()
    dialog = PlacementEditDialog(source, title="socket")
    dialog._rotation[0].setValue(45.0)
    dialog._accept()

    result = dialog.result_placement
    assert result is not None
    assert result.position == source.position
    assert result.rotation != source.rotation


def test_opening_and_accepting_without_typing_changes_nothing(qt_app: QApplication) -> None:
    """Open, click OK, and the bytes must be identical -- including at a pole."""
    source = _pole_placement()
    dialog = PlacementEditDialog(source, title="socket")
    dialog._accept()
    assert write_placement(dialog.result_placement) == write_placement(source)


def test_pole_orientation_is_warned_about(qt_app: QApplication) -> None:
    at_pole = PlacementEditDialog(_pole_placement(), title="socket")
    assert at_pole.pole_warning.isVisibleTo(at_pole)

    level = Placement(scale=(1.0, 1.0, 1.0), rotation=(0.0, 0.0, 0.0, 1.0), position=(0.0, 0.0, 0.0))
    assert not PlacementEditDialog(level, title="body").pole_warning.isVisibleTo(
        PlacementEditDialog(level, title="body")
    )


def test_placement_editor_names_what_position_is_measured_from(qt_app: QApplication) -> None:
    source = Placement(scale=(1.0, 1.0, 1.0), rotation=(0.0, 0.0, 0.0, 1.0), position=(1.0, 2.0, 3.0))
    world = PlacementEditDialog(source, title="Placement", space="world")
    assert "world coordinates" in world.space_label.text()

    offset = PlacementEditDialog(source, title="Placement", space="offset")
    assert "offset from the object" in offset.space_label.text()

    # An unrecognised member must not be described as world by default.
    unknown = PlacementEditDialog(source, title="Placement", space="unknown")
    assert "not established" in unknown.space_label.text()
    assert "world coordinates" not in unknown.space_label.text()


def test_warnings_block_the_review_until_acknowledged(qt_app: QApplication) -> None:
    """A warning you can scroll past is one the tool decided not to act on."""
    from PySide6.QtWidgets import QDialogButtonBox

    from cdmw.ui.archive_browser.prefab_inspector_review import ChangeLine, PrefabChangeReview

    change = ChangeLine(field="Mesh", before="a.pac", after="b.dds")
    review = PrefabChangeReview([change], ["Mesh: that is a texture, not a model"])
    ok = review.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert review.acknowledge is not None
    assert not ok.isEnabled()
    assert "Tick the box" in ok.toolTip()
    review.acknowledge.setChecked(True)
    assert ok.isEnabled()


def test_a_clean_change_needs_no_acknowledgement(qt_app: QApplication) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    from cdmw.ui.archive_browser.prefab_inspector_review import ChangeLine, PrefabChangeReview

    review = PrefabChangeReview([ChangeLine(field="Mesh", before="a.pac", after="b.pac")], [])
    assert review.acknowledge is None
    assert review.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_the_value_editor_refuses_a_number_that_does_not_fit(qt_app: QApplication) -> None:
    from cdmw.ui.archive_browser.prefab_inspector_widgets import ValueEditDialog

    editor = ValueEditDialog("uint8", b"\x05", title="Flags")
    assert not editor.error.isVisibleTo(editor)
    # Drive the encode path directly with an out-of-range value: the spin box
    # clamps, so the guard has to be on the encoder, not on the widget.
    editor._current = lambda: 999
    editor._accept()
    assert editor.result_raw is None
    assert editor.error.isVisibleTo(editor)
    assert "does not fit" in editor.error.text()


def test_the_review_says_a_model_swap_takes_its_companions_with_it(qt_app: QApplication) -> None:
    """The engine resolves material and physics from the model's path.

    So retargeting a mesh silently changes those too, and the review is the
    only place a modder finds out before the game does.
    """
    from cdmw.ui.archive_browser.prefab_inspector_review import ChangeLine, PrefabChangeReview

    with_companion = ChangeLine(
        field="Mesh",
        before="character/model/a/b.pac",
        after="character/model/a/c.pac",
        note="Material (textures and material assignments) comes from character/modelproperty/a/c.pac_xml",
    )
    review = PrefabChangeReview([with_companion], [])
    assert review.companion_note is not None
    text = review.companion_note.text()
    assert "material and physics" in text
    assert "not copied into the package" in text


def test_a_change_with_no_companions_says_nothing_about_them(qt_app: QApplication) -> None:
    from cdmw.ui.archive_browser.prefab_inspector_review import ChangeLine, PrefabChangeReview

    review = PrefabChangeReview([ChangeLine(field="Socket", before="a", after="b")], [])
    assert review.companion_note is None


def test_the_picker_says_why_the_list_is_short(qt_app: QApplication) -> None:
    from cdmw.ui.archive_browser.prefab_inspector_widgets import AssetPickerDialog

    quiet = AssetPickerDialog(("a/b.pac",))
    assert not quiet.note.isVisibleTo(quiet)

    explained = AssetPickerDialog(("a/b.pac",), note="only same length works here")
    assert explained.note.isVisibleTo(explained)
    assert "same length" in explained.note.text()


