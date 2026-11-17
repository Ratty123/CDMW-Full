"""Run an interface action for an AI tool as a click would, without holding the window.

A handler a click runs may open a file chooser or a message box, which would
hold the UI thread until someone clicks. :func:`run_action` posts the action
to the UI thread and, while it runs, answers the static choosers and message
boxes (``QFileDialog.get*``, ``QMessageBox.question/warning/information/
critical``, ``QInputDialog.getText/getItem/getInt/getDouble``) from the call's
``answers`` instead of showing them:

* a chooser with no answer is cancelled, as Esc does;
* a question with no answer is declined (No, or Cancel);
* a message is acknowledged.

Each is recorded in ``asked`` with the answer given, so the AI reads what the
user would have read. A path to write (a save chooser's file, a chosen
folder) passes the one output path rule first: nothing is written into the
game, and no output replaces a file.

A dialog of CDMW's own (``dialog.exec()``) is not answered. When the action
has not returned in time the answering ends and the result names the dialog
in ``waiting_on``; it stays open and ``app.ui`` / ``app.ui_act`` drive it,
because calls still run inside its event loop.

No tool can change the AI connection settings or the game folder
(``approvals.is_protected_setting``): if an action changed one, it is put
back and the call is refused.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping

from cdmw.mcp.errors import FAILED, REFUSED, UNAVAILABLE, ToolError

ACTION_WAIT_S = 8.0
_LOGGER = logging.getLogger(__name__)

#: What ``answers`` may hold, for the tools' schemas.
ANSWERS_SCHEMA: dict[str, object] = {
    "type": "object", "additionalProperties": False,
    "description": "Answers for what the action would show: a chooser with no answer is cancelled, a question "
                   "with no answer is declined. 'asked' in the result lists what was asked.",
    "properties": {
        "file": {"type": "string", "maxLength": 1024, "description": "An existing file, for an Open chooser."},
        "files": {"type": "array", "maxItems": 256, "items": {"type": "string", "maxLength": 1024},
                  "description": "Existing files, for a chooser that takes several."},
        "save_file": {"type": "string", "maxLength": 1024,
                      "description": "The file to write, for a Save chooser. Not in the game; never an "
                                     "existing file."},
        "folder": {"type": "string", "maxLength": 1024,
                   "description": "An existing folder, for a folder chooser. Not in the game."},
        "confirm": {"type": "string", "enum": ["yes", "no", "ok", "cancel", "save", "discard"],
                    "description": "The button for a question."},
        "text": {"type": "string", "maxLength": 4096, "description": "The text for a text prompt."},
        "item": {"type": "string", "maxLength": 512, "description": "The choice for a pick-one prompt."},
        "number": {"type": "number", "description": "The number for a number prompt."},
    },
}


class DialogAnswers:
    """One action's answers and the record of what was asked. UI thread only."""

    def __init__(self, answers: Mapping[str, object] | None, game_folder: str = "") -> None:
        self.answers = dict(answers or {})
        self.game_folder = game_folder
        self.asked: list[dict[str, object]] = []
        self.active = True

    def note(self, kind: str, title: object, text: object, answer: object, **more: object) -> None:
        row = {"kind": kind, "title": str(title or ""), "answer": answer}
        if text:
            row["text"] = str(text)[:2000]
        row.update({key: value for key, value in more.items() if value})
        self.asked.append(row)

    def output_path(self, text: str, *, folder: bool) -> tuple[str, str]:
        """(the path, "") when it may be written to; ("", why not) otherwise."""

        from cdmw.domain.output_paths import OutputPathRefused, check_output_path

        try:
            check_output_path(text, game_folder=self.game_folder, allow_existing=folder)
        except OutputPathRefused as refused:
            return "", str(refused)
        return text, ""


_ACTIVE: list[DialogAnswers] = []
_ORIGINALS: dict[tuple[object, str], object] = {}


def _current() -> DialogAnswers | None:
    return next((answers for answers in reversed(_ACTIVE) if answers.active), None)


