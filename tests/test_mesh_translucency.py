"""Material-only PAC output, history, drafts and cached viewport presentations."""

from dataclasses import replace
import copy
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from cdmw.core.pac_xml_standard_material import PlainMaterial, plain_material_xml, find_material_wrappers
from cdmw.domain.mesh.replacement import ReplacementFile
from cdmw.domain.mesh.translucency import translucency_values, authored_translucency
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from cdmw.services.mesh_replacement_import import initial_replacement_state, mesh_with_part_ids, commit_replacement
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from cdmw.services.mesh_translucency import build_translucency_files
from tests.test_mesh_editor_replacement import editor
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_rust_replacement import command


def sidecar(snapshot):
    text = "\r\n".join(
        f'<SkinnedMeshMaterialWrapper _subMeshName="{part.material or part.name}">\r\n'
        + plain_material_xml(PlainMaterial(base=f"texture/base{index}.dds", normal="texture/normal.dds",
                                          emissive_texture="texture/glow.dds", emissive_color="#12ABCDEF",
                                          emissive_intensity=4), newline="\r\n")
        + '\r\n</SkinnedMeshMaterialWrapper>'
        for index, part in enumerate(snapshot.mesh.submeshes)
    )
    path = snapshot.mesh.path.replace("/model/", "/modelproperty/") + "_xml"
    return ReplacementFile(path, text.encode())


def test_selected_part_output_keeps_pac_textures_emission_and_other_material(editor):
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    source = sidecar(snapshot)
    state = initial_replacement_state(snapshot, dependencies=(source,))
    state = replace(state, parts=(replace(state.parts[0], translucency=(.25, .75)), state.parts[1]))
    commit_replacement(service, snapshot, mesh_with_part_ids(snapshot, state), state, label="Translucency")
    result = prepare_replacement_output(service.capture_export_snapshot(sid))
    assert result.data == snapshot.original_data
    text = result.companion_files[0].data.decode()
    ET.fromstring("<root>" + text + "</root>")
    before, after = find_material_wrappers(source.data.decode()), find_material_wrappers(text)
    assert after[0].shader == "SkinnedMeshTranslucent"
    assert after[0].value("_thickness") == "0.250000"
    assert after[0].value("_extinctionCoefficient") == "0.750000"
    assert after[0].textures == before[0].textures
    assert after[0].value("_emissiveColor") == "#12ABCDEF"
    assert after[0].value("_emissiveIntensity") == before[0].value("_emissiveIntensity")
    assert text[after[1].start:after[1].end] == source.data.decode()[before[1].start:before[1].end]
    assert source == sidecar(snapshot)


@pytest.mark.parametrize("value", [[-1, .2], [.1, 2], [float("nan"), 0], [True, 0], [".1", 0], [], None])
def test_invalid_values_are_rejected(value):
    with pytest.raises(ValueError, match="thickness and extinction"):
        translucency_values(value)


def test_missing_base_missing_wrapper_shared_material_and_downgraded_draft_are_rejected(editor, tmp_path):
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    source = sidecar(snapshot)
    state = initial_replacement_state(snapshot, dependencies=(source,))
    state = replace(state, parts=(replace(state.parts[0], translucency=(.1, .3)), state.parts[1]))
    for altered, message in [
        (replace(state, dependencies=()), "matching PAC XML"),
        (replace(state, dependencies=(replace(source, data=source.data.replace(b'_baseColorTexture', b'_otherTexture')),)), "no base colour"),
        (replace(state, dependencies=(replace(source, data=source.data.replace(b'_subMeshName=', b'_otherName=')),)), "bindings were not found"),
    ]:
        with pytest.raises(ValueError, match=message):
            build_translucency_files(altered, snapshot.mesh, ())
    shared = copy.deepcopy(snapshot.mesh)
    shared.submeshes[1].material = shared.submeshes[0].material
    with pytest.raises(ValueError, match="sharing this material"):
        build_translucency_files(state, shared, ())
    directory = tmp_path / "generation"
    directory.mkdir()
    payload = save_replacement_state(state, tmp_path, directory)
    assert payload["version"] == 8 and load_replacement_state(payload, tmp_path) == state
    with pytest.raises(ValueError, match="version 8"):
        load_replacement_state({**payload, "version": 7}, tmp_path)


