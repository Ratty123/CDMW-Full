"""P14: undo history that survives a restart, as a journal of a draft's saved states."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.services import mesh_history_journal as journal
from cdmw.services.mesh_service import MeshHistoryJournalError, MeshService
from tests.test_mesh_geometry_layers import _persistent_layer_mesh


# ------------------------------------------------------------- the journal file


def _generation(root: Path, name: str, payload: str = "{}", extra: int = 0) -> str:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "generation.json").write_text(payload, encoding="utf-8")
    if extra:
        (folder / "blob.bin").write_bytes(b"x" * extra)
    return name


def _record(root: Path, depth: int, *, extra: int = 0, kind: str = journal.KIND_DRAFT) -> journal.JournalRecord:
    name = _generation(root, f"generation-{1000 + depth}-{uuid4().hex[:8]}", payload=f'{{"d":{depth}}}', extra=extra)
    return journal.new_record(root, name, depth=depth, kind=kind, labels=(f"step {depth}",), part_ids=(depth,))


def _put(root: Path, record: journal.JournalRecord, *, future_valid: bool = False, steps: int = 64,
         size: int = 1 << 30, keep=()) -> journal.Journal:
    return journal.record_state(root, record, future_valid=future_valid, max_steps=steps, max_bytes=size, keep=keep)


def test_records_are_appended_as_lines_and_read_back_by_depth(tmp_path) -> None:
    first, second = _record(tmp_path, 0), _record(tmp_path, 1)
    _put(tmp_path, first)
    _put(tmp_path, second)
    lines = journal.journal_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["generation"] == second.generation
    read = journal.read_journal(tmp_path)
    assert [record.depth for record in read.records] == [0, 1]
    assert read.records[1].labels == ("step 1",) and read.records[1].part_ids == (1,)
    assert read.before(1) == first and read.after(0) == second and read.after(1) is None


def test_an_edit_drops_the_future_and_an_undo_keeps_it(tmp_path) -> None:
    records = [_record(tmp_path, depth) for depth in range(3)]
    for record in records:
        _put(tmp_path, record)
    # An undo back to depth 1 saved again: the step at 1 is replaced, 2 stays a redo.
    again = _record(tmp_path, 1)
    _put(tmp_path, again, future_valid=True)
    assert [r.generation for r in journal.read_journal(tmp_path).records] == [
        records[0].generation, again.generation, records[2].generation]
    assert not (tmp_path / records[1].generation).exists()
    # An edit at depth 1: the step at 2 can no longer be reached and its folder goes.
    edited = _record(tmp_path, 1)
    _put(tmp_path, edited, future_valid=False)
    assert [r.generation for r in journal.read_journal(tmp_path).records] == [records[0].generation, edited.generation]
    assert not (tmp_path / records[2].generation).exists()


def test_the_journal_is_pruned_to_the_step_and_size_limits(tmp_path) -> None:
    kept = _record(tmp_path, 0, extra=10)
    _put(tmp_path, kept)
    for depth in range(1, 5):
        _put(tmp_path, _record(tmp_path, depth, extra=10), steps=3, keep=(kept.generation,))
    read = journal.read_journal(tmp_path)
    assert [record.depth for record in read.records] == [2, 3, 4]
    assert (tmp_path / kept.generation).is_dir()  # the descriptor's fallback is kept on disk
    big = _record(tmp_path, 5, extra=1000)
    read = _put(tmp_path, big, size=1010)
    assert [record.depth for record in read.records] == [5]  # a large state alone keeps its step
    assert read.size_bytes == big.size_bytes


def test_a_truncated_last_line_is_ignored(tmp_path) -> None:
    first, second = _record(tmp_path, 0), _record(tmp_path, 1)
    _put(tmp_path, first)
    path = journal.journal_path(tmp_path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(second.line()[:40])  # a crash mid-write
    read = journal.read_journal(tmp_path)
    assert [record.generation for record in read.records] == [first.generation] and read.ignored_lines == 1
    third = _record(tmp_path, 1)
    _put(tmp_path, third)  # the next write rewrites the file without the broken line
    assert journal.read_journal(tmp_path).ignored_lines == 0


def test_a_changed_generation_fails_its_digest(tmp_path) -> None:
    record = _record(tmp_path, 0)
    _put(tmp_path, record)
    assert journal.verify_record(tmp_path, record) == ""
    (tmp_path / record.generation / "generation.json").write_text('{"d":"changed"}', encoding="utf-8")
    assert "does not match" in journal.verify_record(tmp_path, record)
    (tmp_path / record.generation / "generation.json").unlink()
    assert journal.verify_record(tmp_path, record)


def test_a_clean_mark_survives_a_rewrite(tmp_path) -> None:
    first = _record(tmp_path, 0)
    _put(tmp_path, first)
    journal.mark_clean(tmp_path, first.generation)
    again = _record(tmp_path, 0)
    _put(tmp_path, again, future_valid=True)  # the same state saved again by an undo: still clean
    assert journal.read_journal(tmp_path).clean_generation == again.generation
    _put(tmp_path, _record(tmp_path, 0), future_valid=False)  # an edit at that depth: no longer clean
    assert journal.read_journal(tmp_path).clean_generation == ""
    second = _record(tmp_path, 1)
    _put(tmp_path, second)
    journal.mark_clean(tmp_path, second.generation)
    _put(tmp_path, _record(tmp_path, 2))
    assert journal.read_journal(tmp_path).clean_generation == second.generation


# ------------------------------------------------------------- a draft's session


def _x(service: MeshService, session_id: str) -> float:
    return float(service.working_mesh(session_id, clone=True).submeshes[0].vertices[0][0])


def _move(service: MeshService, session_id: str, dx: float) -> None:
    service.apply_command(session_id, MeshEditCommand(
        "transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}),
        params={"translate": (dx, 0.0, 0.0)}))
    service.retry_mesh_layer_autosave(session_id)


def _open(root: Path) -> tuple[MeshService, str]:
    mesh, _project, _manifest = _persistent_layer_mesh(root)
    service = MeshService()
    view = service.open_edit_session(mesh, session_id=f"journal-{uuid4().hex}", mode="edit")
    return service, view.session_id


def test_undo_history_survives_closing_the_draft(tmp_path) -> None:
    service, session_id = _open(tmp_path)
    for _ in range(3):
        _move(service, session_id, 0.25)
    project_root = tmp_path / "mesh_layers"
    records = journal.read_journal(project_root).records
    assert [record.depth for record in records] == [1, 2, 3]
    assert records[0].labels and records[0].part_ids == (0,)
    service.close_edit_session(session_id)

    service, session_id = _open(tmp_path)
    view = service.session_view(session_id)
    assert view.undo_count == 0 and view.journal_undo_available and not view.journal_redo_available
    assert _x(service, session_id) == pytest.approx(0.75)
    result = service.step_history_journal(session_id, -1)
    assert result.ok and _x(service, session_id) == pytest.approx(0.5)
    service.step_history_journal(session_id, -1)
    assert _x(service, session_id) == pytest.approx(0.25)
    assert not service.session_view(session_id).journal_undo_available  # the first saved step
    service.step_history_journal(session_id, 1)
    assert _x(service, session_id) == pytest.approx(0.5)
    service.close_edit_session(session_id)

    # The draft reopens where the history was left, with its future still there.
    service, session_id = _open(tmp_path)
    assert _x(service, session_id) == pytest.approx(0.5)
    view = service.session_view(session_id)
    assert view.journal_undo_available and view.journal_redo_available
    # An edit here ends that future, as a redo stack is cleared.
    _move(service, session_id, 1.0)
    assert [record.depth for record in journal.read_journal(project_root).records] == [1, 2, 3]
    assert not service.session_view(session_id).journal_redo_available
    service.close_edit_session(session_id)
    service, session_id = _open(tmp_path)
    assert _x(service, session_id) == pytest.approx(1.5)
    service.close_edit_session(session_id)


def test_in_memory_undo_comes_first_and_moves_the_journal_with_it(tmp_path) -> None:
    service, session_id = _open(tmp_path)
    _move(service, session_id, 0.25)
    _move(service, session_id, 0.25)
    service.undo(session_id)
    service.retry_mesh_layer_autosave(session_id)
    project_root = tmp_path / "mesh_layers"
    # The undo saved depth 1 again and kept depth 2 as the journal's future.
    assert [record.depth for record in journal.read_journal(project_root).records] == [1, 2]
    view = service.session_view(session_id)
    assert view.undo_count == 1 and not view.journal_undo_available
    service.close_edit_session(session_id)
    service, session_id = _open(tmp_path)
    assert _x(service, session_id) == pytest.approx(0.25)
    assert service.session_view(session_id).journal_redo_available
    service.step_history_journal(session_id, 1)
    assert _x(service, session_id) == pytest.approx(0.5)
    service.close_edit_session(session_id)


def test_a_step_that_fails_its_digest_stops_there_and_changes_nothing(tmp_path) -> None:
    service, session_id = _open(tmp_path)
    _move(service, session_id, 0.25)
    _move(service, session_id, 0.25)
    service.close_edit_session(session_id)
    project_root = tmp_path / "mesh_layers"
    first = journal.read_journal(project_root).records[0]
    manifest = project_root / first.generation / "generation.json"
    manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")

    service, session_id = _open(tmp_path)
    descriptor_before = (project_root / "mesh_layer_project.json").read_text(encoding="utf-8")
    with pytest.raises(MeshHistoryJournalError, match="last good step"):
        service.step_history_journal(session_id, -1)
    assert _x(service, session_id) == pytest.approx(0.5)
    assert (project_root / "mesh_layer_project.json").read_text(encoding="utf-8") == descriptor_before
    service.close_edit_session(session_id)


def test_the_journal_keeps_no_more_than_the_history_limit(tmp_path) -> None:
    mesh, _project, _manifest = _persistent_layer_mesh(tmp_path)
    service = MeshService(max_history=2)
    session_id = service.open_edit_session(mesh, session_id=f"journal-{uuid4().hex}", mode="edit").session_id
    for _ in range(4):
        _move(service, session_id, 0.25)
    project_root = tmp_path / "mesh_layers"
    records = journal.read_journal(project_root).records
    assert [record.depth for record in records] == [3, 4]
    descriptor = json.loads((project_root / "mesh_layer_project.json").read_text(encoding="utf-8"))
    on_disk = sorted(path.name for path in project_root.iterdir() if path.name.startswith("generation-"))
    assert on_disk == sorted({record.generation for record in records} | {descriptor["previous_generation"]})
    service.close_edit_session(session_id)


def test_the_recovery_point_survives_pruning_and_replaces_its_predecessor(tmp_path) -> None:
    kept = _record(tmp_path, 0)
    _put(tmp_path, kept)
    first = _generation(tmp_path, "generation-2000-aaaaaaaa", payload='{"r":1}')
    journal.write_editor_recovery(tmp_path, first, base_generation=kept.generation)
    stray = _generation(tmp_path, "generation-2001-bbbbbbbb")
    journal.prune_unjournaled_generations(tmp_path, keep=(kept.generation,))
    assert (tmp_path / first).is_dir() and not (tmp_path / stray).exists()
    second = _generation(tmp_path, "generation-2002-cccccccc", payload='{"r":2}')
    journal.write_editor_recovery(tmp_path, second, base_generation=kept.generation)
    assert not (tmp_path / first).exists()
    recovery = journal.read_editor_recovery(tmp_path)
    assert recovery["generation"] == second and recovery["base_generation"] == kept.generation
    journal.clear_editor_recovery(tmp_path)
    assert journal.read_editor_recovery(tmp_path) is None and not (tmp_path / second).exists()
    assert (tmp_path / kept.generation).is_dir()


def test_finished_or_built_states_are_clean_and_closing_a_draft_loses_nothing(tmp_path) -> None:
    from tests.test_mesh_geometry_layers import _layer_mesh

    service, session_id = _open(tmp_path)
    _move(service, session_id, 0.25)
    assert not service.session_view(session_id).history_clean
    service.mark_history_clean(session_id)  # as Build does
    assert service.session_view(session_id).history_clean
    assert journal.read_journal(tmp_path / "mesh_layers").clean_generation
    _move(service, session_id, 0.25)
    assert not service.session_view(session_id).history_clean
    assert not service.closing_loses_work(session_id)  # the draft holds the edit
    service.undo(session_id)
    service.retry_mesh_layer_autosave(session_id)
    assert service.session_view(session_id).history_clean  # back at the built state
    _move(service, session_id, 0.5)
    service.close_edit_session(session_id)
    service, session_id = _open(tmp_path)
    service.step_history_journal(session_id, -1)
    assert service.session_view(session_id).history_clean  # and after a restart
    service.close_edit_session(session_id)

    disk = MeshService()
    disk_id = disk.open_edit_session(_layer_mesh(), session_id=f"disk-{uuid4().hex}", mode="edit").session_id
    assert not disk.closing_loses_work(disk_id) and disk.session_view(disk_id).history_clean
    disk.apply_command(disk_id, MeshEditCommand(
        "transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}),
        params={"translate": (0.5, 0.0, 0.0)}))
    assert disk.closing_loses_work(disk_id) and not disk.session_view(disk_id).history_clean
    disk.close_edit_session(disk_id)


def test_settings_names_the_service_history_limits() -> None:
    import ast

    from cdmw.services.mesh_service import _DEFAULT_MESH_HISTORY_BYTES

    source = Path("cdmw/ui/settings_tab.py").read_text(encoding="utf-8")
    texts = [node.value for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Constant) and isinstance(node.value, str) and "undo history" in node.value]
    limits = " ".join(texts)
    assert f"{MeshService().max_history} steps" in limits
    assert f"{_DEFAULT_MESH_HISTORY_BYTES // (1024 * 1024)} MiB" in limits


def test_undo_and_redo_continue_into_the_saved_steps(tmp_path) -> None:
    service, session_id = _open(tmp_path)
    _move(service, session_id, 0.25)
    _move(service, session_id, 0.25)
    service.close_edit_session(session_id)
    service, session_id = _open(tmp_path)
    result = service.undo(session_id)  # the in-memory history is empty: the journal answers
    assert result.ok and result.action == "journal_undo" and _x(service, session_id) == pytest.approx(0.25)
    assert service.undo(session_id).status == "noop"  # nothing before the first saved step
    assert service.redo(session_id).action == "journal_redo" and _x(service, session_id) == pytest.approx(0.5)
    service.close_edit_session(session_id)


def test_a_journal_undo_never_drops_an_unsaved_redo_state(tmp_path) -> None:
    """Section 8.7 A2: the in-memory redo stack holds a state the journal does not have."""
    service, session_id = _open(tmp_path)
    _move(service, session_id, 0.25)
    _move(service, session_id, 0.25)
    service.close_edit_session(session_id)
    service, session_id = _open(tmp_path)  # at 0.5, two saved steps, empty memory
    session = service._session(session_id)
    service.apply_command(session_id, MeshEditCommand(
        "transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}),
        params={"translate": (1.0, 0.0, 0.0)}))
    if session.mesh_layer_autosave_timer is not None:
        session.mesh_layer_autosave_timer.cancel()  # the edit is not saved yet
    assert _x(service, session_id) == pytest.approx(1.5)
    service.undo(session_id)  # in memory: back to 0.5, the 1.5 state is a redo
    if session.mesh_layer_autosave_timer is not None:
        session.mesh_layer_autosave_timer.cancel()
    service.undo(session_id)  # the in-memory stack is empty: a journal step to 0.25
    assert _x(service, session_id) == pytest.approx(0.25)
    seen = []
    for _ in range(4):
        result = service.redo(session_id)
        if result.status == "noop":
            break
        seen.append(round(_x(service, session_id), 4))
    assert 1.5 in seen, f"the unsaved state was lost; Redo reached {seen}"
    service.close_edit_session(session_id, force_without_saving=True)


def test_a_journal_that_cannot_be_read_leaves_the_draft_readable(tmp_path) -> None:
    """Section 8.7 A12: a damaged journal must not stop the draft from opening, nor cost generations."""
    service, session_id = _open(tmp_path)
    _move(service, session_id, 0.25)
    _move(service, session_id, 0.25)
    service.close_edit_session(session_id)
    project_root = tmp_path / "mesh_layers"
    path = journal.journal_path(project_root)
    path.write_bytes(path.read_bytes() + b"\xff\xfe broken \xff\n")
    generations = sorted(p.name for p in project_root.iterdir() if p.name.startswith("generation-"))
    service, session_id = _open(tmp_path)  # must not raise
    assert _x(service, session_id) == pytest.approx(0.5)
    _move(service, session_id, 0.25)
    still = sorted(p.name for p in project_root.iterdir() if p.name.startswith("generation-"))
    assert set(generations) <= set(still), "an unreadable journal cost saved generations"
    service.close_edit_session(session_id)


def test_a_copied_draft_keeps_every_step_its_journal_names(tmp_path) -> None:
    """Section 8.7 A10: Duplicate and Build copy the draft; its history must still work in the copy."""
    from cdmw.services.mesh_saved_work_service import _copy_draft

    source = tmp_path / "draft"
    service, session_id = _open(source)
    for _ in range(3):
        _move(service, session_id, 0.25)
    service.close_edit_session(session_id)
    project = source / "mesh_layers"
    named = {record.generation for record in journal.read_journal(project).records}
    assert len(named) == 3
    target = tmp_path / "copy"
    _copy_draft(source, target, None)
    copied = {path.name for path in (target / "mesh_layers").iterdir() if path.name.startswith("generation-")}
    assert named <= copied, f"the copy lost {sorted(named - copied)}"


def test_the_clean_mark_decides_whether_closing_a_mesh_without_a_draft_loses_work() -> None:
    """Section 8.7 D4: ``history_clean`` had no reader; the close prompt counted undo steps."""

    from tests.test_mesh_geometry_layers import _layer_mesh

    disk = MeshService()
    disk_id = disk.open_edit_session(_layer_mesh(), session_id=f"disk-{uuid4().hex}", mode="edit").session_id
    try:
        _move(disk, disk_id, 0.5)
        assert disk.closing_loses_work(disk_id)
        disk.mark_history_clean(disk_id)  # Finish: the edit is kept as a pending edit
        assert not disk.closing_loses_work(disk_id) and disk.session_view(disk_id).history_clean
        _move(disk, disk_id, 0.25)
        assert disk.closing_loses_work(disk_id)
        disk.undo(disk_id)  # back at the finished state's geometry, but a step was undone
        assert disk.closing_loses_work(disk_id), "asking once too often is safe; losing work is not"
    finally:
        disk.close_edit_session(disk_id)


def test_the_close_prompt_asks_whenever_closing_loses_work(monkeypatch) -> None:
    """The close prompt asked only with undo steps; work the history does not hold was lost silently."""

    from types import SimpleNamespace

    import cdmw.ui.mesh_editor.tab  # noqa: F401 - loads the facade tab_shell reads
    from cdmw.ui.mesh_editor import tab_shell

    asked: list[str] = []
    shown: list[bool] = []
    box = SimpleNamespace(Yes=1, No=0, question=lambda *args: asked.append(args[1]) or 0)
    monkeypatch.setattr(tab_shell._tab, "QMessageBox", box)
    tab = SimpleNamespace(
        has_active_standalone_session=lambda: True,
        standalone_controller=SimpleNamespace(closing_loses_work=lambda: True),
        current_undo_count=0,
        show_empty_state=lambda: shown.append(True),
    )
    tab_shell.MeshEditorTabShellMixin._close_standalone_session_requested(tab)
    assert asked == ["Discard Unsaved Mesh Editor Changes?"] and not shown


def test_a_journal_read_incompletely_is_never_rewritten_or_pruned_in_that_session(tmp_path) -> None:
    """Section 8.8 R8: record_state rewrote the journal without the unreadable line,
    and the prune that followed deleted that line's generation."""

    service, session_id = _open(tmp_path)
    _move(service, session_id, 0.25)
    service.retry_mesh_layer_autosave(session_id)
    _move(service, session_id, 0.25)
    service.retry_mesh_layer_autosave(session_id)
    service.close_edit_session(session_id)
    root = tmp_path / "mesh_layers"
    path = journal.journal_path(root)
    first = journal.read_journal(root).records[0]
    # The first record's line becomes unreadable; its generation is still on disk.
    lines = path.read_bytes().splitlines()
    damaged = [b"\xff\xfe not text " + line[10:] if first.generation.encode() in line else line for line in lines]
    path.write_bytes(b"\n".join(damaged) + b"\n")
    before = path.read_bytes()
    assert (root / first.generation).is_dir()

    service, session_id = _open(tmp_path)
    _move(service, session_id, 0.5)
    service.retry_mesh_layer_autosave(session_id)
    service.close_edit_session(session_id)
    assert (root / first.generation).is_dir(), "the unreadable line's generation was deleted"
    assert path.read_bytes().startswith(before), "the journal was rewritten without its unreadable line"