def _argument(args: tuple, kwargs: dict, index: int, *names: str, default: object = "") -> object:
    for name in names:
        if name in kwargs:
            return kwargs[name]
    return args[index] if len(args) > index else default


def _open_file(original):
    def answered(*args, **kwargs):
        current = _current()
        if current is None:
            return original(*args, **kwargs)
        title = _argument(args, kwargs, 1, "caption")
        filters = str(_argument(args, kwargs, 3, "filter") or "")
        import os

        path = str(current.answers.get("file") or "")
        if path and not os.path.isfile(path):
            current.note("open_file", title, "", "cancelled", filter=filters, refused=f"There is no file {path}.")
            return "", ""
        current.note("open_file", title, "", path or "cancelled", filter=filters)
        return (path, filters.split(";;")[0]) if path else ("", "")
    return answered


def _open_files(original):
    def answered(*args, **kwargs):
        current = _current()
        if current is None:
            return original(*args, **kwargs)
        import os

        title = _argument(args, kwargs, 1, "caption")
        filters = str(_argument(args, kwargs, 3, "filter") or "")
        paths = [str(path) for path in current.answers.get("files") or ()]
        if not paths and current.answers.get("file"):
            paths = [str(current.answers["file"])]
        missing = [path for path in paths if not os.path.isfile(path)]
        if missing:
            current.note("open_files", title, "", "cancelled", filter=filters,
                         refused=f"There is no file {missing[0]}.")
            return [], ""
        current.note("open_files", title, "", paths or "cancelled", filter=filters)
        return (paths, filters.split(";;")[0]) if paths else ([], "")
    return answered


def _save_file(original):
    def answered(*args, **kwargs):
        current = _current()
        if current is None:
            return original(*args, **kwargs)
        title = _argument(args, kwargs, 1, "caption")
        suggested = str(_argument(args, kwargs, 2, "dir") or "")
        filters = str(_argument(args, kwargs, 3, "filter") or "")
        wanted = str(current.answers.get("save_file") or "")
        path, refused = current.output_path(wanted, folder=False) if wanted else ("", "")
        current.note("save_file", title, "", path or "cancelled", filter=filters, suggested=suggested,
                     refused=refused)
        return (path, filters.split(";;")[0]) if path else ("", "")
    return answered


def _folder(original):
    def answered(*args, **kwargs):
        current = _current()
        if current is None:
            return original(*args, **kwargs)
        import os

        title = _argument(args, kwargs, 1, "caption")
        wanted = str(current.answers.get("folder") or "")
        path, refused = "", ""
        if wanted and not os.path.isdir(wanted):
            refused = f"There is no folder {wanted}."
        elif wanted:
            path, refused = current.output_path(wanted, folder=True)
        current.note("folder", title, "", path or "cancelled", refused=refused)
        return path
    return answered


_CONFIRM = {"yes": "Yes", "no": "No", "ok": "Ok", "cancel": "Cancel", "save": "Save", "discard": "Discard"}
_DECLINE = ("No", "Cancel", "Close", "Abort")


#: Questions only the user answers, whatever runs meanwhile: the two flows that write
#: into the game folder ask them (remove what an older CDMW installed, restore a backup).
USER_ONLY_TITLES = frozenset({"Remove What an Older CDMW Installed", "Restore Backup"})


