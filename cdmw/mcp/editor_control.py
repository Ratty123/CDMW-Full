"""The Mesh Editor's own controls used by name from a tool (``editor_control``).

The helper answers each message with the control's state and, when it refused, the
reason its panel would show; a tool sends one and waits for that answer.
"""

from __future__ import annotations

import time

from cdmw.mcp.errors import FAILED, UNAVAILABLE, ToolError

ANSWER_S = 5.0


def older_helper(control: str) -> str:
    return (f"This Mesh Editor helper does not take its {control} control from CDMW; it is older than this app "
            "(host_editor_controls_v1).")


def has_control(call, control: str) -> bool:
    from cdmw.mcp.mesh_tools import shown_document
    from cdmw.ui.mesh_editor.editor_controls import editor_controls

    return bool(call.context.ui_call(lambda: control in editor_controls(shown_document(call.context))))


def editor_control(call, control: str, arguments: dict[str, object], *,
                   answer_s: float = ANSWER_S) -> dict[str, object]:
    """Send one control and return its answer: ``ok``, ``message`` and ``state``. A control
    that edits (a sculpt stroke) waits longer, so a slow answer is not taken for none and
    the edit tried twice."""

    from cdmw.mcp.mesh_tools import ready_document, shown_document
    from cdmw.ui.mesh_editor.editor_controls import editor_controls, take_editor_control_answer

    context = call.context

    def send() -> int:
        tab = ready_document(context)
        if control not in editor_controls(tab):
            raise ToolError(UNAVAILABLE, older_helper(control))
        token = tab.send_editor_control(control, arguments)
        if not token:
            raise ToolError(FAILED, "The Mesh Editor did not take the message.")
        return token

    token = context.ui_call(send)
    deadline = time.monotonic() + answer_s
    while time.monotonic() < deadline:
        call.check_cancelled()
        answer = context.ui_call(lambda: take_editor_control_answer(shown_document(context), token))
        if answer is not None:
            return answer
        time.sleep(0.03)
    raise ToolError(FAILED, "The Mesh Editor did not answer in time. It may still have done it: check mesh_state's "
                            "history and view_capture before trying again.")


def control_outcome(answer: dict[str, object], key: str) -> dict[str, object]:
    """A tool's result from one answer: ``done``, the state under ``key`` and the refusal."""

    outcome: dict[str, object] = {"done": bool(answer.get("ok")), key: answer.get("state")}
    if not answer.get("ok"):
        outcome["message"] = str(answer.get("message") or "The Mesh Editor did not take it.")
    return outcome


__all__ = ["ANSWER_S", "control_outcome", "editor_control", "has_control", "older_helper"]
