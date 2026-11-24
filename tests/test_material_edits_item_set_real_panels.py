"""Glow and Material colours on a set's pieces, through the real panel states and router.

The earlier set tests stubbed the panel state; both set defects found in the app were
in those panel states (they inherited Import Replacement's "Open one piece separately").
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from cdmw.core.material_colours import wrapper_colours
from cdmw.core.pac_xml_standard_material import find_material_wrappers, wrapper_key
from cdmw.domain.pac_xml_editor import decode_pac_xml_payload
from cdmw.services.mesh_archive_refit import load_archive_refit_context, save_archive_refit_context
from cdmw.services.mesh_asset_context import ASSET_ATTRIBUTE, PART_ATTRIBUTE
from tests.test_material_colours import FIXTURE, HANDLE
from tests.test_mesh_item_set_editing import _set
from tests.test_mesh_rust_authoring import _prepared_dds_entry

GLOW = {"color": [1.0, 0.5, 0.25], "intensity": 6.0,
        "animation": {"flow_u": 0.0, "flow_v": 0.0, "pulse_frequency": 0.0, "pulse_minimum": 0.0}, "rgb": None}


@pytest.fixture
def real_set(tmp_path):
    import cdmw.services.mesh_material_colours as colours

    _source, service, key, context = _set(tmp_path)
    first = service.working_mesh(key).submeshes[0]
    asset = next(item for item in context.assets if item.asset_id == getattr(first, ASSET_ATTRIBUTE))
    name = str(first.name or first.material).strip()
    # The piece's material file names this part's wrapper as the PAC does.
    text, _ = decode_pac_xml_payload(FIXTURE.read_bytes())
    sidecar = _prepared_dds_entry(tmp_path, colours._set_sidecar_path(asset.entry),
                                  b"\xef\xbb\xbf" + text.replace(HANDLE, name).encode("utf-8"))
    authoring = SimpleNamespace(shadow_service=service, shadow_session_id=key, neutral_appearance=None,
                                pending_replacement=None, replacement_comparison="edit", replacement_weight_notes=(),
                                item_set_contexts=())
    args = {"part_ids": [getattr(first, PART_ATTRIBUTE)],
            "_archive_dependencies": SimpleNamespace(entries_by_normalized_path={sidecar.path: (sidecar,)})}
    try:
        yield SimpleNamespace(service=service, key=key, asset=asset, name=name, sidecar=sidecar,
                              authoring=authoring, args=args, colours=colours)
    finally:
        service.close_edit_session(key, force_without_saving=True)


def _run(case, command, **extra):
    from cdmw.services.mesh_rust_replacement import run_replacement_command
    return run_replacement_command(case.authoring, command, {**case.args, **extra}, None)


def test_a_set_refuses_import_replacement_but_offers_glow_and_colours(real_set):
    from cdmw.services.mesh_emission import emission_ui_state
    from cdmw.services.mesh_rust_replacement import replacement_ui_state

    replacement = replacement_ui_state(real_set.authoring)
    assert replacement["available"] is False and replacement["blocked_by"] == "item_set"
    glow = emission_ui_state(real_set.authoring, replacement)
    assert glow["available"] is True and glow["reason"] == ""
    assert all(part["set_material"] for part in replacement["parts"])


def test_glow_on_a_set_piece_writes_its_material_file_and_a_glow_map(real_set):
    case = real_set
    _run(case, "replacement_emission", emission=GLOW)
    context = case.service._session(case.key).archive_refit_context
    assert [(asset, material) for asset, material, _choice in context.emissions] == [(case.asset.asset_id, case.name.casefold())]
    ((owner, entry, _original, written, extras),) = case.colours.item_set_material_files(context)
    assert owner is case.asset and entry.path == case.sidecar.path
    text, _ = decode_pac_xml_payload(written)
    (wrapper,) = [row for row in find_material_wrappers(text) if wrapper_key(row.submesh_name) == case.name.casefold()]
    assert wrapper.shader == "SkinnedMeshEmissive_Ver2"
    assert wrapper.value("_emissiveIntensity") is not None
    # The fixture material has no glow map of its own, so the writer adds one.
    assert [file.path.endswith("_cdmw_glow.dds") for file in extras] == [True]
    # Glow in the same panel state the editor reads.
    from cdmw.services.mesh_emission import emission_ui_state
    from cdmw.services.mesh_rust_replacement import replacement_ui_state
    rows = emission_ui_state(case.authoring, replacement_ui_state(case.authoring))["parts"]
    assert next(row for row in rows if row["id"] == case.args["part_ids"][0])["emission"]["intensity"] == 6.0
    case.service.undo(case.key)
    assert not case.service._session(case.key).archive_refit_context.emissions


def test_colours_and_glow_on_one_piece_are_written_together_and_kept_by_the_draft(real_set, tmp_path):
    case = real_set
    # Glow first captures the piece's material file; its colour rows then come from that file
    # (this owned PAC has no preview metadata to list them before).
    _run(case, "replacement_emission", emission=GLOW)
    _run(case, "replacement_material_colours", colours={"_tintColorR": "#102030"})
    context = case.service._session(case.key).archive_refit_context
    ((_owner, _entry, _original, written, _extras),) = case.colours.item_set_material_files(context)
    text, _ = decode_pac_xml_payload(written)
    assert wrapper_colours(text)[0][case.name.casefold()]["_tintColorR"] == "#102030ff"
    payload = save_archive_refit_context(context, tmp_path, threading.Event())
    restored = load_archive_refit_context(payload, tmp_path)
    assert restored.material_colours == context.material_colours
    assert [(asset, material, choice.to_dict()) for asset, material, choice in restored.emissions] == [
        (asset, material, choice.to_dict()) for asset, material, choice in context.emissions]
    _run(case, "replacement_emission", reset=True)
    context = case.service._session(case.key).archive_refit_context
    assert not context.emissions and context.material_colour_files  # the colours still need the file


def test_build_mod_adds_the_generated_glow_map_beside_the_material_file(real_set, tmp_path, monkeypatch):
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputResult, MeshDirectOutputWorker

    case = real_set
    _run(case, "replacement_emission", emission=GLOW)
    captured, errors = {}, []
    worker = MeshDirectOutputWorker(1, case.service, case.key,
                                    case.service._session(case.key).archive_refit_context.assets[0].entry,
                                    kind="loose_mod", output_path=tmp_path / "mod")

    def publish(rows, metadata, report, additions=()):
        captured["requests"], captured["additions"] = rows, additions
        return MeshDirectOutputResult(kind="loose_mod", output_path=tmp_path / "mod", rebuild_report=report)

    monkeypatch.setattr(worker, "_write_loose_mod", publish)
    worker.error.connect(lambda _id, message: errors.append(message))
    worker.run()
    assert not errors, errors
    assert [request.entry.path for request in captured["requests"]] == [case.sidecar.path]
    assert [str(item.path).endswith("_cdmw_glow.dds") for item in captured["additions"]] == [True]


def test_a_required_choice_is_named_in_the_refusal():
    from cdmw.mcp.errors import ToolError
    from cdmw.mcp.schema import validate_arguments

    schema = {"type": "object", "properties": {"action": {"type": "string", "enum": ["add", "remove"]}},
              "required": ["action"]}
    with pytest.raises(ToolError, match="action is required: one of add, remove"):
        validate_arguments({}, schema)


def test_the_set_preview_shows_a_piece_s_glow_on_its_own_part(tmp_path):
    from cdmw.domain.mesh.emission import EmissionChoice
    from cdmw.services.mesh_material_colours import stage_item_set_colour_preview
    from cdmw.services.mesh_rust_authoring import _session_root_identity

    glowing = SimpleNamespace(name="Coat", material="coat", vertices=[], faces=[])
    plain = SimpleNamespace(name="Coat", material="coat", vertices=[], faces=[])
    setattr(glowing, ASSET_ATTRIBUTE, "upper")
    setattr(plain, ASSET_ATTRIBUTE, "lower")  # the same wrapper name in another piece
    mesh = SimpleNamespace(submeshes=[glowing, plain], lod_levels=[[glowing, plain]])
    base_key = "a" * 32
    base = {"key": base_key, "textures": [], "material_presentations": [], "preview_core_material_graph": None}
    authoring = SimpleNamespace(root=tmp_path, root_identity=_session_root_identity(tmp_path),
                                archive_refit_material_cache={base_key: base}, archive_refit_material_references={})
    context = SimpleNamespace(material_colours=(), emissions=(("upper", "coat", EmissionChoice((1.0, 0.5, 0.25), 6.0)),))
    key = stage_item_set_colour_preview(authoring, mesh, context, base_key)
    assert key != base_key and set(authoring.archive_refit_material_references) == {base_key, key}
    rows = {row["material_index"]: row for row in authoring.archive_refit_material_cache[key]["material_presentations"]}
    assert rows[0]["emissive_color"] == [1.0, 0.5, 0.25] and rows[0]["emissive_intensity"] == 6.0
    assert 1 not in rows


def test_a_reopened_set_with_colours_declares_its_material_states_for_the_editor(real_set, tmp_path):
    """A set draft with colour edits starts the editor with the set's material states
    written; undeclared, the editor refused them and closed (2026-11-24)."""
    import hashlib
    import json

    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession

    case = real_set
    # Glow first captures the piece's material file, whose rows the colours then use.
    _run(case, "replacement_emission", emission=GLOW)
    _run(case, "replacement_material_colours", colours={"_tintColorR": "#102030"})
    context = case.service._session(case.key).archive_refit_context
    assert context.material_colours
    host = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=case.service, active_session_id=case.key),
                                           tmp_path / "reopened-host", process_generation=2)
    try:
        # The editor's own startup check first, as it sees the folder CDMW left.
        from tests.editor_session_check import assert_editor_accepts
        assert_editor_accepts(host.manifest_path)
        manifest = json.loads(host.manifest_path.read_text())
        active = manifest["state"]["archive_refit_materials"]["key"]
        references = manifest["replacement_material_states"]
        assert {row["path"] for row in references} == {
            f"material-state-{context.context_id}.json", f"material-state-{active}.json"}
        assert active != context.context_id and "base" not in {row["path"] for row in references}
        for row in references:
            assert hashlib.sha256((host.root / row["path"]).read_bytes()).hexdigest().upper() == row["sha256"].upper()
    finally:
        host.cancel()
