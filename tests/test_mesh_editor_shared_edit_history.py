"""Work B item 4: one history for mesh edits and texture edits."""

from __future__ import annotations

from cdmw.ui.mesh_editor.shared_edit_history import TEXTURE_EDIT_LABEL, NextStep, SharedEditHistory


def _host(applied: list[str], undone: list[str] = ()) -> list[dict[str, str]]:
    """The shadow session's entries: applied in order, then undone with the next redo first."""

    return ([{"action": "mesh_edit", "label": label, "state": "applied"} for label in applied]
            + [{"action": "mesh_edit", "label": label, "state": "undone"} for label in undone])


class _Texture:
    """A texture's editor history: record ids and the index of the current one."""

    def __init__(self, history: SharedEditHistory, key: str) -> None:
        self.history, self.key, self.records, self.index = history, key, [object()], 0
        history.observe_texture(key, key + ".dds", self.records, self.index)

    def edit(self) -> None:
        self.records = self.records[: self.index + 1] + [object()]
        self.index += 1
        self.history.observe_texture(self.key, self.key + ".dds", self.records, self.index)


def _check(fields: dict[str, object]) -> list[tuple[str, str]]:
    entries = fields["history_entries"]
    cursor = fields["history_cursor"]
    # The three counts the editor's History list requires to agree.
    assert fields["undo_count"] == cursor
    assert fields["redo_count"] == len(entries) - cursor
    assert all("state" not in e for e in entries)  # the cursor says which are applied
    return [(e["label"], e.get("texture", "")) for e in entries]


def _keys(fields):
    return list(fields["history_entries"])


def test_mesh_texture_mesh_then_undo_redo_and_a_new_texture_edit():
    history = SharedEditHistory()
    texture = _Texture(history, "ub_d")
    assert _check(history.merged(_host([]))) == []

    _check(history.merged(_host(["Move"])))
    texture.edit()
    fields = history.merged(_host(["Move", "Scale"]))
    assert _check(fields) == [("Move", ""), (TEXTURE_EDIT_LABEL, "ub_d.dds"), ("Scale", "")]
    keys = _keys(fields)

    # Undo three times: Scale (mesh), the texture edit, Move (mesh).
    assert history.next_undo() == NextStep("mesh")
    history.expect_mesh("undo")
    fields = history.merged(_host(["Move"], ["Scale"]))
    assert _check(fields)[2] == ("Scale", "") and fields["history_cursor"] == 2
    assert _keys(fields) == keys

    assert history.next_undo() == NextStep("texture", "ub_d")
    texture.index = 0
    history.texture_stepped("ub_d", "undo", 0)
    fields = history.merged(_host(["Move"], ["Scale"]))
    assert fields["history_cursor"] == 1 and _keys(fields) == keys

    assert history.next_undo() == NextStep("mesh")
    history.expect_mesh("undo")
    fields = history.merged(_host([], ["Move", "Scale"]))
    assert fields["history_cursor"] == 0 and _keys(fields) == keys
    assert history.next_undo() is None

    # Redo once: Move.
    assert history.next_redo() == NextStep("mesh")
    history.expect_mesh("redo")
    fields = history.merged(_host(["Move"], ["Scale"]))
    assert fields["history_cursor"] == 1 and _keys(fields) == keys
    assert history.next_redo() == NextStep("texture", "ub_d")

    # A new texture edit drops the undone texture edit and Scale, which stays hidden.
    texture.edit()
    fields = history.merged(_host(["Move"], ["Scale"]))
    assert _check(fields) == [("Move", ""), (TEXTURE_EDIT_LABEL, "ub_d.dds")]
    assert history.next_redo() is None

    # The next mesh edit clears the shadow redo; nothing hidden comes back.
    fields = history.merged(_host(["Move", "Smooth"]))
    assert _check(fields) == [("Move", ""), (TEXTURE_EDIT_LABEL, "ub_d.dds"), ("Smooth", "")]


def test_a_new_mesh_edit_after_undoing_a_texture_drops_it():
    history = SharedEditHistory()
    texture = _Texture(history, "ub_n")
    texture.edit()
    history.merged(_host([]))
    history.texture_stepped("ub_n", "undo", 0)
    assert history.current_history_payload()["redo_count"] == 1
    # Without a redo on its way, one more applied mesh entry is a new edit.
    fields = history.merged(_host(["Move"]))
    assert _check(fields) == [("Move", "")]


def test_a_redo_and_a_new_edit_with_the_same_counts_are_told_apart():
    history = SharedEditHistory()
    history.merged(_host(["Move"]))
    history.expect_mesh("undo")
    history.merged(_host([], ["Move"]))
    # A new edit after the undo: the shadow session's counts look like a redo's.
    fields = history.merged(_host(["Scale"]))
    assert _check(fields) == [("Scale", "")]


def test_cleared_history_and_a_discarded_stroke_keep_the_texture_entries():
    history = SharedEditHistory()
    texture = _Texture(history, "ub_d")
    history.merged(_host(["Move"]))
    texture.edit()
    history.merged(_host(["Move", "Scale"]))
    # A stroke the shadow session discarded (one applied entry fewer, no undo asked).
    assert _check(history.merged(_host(["Move"]))) == [("Move", ""), (TEXTURE_EDIT_LABEL, "ub_d.dds")]
    # Finish or a reload clears the mesh history.
    assert _check(history.merged(_host([]))) == [(TEXTURE_EDIT_LABEL, "ub_d.dds")]


def test_an_undo_made_in_the_texture_editor_itself_is_followed():
    history = SharedEditHistory()
    texture = _Texture(history, "ub_d")
    history.merged(_host(["Move"]))
    texture.edit()
    texture.index = 0
    assert history.observe_texture("ub_d", "ub_d.dds", texture.records, 0) is True
    fields = history.current_history_payload()
    assert _check(fields) == [("Move", ""), (TEXTURE_EDIT_LABEL, "ub_d.dds")]
    assert fields["history_cursor"] == 1
    assert history.next_redo() == NextStep("texture", "ub_d")


def test_a_forgotten_texture_leaves_the_history_and_the_revision_moves():
    history = SharedEditHistory()
    texture = _Texture(history, "ub_d")
    texture.edit()
    revision = history.revision
    history.forget_texture("ub_d")
    assert history.current_history_payload()["history_entries"] == [] and history.revision > revision


def test_edits_made_before_the_first_look_are_entries():
    history = SharedEditHistory()
    opened, first, second = object(), object(), object()
    assert history.observe_texture("ub_d", "ub_d.dds", [opened, first, second], 2) is True
    assert _check(history.current_history_payload()) == [(TEXTURE_EDIT_LABEL, "ub_d.dds")] * 2


def test_a_new_edit_right_after_an_undo_is_an_edit_not_a_redo():
    history = SharedEditHistory()
    texture = _Texture(history, "ub_d")
    texture.edit()
    texture.index = 0
    history.texture_stepped("ub_d", "undo", 0)
    texture.edit()  # the editor drops the undone record and appends a new one
    fields = history.current_history_payload()
    assert _check(fields) == [(TEXTURE_EDIT_LABEL, "ub_d.dds")]
    assert fields["history_cursor"] == 1
