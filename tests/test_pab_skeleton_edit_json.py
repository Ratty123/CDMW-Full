"""Skeleton Edit JSON adds bones to the skeleton it came from and refuses anything else."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from cdmw.modding.skeleton_parser import parse_pab
from cdmw.services.pab_skeleton_edit_service import (
    PAB_EDIT_JSON_FORMAT,
    PabEditJsonError,
    apply_pab_edit_json,
    dumps_pab_edit_json,
)
from tests.test_pab_skeleton_writer import pab

PATH = "character/model/test/owned.pab"


def exported(data=None):
    return json.loads(dumps_pab_edit_json(data or pab(), PATH))


def test_export_lists_read_only_bones_and_an_empty_add_list():
    data = pab()
    payload = exported(data)
    assert payload["format"] == PAB_EDIT_JSON_FORMAT and payload["add_bones"] == []
    assert payload["source"] == {"path": PATH, "sha256": hashlib.sha256(data).hexdigest(), "bone_count": 3,
                                 "layout": "flags 0x17, 3 volume set(s)"}
    assert [(row["name"], row["parent"], row["core"]) for row in payload["bones"]] == [
        ("Bip01", None, 1), ("Bip01 Spine", "Bip01", 1), ("Bip01 Head", "Bip01 Spine", 0)]
    assert payload["bones"][1]["global_position"] == [10.0, 22.0, 0.0]
    unchanged = apply_pab_edit_json(data, json.dumps(payload), virtual_path=PATH)
    assert unchanged.data == data and unchanged.appended == ()


def test_added_bones_chain_and_survive_a_reformatted_document():
    data = pab()
    payload = exported(data)
    payload["add_bones"] = [
        {"parent": "Bip01 Spine", "name": "Cape_00", "position": [0, -0.2, 0]},
        {"parent": "Cape_00", "name": "Cape_01", "position": [0, -0.3, 0], "rotation": [0, 0, 0, 1],
         "scale": [1, 1, 1], "core": 0},
    ]
    payload["bones"][0]["position"] = [10, 20, 0.0000001]  # reference floats are ignored
    outcome = apply_pab_edit_json(data, json.dumps(payload, indent=4), virtual_path=PATH)
    assert outcome.appended == ("Cape_00", "Cape_01") and outcome.bone_count == 5
    rig = parse_pab(outcome.data)
    assert [(bone.name, bone.parent_index) for bone in rig.bones[3:]] == [("Cape_00", 1), ("Cape_01", 3)]


@pytest.mark.parametrize("fault", [
    "not json", "format", "version", "other source", "renamed bone", "removed bone", "add not list",
    "missing parent", "unknown field", "bad vector", "core", "duplicate name", "unknown parent",
])
def test_import_refuses_with_a_reason(fault):
    data = pab()
    payload = exported(data)
    payload["add_bones"] = [{"parent": "Bip01 Head", "name": "Hair_00"}]
    if fault == "format":
        payload["format"] = "cdmw.prefab-edit"
    elif fault == "version":
        payload["version"] = 2
    elif fault == "other source":
        payload["source"]["sha256"] = "0" * 64
    elif fault == "renamed bone":
        payload["bones"][2]["name"] = "Head"
    elif fault == "removed bone":
        del payload["bones"][2]
    elif fault == "add not list":
        payload["add_bones"] = {"parent": "Bip01"}
    elif fault == "missing parent":
        del payload["add_bones"][0]["parent"]
    elif fault == "unknown field":
        payload["add_bones"][0]["index"] = 3
    elif fault == "bad vector":
        payload["add_bones"][0]["position"] = [0, 1]
    elif fault == "core":
        payload["add_bones"][0]["core"] = True
    elif fault == "duplicate name":
        payload["add_bones"][0]["name"] = "Bip01 Spine"
    elif fault == "unknown parent":
        payload["add_bones"][0]["parent"] = "Tail_00"
    text = "{" if fault == "not json" else json.dumps(payload)
    with pytest.raises(PabEditJsonError):
        apply_pab_edit_json(data, text, virtual_path=PATH)


def test_archive_browser_import_writes_a_loose_mod_only_after_the_edit_applies(tmp_path, monkeypatch):
    from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
    from cdmw.ui.archive_browser import pab_json_actions as actions
    from cdmw.ui.archive_browser.workspace import ArchiveBrowserWorkspace

    assert issubclass(ArchiveBrowserWorkspace, actions.ArchivePabJsonActionsMixin)
    data = pab()
    payload = exported(data)
    payload["add_bones"] = [{"parent": "Bip01 Head", "name": "Hair_00", "position": [0, 0.1, 0]}]
    document = tmp_path / "owned.skeleton-edit.json"
    document.write_text(json.dumps(payload), encoding="utf-8-sig")  # Notepad adds a byte-order mark
    monkeypatch.setattr(actions.QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(document), ""))
    monkeypatch.setattr(actions, "read_archive_entry_data", lambda entry: (data, False, ""))
    exports, messages = [], []

    def fake_export(requests, **kwargs):
        exports.append((requests, kwargs))
        return ArchiveLooseExportResult(package_root=tmp_path / "mod", written_files=[])

    monkeypatch.setattr(actions, "export_archive_payloads_to_mod_ready_loose", fake_export)
    monkeypatch.setattr(actions.QMessageBox, "information", lambda *args: messages.append(args))
    tasks = []
    entry = SimpleNamespace(path=PATH, basename="owned.pab")
    shell = SimpleNamespace(set_status_message=lambda *args, **kwargs: None,
                            settings_file_path=tmp_path / "settings.json",
                            _run_utility_task=lambda **kwargs: tasks.append(kwargs),
                            _run_utility_task_when_idle=lambda **kwargs: tasks.append(kwargs))
    browser = SimpleNamespace(
        shell=shell,
        _current_archive_pab_entry=lambda: entry,
        _default_archive_pab_edit_json_path=lambda entry: document,
        _collect_archive_mod_ready_export_target=lambda **kwargs: (tmp_path, object(), True, False, None),
    )
    browser._write_pab_edit_loose_mod = lambda *args: actions.ArchivePabJsonActionsMixin._write_pab_edit_loose_mod(
        browser, *args)
    actions.ArchivePabJsonActionsMixin._import_current_archive_pab_edit_json(browser)
    tasks[0]["on_complete"](tasks[0]["task"](lambda _message: None))
    assert not exports and len(tasks) == 2
    tasks[1]["on_complete"](tasks[1]["task"](lambda _message: None))
    (request,), kwargs = exports[0]
    assert request.entry is entry and kwargs["parent_root"] == tmp_path
    assert [bone.name for bone in parse_pab(request.payload_data).bones][-1] == "Hair_00"
    assert "Added: Hair_00" in messages[-1][2]
