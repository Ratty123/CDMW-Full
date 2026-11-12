"""Drafts & Mods: Combine into One Mod and the Game file column (GitHub issue 31), through the real page.

The page is built as the shell builds it (``tool_tabs._create_saved_work_tab``):
a real ``SavedWorkSourceResolver`` over an Archive Browser stand-in whose only
part is the game folder field the user sets. Builds are made by the real loose
writer and publish step. Buttons are pressed; only file dialogs are not shown.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import hashlib
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QLineEdit, QStyleOptionViewItem

from cdmw.domain.packages.game_file_label import ELLIPSIS
from cdmw.services.mesh_saved_work_service import add_built_mod_folder, list_saved_work
from cdmw.ui.mesh_editor import saved_work_combine
from cdmw.ui.mesh_editor.saved_work_page import SavedWorkPage
from cdmw.ui.mesh_editor.saved_work_sources import SavedWorkSourceResolver
from tests.test_mesh_build_combine import SHOULDER, UPPER, WING_TEXTURE, _build


@pytest.fixture(autouse=True)
def _owned_history(tmp_path, monkeypatch):
    # Build Mod and Combine keep authoring records in %LOCALAPPDATA%; keep them owned.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _wait(app, condition, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def _fingerprint(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


class _Setup(SimpleNamespace):
    pass


@pytest.fixture
def combine(tmp_path, app):
    """Two listed builds like the reporter's, a configured game folder and the page."""

    builds = tmp_path / "mods"
    builds.mkdir()
    skirt = _build(builds, "Skirt edit", {UPPER: (b"edited upper body", "0009")})
    wing = _build(builds, "Wing piece", {SHOULDER: (b"replacement shoulder", "0014")},
                  companions={WING_TEXTURE: b"DDS wing texture"})
    drafts = tmp_path / "drafts"
    for folder in (skirt, wing):
        add_built_mod_folder(drafts, folder)
    game = tmp_path / "game"
    (game / "0009").mkdir(parents=True)
    (game / "0009" / "0.pamt").write_bytes(b"owned stand-in table")
    archive = SimpleNamespace(archive_package_root_edit=QLineEdit(str(game)))
    page = SavedWorkPage(draft_root=drafts, source_resolver=SavedWorkSourceResolver(archive, None))
    messages: list[tuple[str, bool]] = []
    page.status_message_requested.connect(lambda text, error: messages.append((text, error)))
    page.resize(1400, 700)
    page.show()
    _wait(app, lambda: len(page.rows()) == 2)
    state = _Setup(app=app, page=page, drafts=drafts, game=game, archive=archive, skirt=skirt, wing=wing,
                   builds=builds, tmp=tmp_path, messages=messages)
    yield state
    flow = page.combine_flow
    if flow.dialog is not None:
        flow.cancel()
        _wait(app, lambda: flow.dialog is None)
    page.close()
    page.deleteLater()
    app.processEvents()


def _select(combine, *names: str) -> None:
    page, table = combine.page, combine.page.table
    table.clearSelection()
    model = table.selectionModel()
    flags = model.SelectionFlag.Select | model.SelectionFlag.Rows
    for index in range(table.rowCount()):
        if table.item(index, 1).text() in names:
            model.select(table.model().index(index, 0), flags)
    combine.app.processEvents()
    assert sorted(row.display_name for row in page._selected_rows()) == sorted(names)


def _open_review(combine):
    page = combine.page
    _select(combine, "Skirt edit", "Wing piece")
    assert page.combine_button.isEnabled(), page.combine_button.toolTip()
    page.combine_button.click()
    dialog = page.combine_flow.dialog
    assert dialog is not None
    _wait(combine.app, lambda: dialog.stage != saved_work_combine.STAGE_CHECKING)
    return dialog


