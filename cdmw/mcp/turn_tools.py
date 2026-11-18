"""Group existing editor history steps by assistant turn."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time
import weakref

from cdmw.mcp.errors import FAILED, UNAVAILABLE, ToolError
from cdmw.mcp.names import EDIT, READ
from cdmw.mcp.rail_actions import press, tool
from cdmw.mcp.tools import ON_WORKER
from cdmw.mcp.ui_actions import run_action


_EDITOR_FAMILIES = {"mesh", "textures", "new_item", "placement"}
_GENERIC_EDITORS = {"app.run_command", "app.ui_act"}
_TURN_TOOLS = {"app.turn_end", "app.undo", "app.redo"}


def _tracks(call):
    return ((call.effect or call.tool.effect) == EDIT
            and (call.tool.family in _EDITOR_FAMILIES or call.tool.name in _GENERIC_EDITORS))


@dataclass(frozen=True)
class _Mark:
    cursor: int
    stamp: object


@dataclass(frozen=True)
class _Editor:
    kind: str
    owner: weakref.ReferenceType
    history_id: int

    def widget(self):
        from shiboken6 import isValid

        widget = self.owner()
        return widget if widget is not None and isValid(widget) else None

    def mark(self):
        widget = self.widget()
        if widget is None:
            return None
        if self.kind == "mesh":
            session = getattr(widget, "standalone_rust_authoring_session", None)
            history = getattr(session, "shared_history", None)
            if history is None or id(history) != self.history_id or getattr(session, "closed", False):
                return None
            state = history.current_history_payload()
            return _Mark(state["history_cursor"], state["history_revision"])
        if self.kind == "placement":
            edits = getattr(widget, "_edits", None)
            if edits is None or id(edits) != self.history_id:
                return None
            return _Mark(edits.command_count, tuple(id(command) for command in edits._commands))
        if self.kind == "new_item":
            if not widget.isVisible() or id(widget) != self.history_id:
                return None
            return _Mark(widget._history_index, tuple(id(record) for record in widget._history))
        history = widget.history_snapshots
        if not history or id(history[0]) != self.history_id:
            return None
        return _Mark(widget.history_index, tuple(id(record) for record in history))

    def ready(self):
        widget = self.widget()
        if widget is None:
            return False
        if self.kind == "mesh":
            from cdmw.mcp.mesh_tools import _busy

            return bool(widget.standalone_rust_ready and widget.standalone_rust_host_commands_supported
                        and not _busy(widget))
        if self.kind == "textures":
            return not widget._busy()
        if self.kind == "new_item":
            return not widget._io_active
        return True

    def move(self, direction):
        widget = self.widget()
        if widget is None:
            raise ToolError(UNAVAILABLE, f"The {self.kind} editor closed.")
        if self.kind == "mesh":
            if not widget._send_rust_command(f"session.{direction}"):
                raise ToolError(UNAVAILABLE, "The Mesh Editor did not take the history command.")
        elif self.kind == "placement":
            press(getattr(widget, f"_{direction}_button"))
        elif self.kind == "new_item":
            press(getattr(widget, f"{direction}_button"))
        else:
            getattr(widget, direction)()


def _target(kind, widget, history):
    return _Editor(kind, weakref.ref(widget), id(history))


def _capture(call):
    from cdmw.mcp.mesh_tools import shown_document
    from cdmw.mcp.texture_tools import target
    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    window = getattr(call.context, "window", None)
    shell = getattr(window, "shell", None)
    if shell is None:
        return {}
    family = call.tool.family if call.tool.name not in _GENERIC_EDITORS else ""
    editors = []
    if family in {"", "mesh", "textures"}:
        mesh = shown_document(call.context)
        session = getattr(mesh, "standalone_rust_authoring_session", None)
        shared = getattr(session, "shared_history", None)
        if shared is not None and (family != "textures" or call.arguments.get("editor", "docked") == "docked"):
            editors.append(_target("mesh", mesh, shared))
        if family in {"", "textures"}:
            locations = ("tool",) if shared is not None else ("tool", "docked")
            for location in locations:
                if family == "textures" and call.arguments.get("editor", "docked") != location:
                    continue
                editor = target(call.context, location)
                records = getattr(editor, "history_snapshots", None)
                if records:
                    editors.append(_target("textures", editor, records[0]))
    widgets = getattr(shell, "_tool_widgets_by_key", {})
    if family in {"", "new_item"}:
        wrapper = created_tool_widget(widgets.get("new_item_studio"))
        tab = getattr(wrapper, "workflow", wrapper)
        try:
            painter = getattr(getattr(tab, "model_panel", None), "_transparency_painter", None)
            if painter is not None:
                editors.append(_target("new_item", painter, painter))
        except RuntimeError:
            pass
    if family in {"", "placement"}:
        tab = created_tool_widget(widgets.get("placement_studio"))
        studio = getattr(tab, "_studio", None)
        edits = getattr(studio, "_edits", None)
        if edits is not None:
            editors.append(_target("placement", studio, edits))
    return {editor: mark for editor in editors if (mark := editor.mark()) is not None}


@dataclass
class _Step:
    editor: _Editor
    epoch: int
    before: int
    after: int
    current: int


class TurnHistory:
    """References and cursors only. The documents retain their own history records."""

    def __init__(self, lock):
        self.lock = lock
        self.pending = []
        self.undo_groups = deque(maxlen=64)
        self.redo_groups = deque(maxlen=64)
        self.known = {}
        self.epochs = {}
        self.partial = None

    def execute(self, call, operation):
        if call.tool.name in _TURN_TOOLS:
            with self.lock:
                call.check_cancelled()
                return operation()
        if not _tracks(call):
            return operation()
        with self.lock:
            call.check_cancelled()
            before = call.context.ui_call(lambda: _capture(call))
            try:
                return operation()
            finally:
                after = call.context.ui_call(lambda: _capture(call)) if before else {}
                self._observe(call, before, after)

    def _observe(self, call, before, after):
        name = call.tool.name
        direction = call.arguments.get("action") or call.arguments.get("command")
        manual_step = name in {"mesh.undo", "mesh.redo"} or str(direction).split(".")[-1] in {"undo", "redo"}
        for editor, start in before.items():
            end = after.get(editor)
            if end is None:
                continue
            if self.known.get(editor, start) != start or (manual_step and start != end):
                self.epochs[editor] = self.epochs.get(editor, 0) + 1
            self.known[editor] = end
            if manual_step or end.cursor <= start.cursor:
                continue
            self.pending.append(_Step(editor, self.epochs.get(editor, 0), start.cursor, end.cursor, end.cursor))
            self.redo_groups.clear()
            self.partial = None

    def end(self):
        group, self.pending = self.pending, []
        if group:
            self.undo_groups.append(group)
        return {"ended": True, "edit_calls": len(group), "editors": sorted({step.editor.kind for step in group})}

    def move(self, call, direction):
        self.end()
        undo = direction == "undo"
        source, destination = (self.undo_groups, self.redo_groups) if undo else (self.redo_groups, self.undo_groups)
        if self.partial is not None:
            group, original = self.partial
            source = original
            destination = self.redo_groups if undo else self.undo_groups
        elif source:
            group = source[-1]
        else:
            return {"moved": False, "steps": 0}

        moves = [(step, step.before if undo else step.after) for step in (reversed(group) if undo else group)]
        moves = [(step, goal) for step, goal in moves if step.current != goal]

        def verify():
            cursors = {}
            for step, goal in moves:
                editor = step.editor
                if editor not in cursors:
                    mark = editor.mark()
                    if mark is None or mark != self.known.get(editor) or not editor.ready():
                        raise ToolError(UNAVAILABLE, f"The {editor.kind} history has changed or is unavailable.")
                    cursors[editor] = mark.cursor
                if step.epoch != self.epochs.get(editor, 0) or cursors[editor] != step.current:
                    raise ToolError(UNAVAILABLE, f"The turn is no longer adjacent in the {editor.kind} history.")
                cursors[editor] = goal

        call.context.ui_call(verify)
        self.partial = (group, source)
        count = 0
        for step, goal in moves:
            while step.current != goal:
                call.check_cancelled()
                self._move_one(call, step, direction, goal)
                count += 1
        if source is not destination:
            source.pop()
            destination.append(group)
        self.partial = None
        return {"moved": bool(count), "steps": count, "editors": sorted({step.editor.kind for step, _ in moves})}

    def _move_one(self, call, step, direction, goal):
        editor = step.editor

        def move():
            if editor.mark() != self.known.get(editor) or not editor.ready():
                raise ToolError(UNAVAILABLE, f"The {editor.kind} history changed during the turn operation.")
            editor.move(direction)

        run_action(call.context, move)
        deadline = time.monotonic() + (15 if editor.kind == "mesh" else 0)
        while True:
            mark, ready = call.context.ui_call(lambda: (editor.mark(), editor.ready()))
            if mark is not None and mark.cursor != step.current and ready:
                low, high = sorted((step.current, goal))
                if not low <= mark.cursor <= high:
                    raise ToolError(FAILED, f"The {editor.kind} history moved outside the turn.")
                step.current = mark.cursor
                self.known[editor] = mark
                return
            if time.monotonic() >= deadline:
                raise ToolError(FAILED, f"The {editor.kind} editor did not finish the history step.")
            time.sleep(0.05)


def _turn_end(call):
    return call.turn_history.end()


def _undo(call):
    return call.turn_history.move(call, "undo")


def _redo(call):
    return call.turn_history.move(call, "redo")


def turn_tools():
    return [
        tool("app.turn_end", READ, "Close the current assistant turn so its editor steps can be undone together.",
             "mcp:TurnHistory.end", _turn_end, runs_on=ON_WORKER),
        tool("app.undo", EDIT, "Undo the most recent assistant turn using the editors' own Undo commands.",
             "mcp:TurnHistory.move", _undo, runs_on=ON_WORKER),
        tool("app.redo", EDIT, "Redo a turn undone by app_undo using the editors' own Redo commands.",
             "mcp:TurnHistory.move", _redo, runs_on=ON_WORKER),
    ]
