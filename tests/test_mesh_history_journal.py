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
