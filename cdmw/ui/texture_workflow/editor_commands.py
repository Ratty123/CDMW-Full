"""The Texture Editor's commands in the registry (P12 step 2).

Every shortcut id the editor already had (``open_file``, ``tool_paint`` ...) is
a command ``texture_editor.<id>``, so saved shortcuts keep their ids; the two
menu entries without a shortcut (Export DDS, Preview Compressed) are commands
too, and the editor's Actions menu entries are views of them. The app builds
the editor embedded in the Textures workspace (``workspace_embedded``); there
its commands, like its keys, work only in the workspace's Edit mode.
"""

from __future__ import annotations

from dataclasses import replace
from weakref import ref

import shiboken6
from PySide6.QtCore import QObject, SIGNAL, Slot
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.commands.adapters import bind_action
from cdmw.ui.commands.registry import Command, CommandRegistry, UNAVAILABLE_REASON, command_registry
from cdmw.ui.texture_workflow.editor_shortcuts import texture_editor_shortcut_labels
from cdmw.ui.texture_workflow.editor_action_state import texture_editor_main_action_state

CONTEXT = "texture_editor"
BUSY_REASON = "Wait for the current task to finish."
NO_IMAGE_REASON = "Open an image first."
EDIT_MODE_REASON = "Switch Textures to Edit first."
#: Commands that open a document; they do not need one.
OPENING = frozenset({"open_file", "open_archive", "open_project"})
#: Menu-only commands: id -> (label, editor method name).
MENU_ONLY = {
    "export_dds": ("Export DDS...", "export_dds_dialog"),
    "preview_compressed": ("Preview Compressed", "preview_compressed_dds"),
}
#: Actions menu entry -> command it shows.
MENU_ACTIONS = {
    "action_open_file": "open_file",
    "action_open_archive": "open_archive",
    "action_open_project": "open_project",
    "action_save_project": "save_project",
    "action_export_png": "save_png",
    "action_export_dds": "export_dds",
    "action_preview_compressed": "preview_compressed",
    "action_send_replace": "send_replace",
    "action_send_workflow": "send_workflow",
    "action_send_item_icons": "send_item_icons",
}



#: What each Texture Editor command does, for the MCP tool table: saving and
#: exporting are output, tool switches and view steps read, the rest edits.
TEXTURE_EFFECTS: dict[str, str] = {
    "actual_size": "read",
    "brush_larger": "read",
    "brush_smaller": "read",
    "clear_selection": "edit",
    "copy_layer": "edit",
    "copy_selection_layer": "edit",
    "cut_selection": "edit",
    "export_dds": "output",
    "fit_view": "read",
    "hardness_harder": "read",
    "hardness_softer": "read",
    "new_layer": "edit",
    "open_archive": "read",
    "open_compare": "read",
    "open_file": "edit",
    "open_project": "edit",
    "paste_centered": "edit",
    "paste_layer": "edit",
    "preview_compressed": "read",
    "redo": "edit",
    "save_png": "output",
    "save_project": "output",
    "send_item_icons": "edit",
    "send_replace": "edit",
    "send_workflow": "edit",
    "toggle_quick_mask": "edit",
    "tool_clone": "read",
    "tool_dodge_burn": "read",
    "tool_erase": "read",
    "tool_fill": "read",
    "tool_gradient": "read",
    "tool_heal": "read",
    "tool_lasso": "read",
    "tool_move": "read",
    "tool_paint": "read",
    "tool_patch": "read",
    "tool_rect": "read",
    "tool_smudge": "read",
    "transform_float_layer": "edit",
    "undo": "edit",
}

def command_id(key: str) -> str:
    return f"{CONTEXT}.{key}"


def texture_editor_commands(editor, bindings: dict, keys: dict) -> list[Command]:
    def reason_for(key: str):
        def reason() -> str:
            if getattr(editor, "workspace_embedded", False) and getattr(editor.job, "mode", "edit") != "edit":
                return EDIT_MODE_REASON
            state = texture_editor_main_action_state(editor.document, busy=editor._busy())
            if not state.open_enabled:
                return BUSY_REASON
            if key not in OPENING and not state.document_action_enabled:
                return NO_IMAGE_REASON
            return ""
        return reason

    labels = texture_editor_shortcut_labels()
    commands = []
    for key, callback in bindings.items():
        if key == "clear_selection_alt":  # a second key for the same command
            continue
        shortcut = tuple(k for k in (keys.get(key, ""), keys.get(f"{key}_alt", "")) if k)
        commands.append(Command(command_id(key), labels.get(key, key), CONTEXT, callback, reason_for(key),
                                keys=shortcut, keywords=(key,), effect=TEXTURE_EFFECTS.get(key, "edit")))
    for key, (label, method) in MENU_ONLY.items():
        commands.append(Command(command_id(key), label, CONTEXT, getattr(editor, method), reason_for(key),
                                keywords=(key,), effect=TEXTURE_EFFECTS.get(key, "edit")))
    return commands


