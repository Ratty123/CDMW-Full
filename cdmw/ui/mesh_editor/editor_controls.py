"""The Mesh Editor's own controls used by name (``editor_control``).

The helper lists the controls it takes in its hello (``editor_controls``) and answers
each message with an ``editor_control`` event carrying the message's token: whether the
control took the action, its reason when it did not, and the control's state after. The
answers are kept on the document by token, a few at a time, for the call that waits.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping

#: Answers kept per document; older ones are dropped first.
ANSWERS_KEPT = 16
_TOKENS = itertools.count(1)


def editor_controls(tab) -> frozenset[str]:
    """The controls this document's helper takes, empty for an older helper."""

    return frozenset(getattr(tab, "standalone_rust_editor_controls", ()) or ())


def send_editor_control(tab, control: str, arguments: Mapping[str, object]) -> int:
    """Send one ``editor_control``; the token its answer carries, or 0 when not sent."""

    if not getattr(tab, "standalone_rust_ready", False) or control not in editor_controls(tab):
        return 0
    token = next(_TOKENS)
    message = tab._rust_host_message("editor_control", request_id=0,
                                     extra={"control": control, "token": token, "arguments": dict(arguments)})
    return token if tab._send_rust_message(message) else 0


def keep_editor_control_answer(tab, payload: Mapping[str, object]) -> None:
    try:
        token = int(payload.get("token") or 0)
    except (TypeError, ValueError, OverflowError):
        return
    if token <= 0:
        return
    answers = getattr(tab, "standalone_rust_editor_control_answers", None)
    if not isinstance(answers, dict):
        answers = {}
        tab.standalone_rust_editor_control_answers = answers
    state = payload.get("state")
    answers[token] = {"control": str(payload.get("control") or ""), "ok": bool(payload.get("ok")),
                      "message": str(payload.get("message") or ""),
                      "state": dict(state) if isinstance(state, Mapping) else state}
    while len(answers) > ANSWERS_KEPT:
        answers.pop(next(iter(answers)))


def take_editor_control_answer(tab, token: int) -> dict[str, object] | None:
    answers = getattr(tab, "standalone_rust_editor_control_answers", None)
    return answers.pop(token, None) if isinstance(answers, dict) else None


__all__ = ["ANSWERS_KEPT", "editor_controls", "keep_editor_control_answer", "send_editor_control",
           "take_editor_control_answer"]
