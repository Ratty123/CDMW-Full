"""Material colours on a set's pieces (Open set in Mesh Editor, ticked Scene parts).

A set has no replacement state; its colour edits live in the set context with each
edited piece's captured .pac_xml, and Build Mod writes that file patched.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from cdmw.core.material_colours import wrapper_colours
from cdmw.domain.pac_xml_editor import decode_pac_xml_payload
from cdmw.services.mesh_archive_refit import load_archive_refit_context, save_archive_refit_context
from cdmw.services.mesh_asset_context import ASSET_ATTRIBUTE, PART_ATTRIBUTE
from tests.test_material_colours import FIXTURE, HANDLE
from tests.test_mesh_item_set_editing import _set
from tests.test_mesh_rust_authoring import _prepared_dds_entry


@pytest.fixture
def coloured_set(tmp_path, monkeypatch):
    import cdmw.services.mesh_material_colours as colours

    _source, service, key, context = _set(tmp_path)
    first = service.working_mesh(key).submeshes[0]
    asset = next(item for item in context.assets if item.asset_id == getattr(first, ASSET_ATTRIBUTE))
    part_id = getattr(first, PART_ATTRIBUTE)
    sidecar_path = colours._set_sidecar_path(asset.entry)
    sidecar = _prepared_dds_entry(tmp_path, sidecar_path, FIXTURE.read_bytes())
    ui = {"available": True, "reason": "", "parts": [{
        "id": part_id, "name": "upper", "asset_id": asset.asset_id, "material": f"{asset.asset_id}|{HANDLE.casefold()}",
        "shared": [part_id], "blocked": "", "material_colours": None,
        "rows": [{"name": "_tintColorR", "label": "Tint (red mask)", "original": "#F7C6AC", "alpha": 255}]}]}
    # The panel rows come from preview metadata, which this owned PAC has none of.
    monkeypatch.setattr(colours, "material_colours_ui_state", lambda *_args: ui)
    monkeypatch.setattr("cdmw.services.mesh_rust_replacement.replacement_ui_state", lambda _authoring: {})
    monkeypatch.setattr("cdmw.services.mesh_shader_controls.shader_controls_ui_state", lambda *_args: {})
    authoring = SimpleNamespace(shadow_service=service, shadow_session_id=key)
    dependencies = SimpleNamespace(entries_by_normalized_path={sidecar_path: (sidecar,)})
    try:
        yield SimpleNamespace(service=service, key=key, asset=asset, part_id=part_id, sidecar=sidecar,
                              authoring=authoring, dependencies=dependencies, colours=colours)
    finally:
        service.close_edit_session(key, force_without_saving=True)


def _apply(case, **args):
    return case.colours.set_item_set_material_colours(
        case.authoring, {"part_ids": [case.part_id], "_archive_dependencies": case.dependencies, **args})


def test_a_set_piece_takes_colours_with_its_material_file_and_one_undo_step(coloured_set):
    case = coloured_set
    _apply(case, colours={"_tintColorR": "#102030"})
    context = case.service._session(case.key).archive_refit_context
    assert context.material_colours == ((case.asset.asset_id, HANDLE.casefold(), (("_tintColorR", "#102030"),)),)
    ((asset, entry, data),) = context.material_colour_files
    assert asset == case.asset.asset_id and entry.path == case.sidecar.path and data == FIXTURE.read_bytes()
    (written,) = case.colours.item_set_colour_files(context)
    text, _ = decode_pac_xml_payload(written[2])
    assert wrapper_colours(text)[0][HANDLE.casefold()]["_tintColorR"] == "#102030ff"
    case.service.undo(case.key)
    assert not case.service._session(case.key).archive_refit_context.material_colours
    case.service.redo(case.key)
    assert case.service._session(case.key).archive_refit_context.material_colours
    _apply(case, reset=True)
    context = case.service._session(case.key).archive_refit_context
    assert not context.material_colours and not context.material_colour_files


def test_a_set_draft_keeps_the_colours_and_the_captured_material_file(coloured_set, tmp_path):
    case = coloured_set
    _apply(case, colours={"_tintColorR": "#102030"})
    context = case.service._session(case.key).archive_refit_context
    payload = save_archive_refit_context(context, tmp_path, threading.Event())
    restored = load_archive_refit_context(payload, tmp_path)
    assert restored.material_colours == context.material_colours
    assert [(asset, entry.path, data) for asset, entry, data in restored.material_colour_files] == [
        (asset, entry.path, data) for asset, entry, data in context.material_colour_files]


def test_a_wrong_wrapper_is_refused_when_the_colour_is_applied_not_at_build(coloured_set):
    case = coloured_set
    ui = case.colours.material_colours_ui_state()
    ui["parts"][0]["material"] = f"{case.asset.asset_id}|no_such_wrapper"
    with pytest.raises(ValueError, match="no wrapper"):
        _apply(case, colours={"_tintColorR": "#102030"})
    assert not case.service._session(case.key).archive_refit_context.material_colours


def test_build_mod_writes_the_set_piece_material_file(coloured_set, tmp_path, monkeypatch):
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputResult, MeshDirectOutputWorker

    case = coloured_set
    _apply(case, colours={"_tintColorR": "#102030"})
    requests, errors = [], []
    worker = MeshDirectOutputWorker(1, case.service, case.key, case.service._session(case.key).archive_refit_context.assets[0].entry,
                                    kind="loose_mod", output_path=tmp_path / "mod")

    def publish(rows, metadata, report):
        requests.extend(rows)
        return MeshDirectOutputResult(kind="loose_mod", output_path=tmp_path / "mod", rebuild_report=report)

    monkeypatch.setattr(worker, "_write_loose_mod", publish)
    worker.error.connect(lambda _id, message: errors.append(message))
    worker.run()
    assert not errors, errors
    # The colours alone are a change: the unchanged PACs are not written.
    (request,) = requests
    assert request.entry.path == case.sidecar.path
    text, _ = decode_pac_xml_payload(request.payload_data)
    assert wrapper_colours(text)[0][HANDLE.casefold()]["_tintColorR"] == "#102030ff"


def test_the_panel_is_open_in_a_set_and_keeps_each_piece_s_materials_apart(monkeypatch):
    from cdmw.services import mesh_asset_context
    from cdmw.services.mesh_material_colours import material_colours_ui_state

    monkeypatch.setattr(mesh_asset_context, "is_item_set", lambda context: True)
    saved = (("asset-a", "handle", (("_tintColorR", "#102030"),)),)
    session = SimpleNamespace(mesh_format="pac", hair_state=None, replacement_state=None,
                              archive_refit_context=SimpleNamespace(material_colours=saved))
    authoring = SimpleNamespace(shadow_session_id="s", shadow_service=SimpleNamespace(_session=lambda _id: session))
    replacement = {"reason": "Open one piece separately before importing a replacement", "parts": [
        {"index": 0, "id": "a:0", "name": "Handle", "asset_id": "asset-a"},
        {"index": 1, "id": "b:0", "name": "Handle", "asset_id": "asset-b"}]}
    rows = [{"kind": "", "name": "_tintColorR", "value": "#f7c6acff"}]
    shader = {"parts": [{"id": "a:0", "source": {"part": "handle"}, "authored": [{"rows": rows}]},
                        {"id": "b:0", "source": {"part": "handle"}, "authored": [{"rows": rows}]}]}
    ui = material_colours_ui_state(authoring, replacement, shader)
    first, second = ui["parts"]
    assert ui["available"] is True and ui["reason"] == ""
    # Two pieces with the same wrapper name are two materials.
    assert first["material"] == "asset-a|handle" and second["material"] == "asset-b|handle"
    assert first["shared"] == ["a:0"] and second["shared"] == ["b:0"]
    assert first["material_colours"] == {"_tintColorR": "#102030"} and second["material_colours"] is None