def test_a_journal_that_failed_to_open_is_left_alone(tmp_path, monkeypatch) -> None:
    """Section 8.8 R8: an OSError at open left depth 0, and the next save deleted every step."""

    service, session_id = _open(tmp_path)
    for step in (0.25, 0.25, 0.25):
        _move(service, session_id, step)
        service.retry_mesh_layer_autosave(session_id)
    service.close_edit_session(session_id)
    root = tmp_path / "mesh_layers"
    generations = {record.generation for record in journal.read_journal(root).records}
    real_read = journal.read_journal
    calls = {"n": 0}

    def failing_once(project_root):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("the disk was busy")
        return real_read(project_root)

    monkeypatch.setattr(journal, "read_journal", failing_once)
    service, session_id = _open(tmp_path)
    monkeypatch.setattr(journal, "read_journal", real_read)
    _move(service, session_id, 0.5)
    service.retry_mesh_layer_autosave(session_id)
    service.close_edit_session(session_id)
    assert generations <= {path.name for path in root.iterdir()}, "saved steps were deleted"


def test_a_layer_change_without_a_new_revision_moves_the_clean_mark() -> None:
    """Section 8.8 R12: the clean mark compared the revision only; renaming, showing or
    activating a layer changes the mesh's state without it."""

    from tests.test_mesh_geometry_layers import _layer_mesh

    disk = MeshService()
    disk_id = disk.open_edit_session(_layer_mesh(), session_id=f"disk-{uuid4().hex}", mode="edit").session_id
    try:
        disk.apply_command(disk_id, MeshEditCommand(
            "select", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
            params={"operation": "replace"}))
        disk.copy_selection(disk_id, target="face")
        disk.paste_selection(disk_id)  # a layer of its own: "selection-copy-1"
        disk.mark_history_clean(disk_id)  # Finish or Build
        assert not disk.closing_loses_work(disk_id)
        revision = disk.session_view(disk_id).revision
        disk.rename_geometry_layer(disk_id, "selection-copy-1", "Renamed")
        assert disk.session_view(disk_id).revision == revision  # no new revision
        assert disk.closing_loses_work(disk_id), "the rename was lost on close unasked"
    finally:
        disk.close_edit_session(disk_id)