def _message(original, kind: str):
    def answered(*args, **kwargs):
        current = _current()
        title = _argument(args, kwargs, 1, "title")
        if current is None or str(title or "") in USER_ONLY_TITLES:
            return original(*args, **kwargs)
        from PySide6.QtWidgets import QMessageBox

        buttons_type = QMessageBox.StandardButton
        text = _argument(args, kwargs, 2, "text")
        default = buttons_type.Yes | buttons_type.No if kind == "question" else buttons_type.Ok
        buttons = _argument(args, kwargs, 3, "buttons", default=default)
        offered = [name for name in ("Yes", "No", "Ok", "Cancel", "Save", "Discard", "Close", "Abort", "Retry",
                                     "Ignore", "Apply", "Open", "YesToAll", "NoToAll")
                   if buttons & getattr(buttons_type, name)]
        wanted = _CONFIRM.get(str(current.answers.get("confirm") or ""))
        if wanted in offered:
            chosen = wanted
        elif offered == ["Ok"] or not offered:
            chosen = "Ok"  # a message: acknowledged
        else:
            chosen = next((name for name in _DECLINE if name in offered), None)
            if chosen is None:
                # Every button goes on: none is taken for the user. Ok stands for "seen".
                chosen = "Ok" if "Ok" in offered and len(offered) == 1 else offered[-1]
        current.note(kind, title, text, chosen.casefold(), buttons=[name.casefold() for name in offered])
        return getattr(buttons_type, chosen)
    return answered


def _input(original, kind: str):
    def answered(*args, **kwargs):
        current = _current()
        if current is None:
            return original(*args, **kwargs)
        title = _argument(args, kwargs, 1, "title")
        label = _argument(args, kwargs, 2, "label")
        if kind == "text":
            given = current.answers.get("text")
            current.note("text", title, label, given if given is not None else "cancelled")
            return (str(given), True) if given is not None else ("", False)
        if kind == "item":
            items = [str(item) for item in _argument(args, kwargs, 3, "items", default=()) or ()]
            given = str(current.answers.get("item") or "")
            ok = given in items
            current.note("item", title, label, given if ok else "cancelled", items=items[:100])
            return (given, True) if ok else ("", False)
        given = current.answers.get("number")
        current.note("number", title, label, given if given is not None else "cancelled")
        if given is None:
            return (0, False) if kind == "int" else (0.0, False)
        return (int(given), True) if kind == "int" else (float(given), True)
    return answered


def _patches() -> list[tuple[object, str, Callable]]:
    from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

    return [
        (QFileDialog, "getOpenFileName", _open_file),
        (QFileDialog, "getOpenFileNames", _open_files),
        (QFileDialog, "getSaveFileName", _save_file),
        (QFileDialog, "getExistingDirectory", _folder),
        (QMessageBox, "question", lambda original: _message(original, "question")),
        (QMessageBox, "warning", lambda original: _message(original, "warning")),
        (QMessageBox, "information", lambda original: _message(original, "information")),
        (QMessageBox, "critical", lambda original: _message(original, "critical")),
        (QInputDialog, "getText", lambda original: _input(original, "text")),
        (QInputDialog, "getItem", lambda original: _input(original, "item")),
        (QInputDialog, "getInt", lambda original: _input(original, "int")),
        (QInputDialog, "getDouble", lambda original: _input(original, "double")),
    ]


class answering:
    """While inside, the static dialogs are answered from ``answers`` (UI thread only)."""

    def __init__(self, answers: DialogAnswers) -> None:
        self.answers = answers

    def __enter__(self) -> DialogAnswers:
        if not _ACTIVE:
            for owner, name, wrap in _patches():
                original = getattr(owner, name)
                _ORIGINALS[(owner, name)] = original
                setattr(owner, name, staticmethod(wrap(original)))
        _ACTIVE.append(self.answers)
        return self.answers

    def __exit__(self, *_exc) -> None:
        self.answers.active = False
        if self.answers in _ACTIVE:
            _ACTIVE.remove(self.answers)
        if not _ACTIVE:
            for (owner, name), original in list(_ORIGINALS.items()):
                setattr(owner, name, staticmethod(original))
            _ORIGINALS.clear()


# ----- the settings no tool may change -------------------------------------------------
def _protected_values(settings) -> dict[str, object]:
    from cdmw.mcp.approvals import is_protected_setting

    if settings is None:
        return {}
    try:
        keys = [str(key) for key in settings.allKeys()]
    except (AttributeError, RuntimeError):
        return {}
    return {key: settings.value(key) for key in keys if is_protected_setting(key)}


