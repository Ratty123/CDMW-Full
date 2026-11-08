"""Import Replacement asks for Blender only for an FBX, once, and shares New Item's choice."""

import pytest

from cdmw.ui.mesh_editor import replacement_flow
from cdmw.ui.new_item import blender_setting


def _dialog(monkeypatch, answer):
    asked = []

    def dialog(_parent, caption, start, _filter):
        asked.append((caption, start))
        return answer, ""

    monkeypatch.setattr(replacement_flow.QFileDialog, "getOpenFileName", staticmethod(dialog))
    return asked


def test_a_chosen_blender_is_used_without_asking(monkeypatch):
    monkeypatch.setattr(blender_setting, "blender_for_fbx", lambda: "C:/Blender/blender.exe")
    asked = _dialog(monkeypatch, "")
    assert replacement_flow._blender_for(None, "dragon.fbx") == "C:/Blender/blender.exe"
    assert asked == []


def test_no_blender_asks_and_remembers_the_answer(monkeypatch):
    remembered = []
    monkeypatch.setattr(blender_setting, "blender_for_fbx", lambda: "")
    monkeypatch.setattr(blender_setting, "suggested_blender", lambda: None)
    monkeypatch.setattr(blender_setting, "remember_blender", lambda path: remembered.append(path) or path)
    asked = _dialog(monkeypatch, "D:/Tools/blender.exe")
    assert replacement_flow._blender_for(None, "dragon.fbx") == "D:/Tools/blender.exe"
    assert asked == [("Choose the Blender that reads FBX", "")] and remembered == ["D:/Tools/blender.exe"]


def test_declining_the_blender_question_cancels(monkeypatch):
    monkeypatch.setattr(blender_setting, "blender_for_fbx", lambda: "")
    monkeypatch.setattr(blender_setting, "suggested_blender", lambda: None)
    _dialog(monkeypatch, "")
    assert replacement_flow._blender_for(None, "dragon.fbx") is None


def test_a_file_that_is_not_blender_is_refused(monkeypatch):
    monkeypatch.setattr(blender_setting, "blender_for_fbx", lambda: "")
    monkeypatch.setattr(blender_setting, "suggested_blender", lambda: None)
    monkeypatch.setattr(blender_setting, "remember_blender", lambda path: "")
    _dialog(monkeypatch, "C:/Windows/notepad.exe")
    with pytest.raises(ValueError, match="not a Blender"):
        replacement_flow._blender_for(None, "dragon.fbx")
