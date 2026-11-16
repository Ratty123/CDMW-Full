"""One undo history for a Mesh Editor document's mesh edits and texture edits (Work B item 4).

The mesh history stays where it is (the shadow session's undo and redo stacks, on the
authoring worker); each texture's history stays in the Texture Editor's own session for it
(on the UI thread). This timeline only orders the two: it says which comes next for Undo and
Redo, and it is what the Rust editor's History list, Undo and Redo show. Every state sent to
the editor takes its history fields from ``merged`` so they always agree.

Rules, as in any single history: Undo takes the latest applied entry, Redo the first undone
one, and a new edit of either kind drops every undone entry. Undone mesh entries dropped by a
texture edit stay on the mesh redo stack until the next mesh edit clears it; they are hidden
here (``_hidden_mesh_redo``) and never offered again.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Iterable, Mapping

TEXTURE_EDIT_LABEL = "Texture edit"
"""The History label of a texture entry; the editor adds the texture's file name."""


@dataclass(slots=True)
class _Slot:
    kind: str  # "mesh" or "texture"
    applied: bool
    action: str
    label: str
    texture_key: str = ""
    texture_name: str = ""

    def as_history_dict(self) -> dict[str, object]:
        # Applied or undone is the cursor's to say: the editor reads no state per entry.
        entry: dict[str, object] = {"action": self.action, "label": self.label}
        if self.kind == "texture":
            entry["texture"] = self.texture_name
        return entry


@dataclass(frozen=True, slots=True)
class NextStep:
    """What Undo or Redo does next: ``kind`` "mesh" or "texture" (with its key)."""

    kind: str
    texture_key: str = ""


def _host_entries(entries: Iterable[object]) -> list[tuple[str, str, bool]]:
    rows = []
    for entry in entries or ():
        get = entry.get if isinstance(entry, Mapping) else (lambda name, default="", _e=entry: getattr(_e, name, default))
        rows.append((str(get("action", "") or "mesh_edit"), str(get("label", "") or ""),
                     str(get("state", "applied") or "applied") != "undone"))
    return rows


