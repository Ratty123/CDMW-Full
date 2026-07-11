"""Attachment-named compatibility wrapper for request-ID utility tasks."""

from __future__ import annotations

from cdmw.ui.shell.request_task_controller import RequestTaskController


class AttachmentTaskController(RequestTaskController):
    def __init__(self, owner: object, guard: object) -> None:
        super().__init__(owner, guard, worker_label="attachment_io")


def attachment_task_controller_for_guard(
    owner: object,
    guard: object,
    *,
    attribute: str = "_attachment_task_controller",
) -> AttachmentTaskController:
    existing = getattr(guard, attribute, None)
    if isinstance(existing, AttachmentTaskController):
        return existing
    controller = AttachmentTaskController(owner, guard)
    setattr(guard, attribute, controller)
    connect = getattr(getattr(guard, "finished", None), "connect", None)
    if callable(connect):
        connect(lambda _result=0: controller.request_shutdown())
    return controller


__all__ = ["AttachmentTaskController", "attachment_task_controller_for_guard"]
