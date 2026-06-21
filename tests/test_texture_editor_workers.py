from __future__ import annotations

from cdmw.ui.texture_workflow import editor_workers
from cdmw.ui.texture_workflow.editor_workers import TextureEditorTaskWorker, TextureEditorUIConstraintWorker


def test_texture_editor_task_worker_emits_completed_and_finished() -> None:
    worker = TextureEditorTaskWorker(lambda: "done")
    completed: list[object] = []
    errors: list[str] = []
    finished: list[bool] = []
    worker.completed.connect(completed.append)
    worker.error.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert completed == ["done"]
    assert errors == []
    assert finished == [True]


def test_texture_editor_task_worker_suppresses_completed_after_stop() -> None:
    worker = TextureEditorTaskWorker(lambda: "done")
    completed: list[object] = []
    finished: list[bool] = []
    worker.completed.connect(completed.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.stop()

    worker.run()

    assert completed == []
    assert finished == [True]


def test_texture_editor_task_worker_emits_error_for_task_failure() -> None:
    def _fail() -> object:
        raise RuntimeError("boom")

    worker = TextureEditorTaskWorker(_fail)
    errors: list[str] = []
    finished: list[bool] = []
    worker.error.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert errors == ["boom"]
    assert finished == [True]


def test_texture_editor_ui_constraint_worker_emits_summary_warning(monkeypatch) -> None:
    calls: list[tuple[list[object], str, object]] = []

    def _summarize(entries: list[object], target_path: str, *, stop_event: object) -> dict[str, str]:
        calls.append((entries, target_path, stop_event))
        return {"warning_text": "watch UI bounds"}

    monkeypatch.setattr(editor_workers, "summarize_ui_reference_constraints", _summarize)
    worker = TextureEditorUIConstraintWorker([object()], "ui/icon.dds")
    completed: list[tuple[str, str]] = []
    finished: list[bool] = []
    worker.completed.connect(lambda target, warning: completed.append((target, warning)))
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert completed == [("ui/icon.dds", "watch UI bounds")]
    assert calls and calls[0][1] == "ui/icon.dds"
    assert calls[0][2] is worker.stop_event
    assert finished == [True]