def test_combine_needs_two_built_mods_and_the_button_and_command_say_why(combine):
    from cdmw.ui.commands.registry import command_registry

    page = combine.page
    registry = command_registry()
    assert saved_work_combine.COMMAND_ID in registry
    # The button and the command share one label (the catalogue key).
    assert page.combine_button.text() == saved_work_combine.LABEL == registry.get(saved_work_combine.COMMAND_ID).label
    _select(combine, "Skirt edit")
    assert not page.combine_button.isEnabled()
    assert page.combine_button.toolTip() == saved_work_combine.REASON_TOO_FEW
    assert registry.reason(saved_work_combine.COMMAND_ID) == saved_work_combine.REASON_TOO_FEW
    _select(combine, "Skirt edit", "Wing piece")
    assert page.combine_button.isEnabled()
    assert page.combine_button.toolTip() == saved_work_combine.ENABLED_TIP
    assert registry.reason(saved_work_combine.COMMAND_ID) == ""
    # The command runs the page's action: the same dialog opens.
    registry.run(saved_work_combine.COMMAND_ID)
    assert page.combine_flow.dialog is not None
    assert not page.combine_button.isEnabled()
    assert page.combine_button.toolTip() == saved_work_combine.REASON_BUSY


def test_combine_reason_refuses_drafts_item_packages_and_missing_folders(tmp_path):
    def row(**changes):
        values = dict(is_built_mod=True, is_item_package=False, mod_root=tmp_path)
        values.update(changes)
        return SimpleNamespace(**values)

    assert saved_work_combine.combine_reason([row(), row()]) == ""
    assert saved_work_combine.combine_reason([row(), row(is_built_mod=False)]) == saved_work_combine.REASON_NOT_BUILT
    assert saved_work_combine.combine_reason([row(), row(is_item_package=True)]) == \
        saved_work_combine.REASON_NOT_BUILT
    assert saved_work_combine.combine_reason([row(), row(mod_root=tmp_path / "gone")]) == \
        saved_work_combine.REASON_MISSING
    assert saved_work_combine.combine_reason([row(), row()], busy=True) == saved_work_combine.REASON_BUSY


def test_the_reporter_pair_becomes_one_listed_mod_through_the_page(combine):
    page, app = combine.page, combine.app
    before = {folder: _fingerprint(folder) for folder in (combine.skirt, combine.wing)}
    dialog = _open_review(combine)
    # The plan is shown before anything is written.
    assert dialog.stage == saved_work_combine.STAGE_REVIEW
    files = [dialog.files_list.item(index).text() for index in range(dialog.files_list.count())]
    # In the table's order (newest first); every file names the build it comes from.
    assert sorted(files) == sorted([f"{UPPER}  (Skirt edit)", f"{SHOULDER}  (Wing piece)",
                                    f"{WING_TEXTURE}  (Wing piece)"])
    assert dialog.layout_value.text() == "Loose mod for DMM"
    assert not dialog.shared_list.isVisibleTo(dialog)
    output = combine.tmp / "out" / "Combined armour"
    assert not output.exists() and not (combine.tmp / "out").exists()
    dialog.title_edit.setText("Combined armour")
    dialog.folder_edit.setText(str(output))
    dialog.combine_button.click()
    _wait(app, lambda: page.combine_flow.dialog is None)
    _wait(app, lambda: any(row.display_name == "Combined armour" for row in page.rows()))
    assert (output / UPPER).read_bytes() == b"edited upper body"
    assert (output / SHOULDER).read_bytes() == b"replacement shoulder"
    assert (output / WING_TEXTURE).read_bytes() == b"DDS wing texture"
    assert {folder: _fingerprint(folder) for folder in (combine.skirt, combine.wing)} == before
    assert combine.messages[-1] == (f"Combined mod written: {output.resolve()}", False)
    row = next(row for row in list_saved_work(combine.drafts) if row.display_name == "Combined armour")
    assert sorted(row.game_files) == sorted((UPPER, SHOULDER)) and row.is_built_mod
    first, second = row.game_files
    # The new row is selected and shows every file.
    assert page._selected_row() is not None and page._selected_row().row_id == row.row_id
    listed = [page.game_files_list.item(index).text() for index in range(page.game_files_list.count())]
    assert listed == [first, second] and page.game_files_list.isVisibleTo(page)
    assert page.game_file_value.text() == f"{first} + 1 more"
    cell = next(page.table.item(index, 2) for index in range(page.table.rowCount())
                if page.table.item(index, 1).text() == "Combined armour")
    assert cell.text() == f"{first} + 1 more"
    assert cell.toolTip().splitlines() == [first, second]