def _restore_protected(settings, before: dict[str, object]) -> list[str]:
    """Put back any protected setting the action changed; the keys that were put back."""

    after = _protected_values(settings)
    changed = sorted(key for key in {*before, *after} if str(before.get(key)) != str(after.get(key)))
    for key in changed:
        if key in before:
            settings.setValue(key, before[key])
        else:
            settings.remove(key)
    return changed


# ----- running ---------------------------------------------------------------------------
def modal_dialog() -> dict[str, object] | None:
    """The dialog that holds the interface now, as ``app.ui`` names it (UI thread)."""

    from PySide6.QtWidgets import QApplication, QMessageBox

    from cdmw.mcp.ui_tree import widget_id

    widget = QApplication.activeModalWidget()
    if widget is None:
        return None
    row: dict[str, object] = {"widget": widget_id(widget), "title": widget.windowTitle(),
                              "class": type(widget).__name__}
    if isinstance(widget, QMessageBox):
        row["text"] = widget.text()
    return row


def run_action(context, function: Callable[[], object], answers: Mapping[str, object] | None = None, *,
               wait_s: float | None = None) -> dict[str, object]:
    """Run ``function`` on the UI thread as a click would. Returns ``{"result", "asked"}``, or
    ``{"waiting_on", "asked"}`` when a dialog of the app's own is open and waits."""

    from PySide6.QtCore import QCoreApplication, QThread, QTimer

    from cdmw.ui.commands.registry import CommandRefused

    record = DialogAnswers(answers, getattr(context, "game_folder", lambda: "")())
    settings = getattr(context, "settings", None)
    done = threading.Event()
    box: dict[str, object] = {}

    def go() -> None:
        before = _protected_values(settings)
        try:
            with answering(record):
                box["result"] = function()
        except CommandRefused as refused:
            box["error"] = ToolError(UNAVAILABLE, str(refused))
        except ToolError as error:
            box["error"] = error
        except Exception as exc:  # the handler's own failure; the log has the trace
            _LOGGER.exception("An AI tool's interface action failed")
            box["error"] = ToolError(FAILED, str(exc) or type(exc).__name__)
        finally:
            try:
                changed = _restore_protected(settings, before)
            except Exception:
                changed = []
            if changed:
                box["error"] = ToolError(REFUSED, "Only you can change this setting in CDMW: AI connections, "
                                                  "their approvals, Full access and the game folder are never "
                                                  "changed by a tool. It was put back.", {"settings": changed})
            done.set()

    app = QCoreApplication.instance()
    if app is None or QThread.currentThread() is app.thread():
        go()  # already on the UI thread (a test calling a handler directly)
    else:
        context.ui_call(lambda: QTimer.singleShot(0, go))
        if not done.wait(max(0.1, ACTION_WAIT_S if wait_s is None else wait_s)):
            # Either a dialog of the app's own waits, or the handler is still working. The
            # UI thread answers this question only once it runs an event loop again.
            try:
                waiting = context.ui_call(modal_dialog)
            except ToolError:
                waiting = None
            if not done.is_set():
                if waiting is not None:
                    record.active = False  # the dialog is the user's (and app_ui_act's) from here
                    return {"waiting_on": waiting, "asked": list(record.asked),
                            "message": "The action opened a dialog that waits for an answer. Read it with "
                                       "app_ui and answer it with app_ui_act."}
                return {"running": True, "asked": list(record.asked),
                        "message": "The action is still running in CDMW; app_state shows what it is doing."}
    if "error" in box:
        error = box["error"]
        if record.asked and isinstance(error, ToolError):
            error.data.setdefault("asked", list(record.asked))
        raise error
    return {"result": box.get("result"), "asked": list(record.asked)}


__all__ = ["ACTION_WAIT_S", "ANSWERS_SCHEMA", "DialogAnswers", "answering", "modal_dialog", "run_action"]