class SharedEditHistory:
    """The ordered history of one document. Thread-safe: the worker merges, the UI records."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: list[_Slot] = []
        self._hidden_mesh_redo = 0
        self._expected = ""  # "undo" or "redo" while a mesh step is on its way to the worker
        self._seen_records: dict[str, list[object]] = {}
        self._texture_index: dict[str, int] = {}
        self.revision = 0

    # Mesh side (any thread) ---------------------------------------------------

    def merged(self, host_entries: Iterable[object]) -> dict[str, object]:
        """The history fields for a state sent to the editor, after taking in the mesh
        history ``host_entries`` (the shadow session's entries, applied then undone)."""

        with self._lock:
            self._take_in_mesh(_host_entries(host_entries))
            return self._history_payload()

    def current_history_payload(self) -> dict[str, object]:
        with self._lock:
            return self._history_payload()

    def _history_payload(self) -> dict[str, object]:
        cursor = sum(1 for slot in self._slots if slot.applied)
        return {"history_entries": [slot.as_history_dict() for slot in self._slots], "history_cursor": cursor,
                "undo_count": cursor, "redo_count": len(self._slots) - cursor,
                "history_revision": self.revision}

    def _take_in_mesh(self, host: list[tuple[str, str, bool]]) -> None:
        applied_host = sum(1 for _action, _label, applied in host if applied)
        undone_host = len(host) - applied_host
        self._hidden_mesh_redo = min(self._hidden_mesh_redo, undone_host)
        visible = host[: len(host) - self._hidden_mesh_redo]
        mesh = [slot for slot in self._slots if slot.kind == "mesh"]
        applied_mesh = sum(1 for slot in mesh if slot.applied)
        expected, self._expected = self._expected, ""
        before = [(slot.kind, slot.applied, slot.label) for slot in self._slots]
        if applied_host == applied_mesh and len(visible) == len(mesh):
            pass
        elif applied_host == applied_mesh - 1 and len(visible) == len(mesh):
            last = max(i for i, slot in enumerate(self._slots) if slot.kind == "mesh" and slot.applied)
            self._move_to_boundary(last, applied=False)
        elif expected == "redo" and applied_host == applied_mesh + 1 and len(visible) == len(mesh):
            first = min(i for i, slot in enumerate(self._slots) if slot.kind == "mesh" and not slot.applied)
            self._move_to_boundary(first, applied=True)
        elif applied_host == applied_mesh + 1 and len(visible) == applied_host:
            # A new mesh edit: the shadow session cleared its redo; drop every undone entry.
            self._drop_undone()
            self._hidden_mesh_redo = 0
            action, label, _applied = visible[applied_host - 1]
            self._slots.append(_Slot("mesh", True, action, label))
        else:
            self._rebuild_mesh(visible, applied_host)
        # Labels follow the shadow session's, entry for entry.
        mesh = [slot for slot in self._slots if slot.kind == "mesh"]
        order = [row for row in visible if row[2]] + [row for row in visible if not row[2]]
        for slot, (action, label, _applied) in zip(
                [s for s in mesh if s.applied] + [s for s in mesh if not s.applied], order):
            slot.action, slot.label = action, label
        if [(slot.kind, slot.applied, slot.label) for slot in self._slots] != before:
            self.revision += 1

    def _rebuild_mesh(self, visible: list[tuple[str, str, bool]], applied_host: int) -> None:
        """Anything else (a cleared history, a discarded stroke): keep the texture entries
        where they are and fit the mesh entries to the shadow session's counts."""

        applied = [i for i, slot in enumerate(self._slots) if slot.kind == "mesh" and slot.applied]
        undone = [i for i, slot in enumerate(self._slots) if slot.kind == "mesh" and not slot.applied]
        undone_host = len(visible) - applied_host
        drop = set(applied[applied_host:]) | set(undone[undone_host:])
        self._slots = [slot for i, slot in enumerate(self._slots) if i not in drop]
        boundary = sum(1 for slot in self._slots if slot.applied)
        for _ in range(applied_host - min(applied_host, len(applied))):
            self._slots.insert(boundary, _Slot("mesh", True, "mesh_edit", ""))
            boundary += 1
        for _ in range(undone_host - min(undone_host, len(undone))):
            self._slots.append(_Slot("mesh", False, "mesh_edit", ""))
        self._slots = [s for s in self._slots if s.applied] + [s for s in self._slots if not s.applied]

    def _move_to_boundary(self, index: int, *, applied: bool) -> None:
        slot = self._slots.pop(index)
        slot.applied = applied
        boundary = sum(1 for other in self._slots if other.applied)
        self._slots.insert(boundary, slot)

    def _drop_undone(self) -> None:
        # A texture's undone edits stay in its editor session; nothing offers them again.
        self._slots = [slot for slot in self._slots if slot.applied]

    # Routing (UI thread) ------------------------------------------------------

    def next_undo(self) -> NextStep | None:
        with self._lock:
            applied = [slot for slot in self._slots if slot.applied]
            return NextStep(applied[-1].kind, applied[-1].texture_key) if applied else None

    def next_redo(self) -> NextStep | None:
        with self._lock:
            undone = [slot for slot in self._slots if not slot.applied]
            return NextStep(undone[0].kind, undone[0].texture_key) if undone else None

    def expect_mesh(self, step: str) -> None:
        """A mesh Undo or Redo is going to the worker; the next merge takes it in as one."""

        with self._lock:
            self._expected = step

    def texture_stepped(self, texture_key: str, step: str, history_index: int) -> None:
        """The Texture Editor undid or redid ``texture_key`` at Undo's or Redo's request."""

        with self._lock:
            self._texture_index[texture_key] = int(history_index)
            if step == "undo":
                index = max((i for i, s in enumerate(self._slots) if s.applied), default=-1)
            else:
                index = min((i for i, s in enumerate(self._slots) if not s.applied), default=-1)
            if index >= 0 and self._slots[index].texture_key == texture_key:
                self._move_to_boundary(index, applied=step != "undo")
                self.revision += 1

    # Texture side (UI thread) -------------------------------------------------

    def observe_texture(self, texture_key: str, texture_name: str, records: Iterable[object],
                        history_index: int) -> bool:
        """Take in a texture's editor history after a change: its history records (the
        editor's own objects) and the index of the current one. New records are new edits;
        a moved index without new records is an undo or redo made in the editor itself.
        True when the timeline changed.

        Records are compared by identity and the last seen ones are held, so a record
        dropped by a new edit cannot hand its id to the new one before it is seen."""

        current = list(records)
        index = int(history_index)
        with self._lock:
            seen = self._seen_records.get(texture_key)
            self._seen_records[texture_key] = current
            if seen is None:
                # The first record is the texture as it was opened; any after it up to the
                # current one are edits made before the first look (a patch comes after them).
                new = current[1: index + 1]
                before = 0
            else:
                known = {id(record) for record in seen}
                new = [record for record in current[: index + 1] if id(record) not in known]
                before = self._texture_index.get(texture_key, index)
            self._texture_index[texture_key] = index
            changed = False
            if new:
                self._drop_undone_for_edit()
                for _ in new:
                    self._slots.append(_Slot("texture", True, "texture_edit", TEXTURE_EDIT_LABEL,
                                             texture_key, texture_name))
                changed = True
            elif index != before:
                changed = self._follow_editor_step(texture_key, index - before)
            if changed:
                self.revision += 1
            return changed

    def _drop_undone_for_edit(self) -> None:
        self._hidden_mesh_redo += sum(1 for slot in self._slots if slot.kind == "mesh" and not slot.applied)
        self._slots = [slot for slot in self._slots if slot.applied]

    def _follow_editor_step(self, texture_key: str, delta: int) -> bool:
        changed = False
        for _ in range(abs(delta)):
            if delta < 0:
                found = [i for i, s in enumerate(self._slots) if s.applied and s.texture_key == texture_key]
                if found:
                    self._move_to_boundary(found[-1], applied=False)
                    changed = True
            else:
                found = [i for i, s in enumerate(self._slots) if not s.applied and s.texture_key == texture_key]
                if found:
                    self._move_to_boundary(found[0], applied=True)
                    changed = True
        return changed

    def forget_texture(self, texture_key: str) -> None:
        """The texture's editor session is gone: its entries cannot be undone any more."""

        with self._lock:
            before = len(self._slots)
            self._slots = [slot for slot in self._slots if slot.texture_key != texture_key]
            self._seen_records.pop(texture_key, None)
            self._texture_index.pop(texture_key, None)
            if len(self._slots) != before:
                self.revision += 1


__all__ = ["NextStep", "SharedEditHistory", "TEXTURE_EDIT_LABEL"]