def test_two_builds_of_one_game_file_are_refused_by_name_before_anything_is_written(combine):
    page, app = combine.page, combine.app
    other = _build(combine.builds, "Second skirt", {UPPER: (b"another upper body", "0009")})
    add_built_mod_folder(combine.drafts, other)
    page.refresh()
    _wait(app, lambda: len(page.rows()) == 3)
    _select(combine, "Skirt edit", "Second skirt")
    listing = sorted(path.name for path in combine.tmp.iterdir())
    page.combine_button.click()
    dialog = page.combine_flow.dialog
    _wait(app, lambda: dialog.stage != saved_work_combine.STAGE_CHECKING)
    assert dialog.stage == saved_work_combine.STAGE_REFUSED
    text = dialog.status_label.text()
    assert text.startswith("These builds cannot be combined")
    assert ('"Skirt edit" and "Second skirt"' in text or '"Second skirt" and "Skirt edit"' in text) and UPPER in text
    assert not dialog.combine_button.isVisibleTo(dialog) and dialog.cancel_button.text() == "Close"
    dialog.cancel_button.click()
    _wait(app, lambda: page.combine_flow.dialog is None)
    assert sorted(path.name for path in combine.tmp.iterdir()) == listing
    assert combine.messages[-1] == (text, True)


def test_an_output_inside_the_configured_game_folder_is_refused_on_the_loose_route(combine):
    page, app = combine.page, combine.app
    game_before = _fingerprint(combine.game)
    dialog = _open_review(combine)
    assert dialog.layout_value.text() == "Loose mod for DMM"  # the loose route, which needs no game
    inside = combine.game / "mods" / "Combined armour"
    dialog.title_edit.setText("Combined armour")
    dialog.folder_edit.setText(str(inside))
    dialog.combine_button.click()
    _wait(app, lambda: dialog.stage != saved_work_combine.STAGE_WRITING)
    assert dialog.stage == saved_work_combine.STAGE_REVIEW
    assert "separate from the game" in dialog.status_label.text()
    assert not (combine.game / "mods").exists()
    assert _fingerprint(combine.game) == game_before
    assert not any(row.display_name == "Combined armour" for row in list_saved_work(combine.drafts))
    # The refusal comes from the configured game folder, not from the builds.
    combine.archive.archive_package_root_edit.setText("")
    dialog.combine_button.click()
    _wait(app, lambda: page.combine_flow.dialog is None)
    assert (inside / UPPER).is_file()


def _leftovers(parent: Path) -> list[str]:
    return sorted(path.name for path in parent.iterdir()) if parent.exists() else []


def test_cancel_while_checking_stops_the_worker(combine, monkeypatch):
    import cdmw.services.mesh_build_combine_service as service

    real = service.prepare_mesh_build_combine
    seen: list[threading.Event] = []

    def slow(folders, *, labels=(), stop_event=None):
        seen.append(stop_event)
        assert stop_event.wait(10), "the cancel never reached the worker"
        return real(folders, labels=labels, stop_event=stop_event)

    monkeypatch.setattr(service, "prepare_mesh_build_combine", slow)
    page, app = combine.page, combine.app
    _select(combine, "Skirt edit", "Wing piece")
    page.combine_button.click()
    dialog = page.combine_flow.dialog
    _wait(app, lambda: bool(seen))
    assert dialog.stage == saved_work_combine.STAGE_CHECKING
    dialog.cancel_button.click()
    assert page.combine_flow.dialog is None and seen[0].is_set()
    assert combine.messages[-1][0].endswith("was cancelled. Nothing was written.")
    assert page.combine_button.isEnabled()


def test_cancel_at_review_writes_nothing(combine):
    page, app = combine.page, combine.app
    dialog = _open_review(combine)
    output = Path(dialog.folder_edit.text())
    dialog.reject()  # Escape
    _wait(app, lambda: page.combine_flow.dialog is None)
    assert not output.exists()
    assert len(list_saved_work(combine.drafts)) == 2