class _CommandOwners(QObject):
    """Resolve at invocation so creating a hidden editor cannot steal commands."""

    def __init__(self, registry):
        super().__init__(registry)
        self.editors = []
        self.preferred = None
        self.registry = ref(registry)
        self._focus_connection = None

    def add(self, editor):
        if any(owner() is editor for owner in self.editors):
            return
        owner = ref(editor)
        self.editors.append(owner)
        if self._focus_connection is None:
            self._focus_connection = QApplication.instance().focusChanged.connect(self.focus_changed)
        # The context ends both callbacks when the registry is destroyed. Neither
        # callback retains an editor after Qt deletes its widget.
        QObject.connect(editor, SIGNAL("destroyed(QObject*)"), self, lambda _object: self.remove(owner))
        QObject.connect(editor.actions_menu, SIGNAL("aboutToShow()"), self, lambda: self.select(owner()))

    def remove(self, owner):
        self.editors = [registered for registered in self.editors if registered is not owner]
        if self.preferred is owner:
            self.preferred = None
        if not self.editors and self._focus_connection is not None:
            QObject.disconnect(self._focus_connection)
            self._focus_connection = None

    @Slot(QWidget, QWidget)
    def focus_changed(self, _old, widget):
        if not shiboken6.isValid(self):
            return
        while widget is not None and shiboken6.isValid(widget):
            if any(owner() is widget for owner in self.editors):
                self.select(widget)
                return
            widget = widget.parentWidget()

    def select(self, editor):
        if not shiboken6.isValid(self) or editor is None or not shiboken6.isValid(editor):
            return
        owner = next((owner for owner in self.editors if owner() is editor), None)
        registry = self.registry()
        if owner is not None and registry is not None and shiboken6.isValid(registry):
            self.preferred = owner
            registry.refresh(CONTEXT)

    def current(self):
        if not shiboken6.isValid(self):
            return None
        live = []
        for owner in tuple(self.editors):
            editor = owner()
            if editor is None or not shiboken6.isValid(editor):
                self.remove(owner)
            else:
                live.append(editor)
        preferred = self.preferred() if self.preferred else None
        visible = [e for e in live if e.isVisible()]
        choices = visible or live
        if any(editor is preferred for editor in choices):
            return preferred
        return choices[0] if choices else None

    def command(self, key):
        owner = self.current()
        return owner._texture_commands[key] if owner is not None else None

    def route(self, command):
        key = command.id

        def reason():
            target = self.command(key)
            return target.reason() if target else UNAVAILABLE_REASON

        def run():
            target = self.command(key)
            if target:
                return target.run()

        return replace(command, run=run, reason=reason)


def install_texture_editor_commands(editor, bindings: dict, keys: dict) -> CommandRegistry | None:
    """Register the editor's commands and make its Actions menu views of them."""

    registry = command_registry()
    if registry is None:
        return None
    owners = getattr(registry, "_texture_editor_owners", None)
    if owners is None:
        owners = registry._texture_editor_owners = _CommandOwners(registry)
    commands = texture_editor_commands(editor, bindings, keys)
    editor._texture_commands = {command.id: command for command in commands}
    owners.add(editor)
    registry.register_all([owners.route(command) for command in commands], replace=True)
    if not getattr(editor, "_cdmw_follows_keymap", False):
        # A key changed in Settings > Shortcuts rebinds this editor's shortcuts at once.
        editor._cdmw_follows_keymap = True
        registry.keymap_changed.connect(editor._rebuild_shortcuts)
    for attribute, key in MENU_ACTIONS.items():
        action = getattr(editor, attribute, None)
        if action is not None and action.property("_cdmw_command_id") != command_id(key):
            bind_action(action, registry, command_id(key))
    return registry
