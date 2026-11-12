"""The keymap's view of the registry: rows, conflicts and Qt shortcuts (P12 step 4).

One store (``cdmw.services.keymap_store``) holds every override. This module
turns registry commands into keymap rows (with the Mesh Editor's commands from
``cdmw/resources/mesh_editor_commands.json`` while no editor runs), names
conflicts, and keeps Qt shortcuts for shell and Browse Archives commands in
step with the keymap. The Texture Editor builds its own shortcuts and the Mesh
Editor helper its own; both read the same store and follow ``keymap_changed``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QKeySequence, QShortcut

from cdmw.services import keymap_store
from cdmw.ui.commands.registry import CommandRegistry

RESOURCE = Path(__file__).resolve().parents[2] / "resources" / "mesh_editor_commands.json"
#: Contexts whose commands get Qt shortcuts from this module.
QT_BOUND_CONTEXTS = ("shell", "browse")


@dataclass(frozen=True, slots=True)
class KeymapRow:
    command_id: str
    context: str
    label: str
    defaults: tuple[str, ...]
    keys: tuple[str, ...]
    #: The Mesh Editor helper's group for its own commands ("" otherwise).
    helper_group: str = ""

    @property
    def changed(self) -> bool:
        return self.keys != self.defaults

    @property
    def helper(self) -> bool:
        """Keys the Mesh Editor helper reads, in its own grammar (``helper_keys``)."""

        return bool(self.helper_group)

    @property
    def takes_modifier(self) -> bool:
        """The helper's selection modifiers take Ctrl, Alt or Shift on its own."""

        return self.helper_group == "SelectionModifiers"


@lru_cache(maxsize=1)
def mesh_editor_command_list() -> tuple[dict, ...]:
    """The helper's commands as committed beside its keymap (a Rust test keeps them equal)."""

    try:
        return tuple(json.loads(RESOURCE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return ()


def keymap_rows(registry: CommandRegistry, settings) -> list[KeymapRow]:
    overrides = keymap_store.load_keymap(settings)
    rows: dict[str, KeymapRow] = {}
    for command in registry.commands():
        if command.helper:
            continue  # the committed list below gives their defaults
        defaults = tuple(command.keys)
        if command.context == "texture_editor":
            from cdmw.domain.texture_editor_shortcuts import default_texture_editor_shortcuts

            key = command.id.split(".", 1)[1]
            defaults = tuple(k for k in (default_texture_editor_shortcuts().get(key, ""),
                                         default_texture_editor_shortcuts().get(f"{key}_alt", "")) if k)
        keys = tuple(overrides[command.id]) if command.id in overrides else defaults
        rows[command.id] = KeymapRow(command.id, command.context, command.label, defaults, keys)
    for spec in mesh_editor_command_list():
        command_id = keymap_store.MESH_PREFIX + str(spec.get("id", ""))
        defaults = tuple(str(key) for key in spec.get("defaults", ()))
        keys = tuple(overrides[command_id]) if command_id in overrides else defaults
        rows[command_id] = KeymapRow(command_id, "mesh_editor", str(spec.get("label", "")), defaults, keys,
                                     str(spec.get("group", "") or "Tools"))
    return sorted(rows.values(), key=lambda row: (row.context, row.label.casefold(), row.command_id))


def _normal(key: str) -> str:
    return QKeySequence(key).toString(QKeySequence.SequenceFormat.PortableText) or key


def conflicts(rows: list[KeymapRow]) -> dict[str, list[str]]:
    """Commands sharing a key where both are live: one context, or a shell key anywhere."""

    by_key: dict[str, list[KeymapRow]] = {}
    for row in rows:
        for key in row.keys:
            by_key.setdefault(_normal(key), []).append(row)
    result: dict[str, list[str]] = {}
    for holders in by_key.values():
        for row in holders:
            for other in holders:
                if other is row:
                    continue
                if row.context == other.context or "shell" in (row.context, other.context):
                    result.setdefault(row.command_id, []).append(other.command_id)
    return result


class QtShortcutBinder(QObject):
    """Qt shortcuts for shell (anywhere in the app's windows) and Browse (inside Browse)."""

    def __init__(self, registry: CommandRegistry, settings, *, shell_parent, browse_parent=None) -> None:
        super().__init__(shell_parent)
        self.registry, self.settings = registry, settings
        self._parents = {"shell": shell_parent, "browse": browse_parent}
        self._shortcuts: list[QShortcut] = []
        registry.keymap_changed.connect(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._shortcuts = []
        for row in keymap_rows(self.registry, self.settings):
            parent = self._parents.get(row.context)
            if parent is None or row.context not in QT_BOUND_CONTEXTS:
                continue
            for key in row.keys:
                shortcut = QShortcut(QKeySequence(key), parent)
                shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut if row.context == "shell"
                                    else Qt.ShortcutContext.WidgetWithChildrenShortcut)
                shortcut.activated.connect(lambda command_id=row.command_id: self._run(command_id))
                self._shortcuts.append(shortcut)

    def _run(self, command_id: str) -> None:
        self.registry.run_or_reason(command_id)  # a refusal is silent, as before; a failure is logged


def save_keys(registry: CommandRegistry, settings, command_id: str, keys: list[str] | None) -> None:
    """Rebind (a list, empty to unbind) or reset (None) one command, and tell every consumer."""

    keymap_store.set_override(settings, command_id, keys)
    registry.keymap_changed.emit()


def reset_all(registry: CommandRegistry, settings) -> None:
    keymap_store.reset_keymap(settings)
    registry.keymap_changed.emit()