def test_rust_command_preview_reuse_undo_reset_finish_and_saved_output(tmp_path, monkeypatch):
    original, service, session = _open_exact_session(tmp_path / "session")
    try:
        snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        source = sidecar(snapshot)
        monkeypatch.setattr("cdmw.services.mesh_replacement_materials.capture_replacement_dependencies",
                            lambda *args: (source,))
        # Absorption edits must never re-decode the accepted material textures.
        monkeypatch.setattr("cdmw.services.mesh_rust_authoring._mesh_texture_payloads",
                            lambda *args, **kw: pytest.fail("texture decode on an absorption-only edit"))
        base = copy.deepcopy(session.archive_refit_material_cache["base"])
        key = session.state_payload()["translucency"]["parts"][0]["id"]

        def apply(values=(.1, .3), reset=False):
            return command(session, "replacement_translucency", {"part_ids": [key], "translucency": values, "reset": reset})

        changed = apply()
        material_key = changed["state"]["archive_refit_materials"]["key"]
        preview = session.archive_refit_material_cache[material_key]
        assert preview["textures"] == base["textures"]
        assert preview["material_presentations"][0]["translucency"] == [.1, .3]
        assert session.archive_refit_material_cache["base"] == base
        assert all(row.get("translucency") == [.1, .3] for row in preview["material_presentations"]
                   if row["material_index"] == 0)
        assert service.capture_export_snapshot(session.authoritative_session_id).replacement_state is None
        command(session, "undo")
        assert session.shadow_service.capture_export_snapshot(session.shadow_session_id).replacement_state is None
        command(session, "redo")
        restored = apply(reset=True)
        assert restored["state"]["archive_refit_materials"]["key"] == "base"
        assert not prepare_replacement_output(session.shadow_service.capture_export_snapshot(session.shadow_session_id)).companion_files
        apply((.4, .6))
        before_failure = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        with monkeypatch.context() as failure:
            failure.setattr("cdmw.services.mesh_rust_replacement_materials.stage_replacement_materials",
                            lambda *args: (_ for _ in ()).throw(RuntimeError("Renderer preparation failed")))
            with pytest.raises(RuntimeError, match="preparation failed"):
                apply((.2, .8))
        after_failure = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        assert after_failure.mesh_revision == before_failure.mesh_revision
        assert after_failure.replacement_state == before_failure.replacement_state
        session.finish(_request(session, "finish_request", 22))
        final = service.capture_export_snapshot(session.authoritative_session_id)
        result = prepare_replacement_output(final)
        assert result.data == original
        assert find_material_wrappers(result.companion_files[0].data.decode())[0].value("_thickness") == "0.400000"
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)


def test_imported_companion_is_preserved_when_absorption_is_restored(editor):
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    source = sidecar(snapshot)
    imported = replace(source, data=source.data.replace(b"texture/base0.dds", b"texture/imported.dds"))
    state = initial_replacement_state(snapshot, dependencies=(source,))
    state = replace(state, companion_files=(imported,), parts=(
        replace(state.parts[0], material_choice="imported", translucency=(.1, .3)), state.parts[1]))
    changed = build_translucency_files(state, snapshot.mesh, state.companion_files)
    assert b"texture/imported.dds" in changed[0].data
    restored = replace(state, parts=tuple(replace(part, translucency=None) for part in state.parts))
    assert build_translucency_files(restored, snapshot.mesh, state.companion_files) == (imported,)


def test_exported_shader_parameters_are_read_back_into_the_renderer(monkeypatch):
    from cdmw.services import mesh_rust_authoring as authoring
    from cdmw.domain.model_preview_materials import PreviewMaterialTextureInput, PreviewMaterialParameterInput
    parameters = (PreviewMaterialParameterInput(parameter_name="_thickness", value=".4"),
                  PreviewMaterialParameterInput(parameter_name="_extinctionCoefficient", numeric_value=.6))
    part = SimpleNamespace(name="Crystal", material="Crystal", preview_material_texture_inputs=(
        PreviewMaterialTextureInput(shader_family="SkinnedMeshTranslucent", material_parameters=parameters),
    ))
    assert authored_translucency(part) == (.4, .6)
    monkeypatch.setattr(authoring, "mesh_dotnet_material_state_payload", lambda *args, **kw: {
        "submeshes": [{"submesh_index": 0, "material_slot_index": 0, "parameters": {}}]})
    mesh = SimpleNamespace(path="test.pac", submeshes=[part], lod_levels=[])
    assert authoring._mesh_material_presentations(mesh)[0]["translucency"] == (.4, .6)
    part.preview_sidecar_shader_family = "SkinnedMeshStandard"
    assert authored_translucency(part) is None
    part.preview_sidecar_shader_family = ""
    part.preview_material_texture_inputs = ()
    assert authored_translucency(part) is None  # A glass-sounding name is insufficient.


def test_captured_draft_command_preparation_does_not_require_a_live_archive(editor):
    from cdmw.ui.mesh_editor.replacement_flow import prepare_replacement_event
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    state = initial_replacement_state(snapshot, dependencies=(sidecar(snapshot),))
    service._session(sid).replacement_state = state
    session = SimpleNamespace(shadow_service=service, shadow_session_id=sid)
    tab = SimpleNamespace(standalone_rust_authoring_session=session, standalone_rust_closing=False)
    event = {"command": "replacement_translucency", "arguments": {"part_ids": [state.parts[0].part_id], "translucency": [.1, .3]}}
    assert prepare_replacement_event(tab, session, event) == event
    tab.standalone_rust_closing = True
    with pytest.raises(ValueError, match="closed"):
        prepare_replacement_event(tab, session, event)
