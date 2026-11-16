"""The UI thread's small questions to a preview manifest parse it once while it is unchanged.

The review measured 281 ms on the UI thread in Open in Mesh Editor, reading
and parsing the selected model's preview manifest (megabytes for a set piece)
several times per launch. These tests fail when a repeated question parses
the file again, and when a rewritten file is not read again.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from cdmw.services import json_file_facts
from cdmw.services.json_file_facts import json_file_fact
from cdmw.models import ArchiveEntry


@pytest.fixture(autouse=True)
def _fresh_memo():
    json_file_facts.forget_json_file_facts()
    yield
    json_file_facts.forget_json_file_facts()


@pytest.fixture
def parses(monkeypatch):
    calls = []
    real_loads = json.loads

    def counting_loads(*args, **kwargs):
        calls.append(1)
        return real_loads(*args, **kwargs)

    monkeypatch.setattr(json, "loads", counting_loads)
    return calls


def _write_old(path: Path, payload: dict, *, age_s: float = 60.0) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
    past = time.time() - age_s
    os.utime(path, (past, past))


def _first_key(payload):
    return sorted(payload)[0] if isinstance(payload, dict) and payload else ""


def test_fact_is_parsed_once_and_again_after_a_rewrite(tmp_path, parses):
    manifest = tmp_path / "manifest.json"
    _write_old(manifest, {"a": 1})
    assert json_file_fact(manifest, _first_key) == "a"
    assert json_file_fact(manifest, _first_key) == "a"
    assert len(parses) == 1
    _write_old(manifest, {"bb": 1}, age_s=30.0)
    assert json_file_fact(manifest, _first_key) == "bb"
    assert len(parses) == 2


def test_a_file_written_just_now_is_not_remembered(tmp_path, parses):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"a": 1}), encoding="utf-8")
    json_file_fact(manifest, _first_key)
    json_file_fact(manifest, _first_key)
    assert len(parses) == 2


def test_errors_are_not_remembered(tmp_path):
    manifest = tmp_path / "manifest.json"
    with pytest.raises(OSError):
        json_file_fact(manifest, _first_key)
    _write_old(manifest, {"a": 1})
    assert json_file_fact(manifest, _first_key) == "a"


def _entry(tmp_path: Path) -> ArchiveEntry:
    pamt = tmp_path / "0009" / "0.pamt"
    return ArchiveEntry(
        path="character/model/armor/cd_test_ub.pac", pamt_path=pamt, paz_file=pamt.with_name("0.paz"),
        offset=4096, comp_size=10, orig_size=10, flags=0, paz_index=0,
    )


def _manifest_for(entry: ArchiveEntry, *, source_path: str | None = None) -> dict:
    identity = entry.identity
    return {
        "source_path": source_path if source_path is not None else entry.path,
        "source_identity": {
            "normalized_path": identity.normalized_path,
            "source_pamt": str(entry.pamt_path),
            "paz_index": identity.paz_index,
            "entry_offset": identity.entry_offset,
        },
        "textures": [{"name": "t"}],
        "batches": [{"vertices": list(range(2000))}],
    }


def test_mesh_editor_entry_match_parses_the_manifest_once(tmp_path, parses):
    from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin

    entry = _entry(tmp_path)
    package = tmp_path / "package"
    package.mkdir()
    _write_old(package / "manifest.json", _manifest_for(entry))
    match = MeshEditorShellBridgeMixin._mesh_editor_package_matches_archive_entry
    assert match(package, entry) is True
    first = len(parses)
    for _ in range(3):
        assert match(package, entry) is True
    assert len(parses) == first, "the unchanged manifest was parsed again"
    _write_old(package / "manifest.json", _manifest_for(entry, source_path="other/model.pac"), age_s=30.0)
    assert match(package, entry) is False


def test_package_texture_and_source_questions_parse_the_manifest_once(tmp_path, parses):
    from cdmw.ui.archive_browser.preview_state import (
        archive_model_manifest_source_identity,
        archive_model_manifest_source_path,
        archive_model_package_has_textures,
    )

    entry = _entry(tmp_path)
    package = tmp_path / "package"
    package.mkdir()
    _write_old(package / "manifest.json", _manifest_for(entry))
    assert archive_model_package_has_textures(package) is True
    assert archive_model_manifest_source_path(package) == entry.path
    assert archive_model_manifest_source_identity(package) == (entry.path.casefold(), "")
    first = len(parses)
    for _ in range(3):
        assert archive_model_package_has_textures(package) is True
        assert archive_model_manifest_source_path(package) == entry.path
        assert archive_model_manifest_source_identity(package) == (entry.path.casefold(), "")
    assert len(parses) == first
    payload = _manifest_for(entry)
    payload["textures"] = []
    _write_old(package / "manifest.json", payload, age_s=30.0)
    assert archive_model_package_has_textures(package) is False


def _key_count(payload):
    return len(payload) if isinstance(payload, dict) else 0


def test_one_parse_answers_every_known_question_of_a_new_file(tmp_path, parses):
    first = tmp_path / "one" / "manifest.json"
    second = tmp_path / "two" / "manifest.json"
    for path in (first, second):
        path.parent.mkdir()
        _write_old(path, {"a": 1, "b": 2})
    json_file_fact(first, _first_key)
    json_file_fact(first, _key_count)
    assert len(parses) == 2
    assert json_file_fact(second, _first_key) == "a"
    assert json_file_fact(second, _key_count) == 2
    assert len(parses) == 3


def test_the_first_launch_on_a_new_package_parses_its_manifest_once(tmp_path, parses):
    from cdmw.services.mesh_rust_preview_cache import native_material_package_for_rust_preview
    from cdmw.ui.archive_browser.preview_state import (
        archive_model_manifest_source_identity,
        archive_model_package_has_textures,
    )
    from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin

    entry = _entry(tmp_path)
    package = tmp_path / "package"
    package.mkdir()
    _write_old(package / "manifest.json", _manifest_for(entry))
    assert archive_model_package_has_textures(package) is True
    manifest_parses = len(parses)
    assert MeshEditorShellBridgeMixin._mesh_editor_package_matches_archive_entry(package, entry) is True
    archive_model_manifest_source_identity(package)
    native_material_package_for_rust_preview(package)
    assert len(parses) == manifest_parses, "a registered question parsed the manifest again"