@pytest.mark.parametrize("chosen_empty", [False, True])
def test_cancel_while_writing_leaves_no_folder(combine, monkeypatch, chosen_empty):
    import cdmw.services.mesh_mod_publish as publish

    real = publish.publish_mesh_mod_output
    waiting = threading.Event()

    def slow(staging, root, *, stop_event=None, **options):
        waiting.set()
        assert stop_event.wait(10), "the cancel never reached the writer"
        return real(staging, root, stop_event=stop_event, **options)

    monkeypatch.setattr(publish, "publish_mesh_mod_output", slow)
    page, app = combine.page, combine.app
    dialog = _open_review(combine)
    output = combine.tmp / "out" / "Combined armour"
    if chosen_empty:
        output.mkdir(parents=True)
    dialog.title_edit.setText("Combined armour")
    dialog.folder_edit.setText(str(output))
    dialog.combine_button.click()
    _wait(app, waiting.is_set)
    dialog.cancel_button.click()
    assert dialog.stage == saved_work_combine.STAGE_CANCELLING
    _wait(app, lambda: page.combine_flow.dialog is None)
    assert combine.messages[-1][0].endswith("was cancelled. Nothing was written.")
    if chosen_empty:
        assert output.is_dir() and not any(output.iterdir())
    else:
        assert not output.exists()
    assert _leftovers(output.parent) == (["Combined armour"] if chosen_empty else [])
    assert len(list_saved_work(combine.drafts)) == 2


def test_a_cancel_after_the_mod_was_written_takes_it_back_out(combine, monkeypatch):
    import cdmw.services.mesh_build_combine_service as service

    real = service.export_combined_mesh_builds
    written = threading.Event()

    def then_wait(prepared, destination, *, stop_event=None, **options):
        result = real(prepared, destination, stop_event=stop_event, **options)
        written.set()
        assert stop_event.wait(10)
        return result

    monkeypatch.setattr(service, "export_combined_mesh_builds", then_wait)
    page, app = combine.page, combine.app
    dialog = _open_review(combine)
    output = combine.tmp / "out" / "Combined armour"
    dialog.title_edit.setText("Combined armour")
    dialog.folder_edit.setText(str(output))
    dialog.zip_check.setChecked(True)
    dialog.combine_button.click()
    _wait(app, written.is_set)
    assert (output / UPPER).is_file() and output.with_name("Combined armour.zip").is_file()
    dialog.cancel_button.click()
    _wait(app, lambda: page.combine_flow.dialog is None)
    assert _leftovers(output.parent) == []
    assert len(list_saved_work(combine.drafts)) == 2


def _delegate_text(page, row_name: str, width: int) -> str:
    table = page.table
    row = next(index for index in range(table.rowCount()) if table.item(index, 1).text() == row_name)
    index = table.model().index(row, 2)
    option = QStyleOptionViewItem()
    option.initFrom(table)
    option.rect = QRect(0, 0, width, 20)
    table.itemDelegateForColumn(2).initStyleOption(option, index)
    return option.text


def test_the_game_file_column_keeps_both_file_names_whole_when_narrow(combine):
    page = combine.page
    char = page.table.fontMetrics().averageCharWidth()
    skirt = _delegate_text(page, "Skirt edit", char * 40)
    wing = _delegate_text(page, "Wing piece", char * 40)
    assert skirt.endswith("cd_phw_00_ub_00_0151.pac") and wing.endswith("cd_phw_00_sho_under_00_0151.pac")
    assert skirt.startswith(ELLIPSIS) and skirt != wing
    assert page.table.fontMetrics().horizontalAdvance(skirt) <= char * 40
    # Wide enough: the whole path.
    assert _delegate_text(page, "Skirt edit", char * 200) == UPPER
    # Too narrow for any folder: the file name alone, never cut.
    assert _delegate_text(page, "Skirt edit", char * 4) == "cd_phw_00_ub_00_0151.pac"


def test_a_row_with_several_files_reads_first_plus_more_in_the_column(combine):
    from cdmw.services.mesh_saved_work_service import register_combined_mod

    page, app = combine.page, combine.app
    folder = combine.tmp / "mods" / "Set build"
    folder.mkdir()
    register_combined_mod(combine.drafts, mod_root=folder, target_paths=(UPPER, SHOULDER), display_name="Set build")
    page.refresh()
    _wait(app, lambda: len(page.rows()) == 3)
    char = page.table.fontMetrics().averageCharWidth()
    text = _delegate_text(page, "Set build", char * 48)
    assert text.endswith("cd_phw_00_ub_00_0151.pac + 1 more") and text.startswith(ELLIPSIS)
