from dataclasses import replace
from types import SimpleNamespace
import threading

import pytest

from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.mesh_archive_refit import (
    archive_refit_snapshots, load_archive_refit_context, save_archive_refit_context,
)
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from cdmw.services.mesh_service import MeshService
from tests.test_mesh_archive_refit import _load_pair
from tests.test_mesh_neutral_face_editing import _appearance
from tests.test_mesh_rust_authoring_exact_output import _request, _rig_command


def _armor_appearance():
    appearance = _appearance()
    matrices = tuple(tuple(-value if index in {12, 13, 14} else value
                           for index, value in enumerate(row)) for row in appearance.skin_matrices)
    return replace(appearance, source="owned/armor.pabc", skin_matrices=matrices)


@pytest.mark.parametrize("role", ["body", "armor"])
@pytest.mark.parametrize("mapped", [(True, True), (True, False), (False, True)])
def test_neutral_archive_load_and_noop_finish_use_each_assets_mapping(tmp_path, role, mapped):
    appearances = (_appearance() if mapped[0] else None, _armor_appearance() if mapped[1] else None)
    source, authority, session, primary, armor, loaded = _load_pair(
        tmp_path, assign_body=False, primary_appearance=appearances[0], incoming_appearance=appearances[1], role=role,
    )
    try:
        assert loaded["result"]["role"] == role
        shadow = session.shadow_service.working_mesh(session.shadow_session_id)
        raw = parse_pac(source)
        for part, appearance in zip(shadow.submeshes, appearances, strict=True):
            expected = appearance.to_neutral(raw) if appearance is not None else raw
            assert part.vertices == expected.submeshes[0].vertices
        finished = session.finish(_request(session, "finish_request", 3))
        assert all(item["byte_identical"] for item in finished["exact_output_validation"]["assets"])
        snapshot = authority.capture_export_snapshot(session.authoritative_session_id)
        assert not snapshot.archive_refit_context.neutral_coordinates
        for _entry, component in archive_refit_snapshots(snapshot):
            rebuilt, report = authority.rebuild_result_from_snapshot(component)
            assert report.validation_status == "passed" and rebuilt.data == source
        assert primary.paz_file.read_bytes() == source and armor.pamt_path.read_bytes() == b"owned archive index"
    finally:
        session.cancel()
        authority.close_edit_session(session.authoritative_session_id, force_without_saving=True)


def test_neutral_body_slider_refits_armor_then_finish_draft_and_reopen_preserve_display(tmp_path):
    source, authority, session, primary, _armor, loaded = _load_pair(
        tmp_path, primary_appearance=_appearance(), incoming_appearance=_armor_appearance(),
    )
    reopened = None
    draft_service, draft_session_id = MeshService(), ""
    try:
        _rig_command(session, 3, "select", {"selection": {"source_indices": [0]}})
        _rig_command(session, 4, "morph_create", {"definition": {
            "profile_id": "fit", "profile_name": "Fit", "definition_id": "height", "label": "Height",
            "rule": "move", "axis": "z", "amount": 0.1, "feather": 0,
        }})
        _rig_command(session, 5, "refit_bind", {"submesh_indices": loaded["result"]["loaded_parts"]})
        shadow, sid = session.shadow_service, session.shadow_session_id
        before = shadow.working_mesh(sid, clone=True)
        _rig_command(session, 6, "morph_set_value", {"definition_id": "height", "value": 50, "phase": "end"})
        displayed = shadow.working_mesh(sid, clone=True)
        assert all(old.vertices != new.vertices for old, new in zip(before.submeshes, displayed.submeshes, strict=True))
        _rig_command(session, 7, "morph_bake", {})
        snapshot = shadow.capture_export_snapshot(sid)
        root = tmp_path / "draft"
        payload = save_archive_refit_context(snapshot.archive_refit_context, root, threading.Event())
        restored = load_archive_refit_context(payload, root)
        assert restored.neutral_coordinates
        assert [asset.neutral_appearance for asset in restored.assets] == [_appearance(), _armor_appearance()]
        raw_components = archive_refit_snapshots(replace(snapshot, archive_refit_context=restored))
        session.finish(_request(session, "finish_request", 8))
        committed = authority.capture_export_snapshot(session.authoritative_session_id)
        for index, ((_entry, component), (_other, expected)) in enumerate(zip(
            archive_refit_snapshots(committed), raw_components, strict=True,
        )):
            assert component.mesh.submeshes[0].vertices == expected.mesh.submeshes[0].vertices
            rebuilt, _report = authority.rebuild_result_from_snapshot(component)
            appearance = restored.assets[index].neutral_appearance
            reparsed = appearance.to_neutral(parse_pac(rebuilt.data))
            for actual, wanted in zip(reparsed.submeshes[0].vertices, displayed.submeshes[index].vertices, strict=True):
                assert actual == pytest.approx(wanted, abs=8e-5)
        # The authoritative draft stores source coordinates and both mappings.
        raw_payload = save_archive_refit_context(committed.archive_refit_context, root, threading.Event())
        project_path = root / "mesh_layer_project.json"
        authority._session(session.authoritative_session_id).mesh_layer_project_path = project_path
        authority.retry_mesh_layer_autosave(session.authoritative_session_id)
        draft_mesh = draft_service.load_mesh_bytes(source, str(primary.path), run_roundtrip=True)
        setattr(draft_mesh, "_cdmw_mesh_layer_project_path", str(project_path))
        draft_session_id = draft_service.open_edit_session(draft_mesh, mode="edit").session_id
        draft_context = draft_service._session(draft_session_id).archive_refit_context
        assert [asset.neutral_appearance for asset in draft_context.assets] == [_appearance(), _armor_appearance()]
        reopened = RustMeshAuthoringSession.create(
            SimpleNamespace(mesh_service=draft_service, active_session_id=draft_session_id),
            tmp_path / "reopened", process_generation=12,
        )
        redisplayed = reopened.shadow_service.working_mesh(reopened.shadow_session_id)
        for actual, wanted in zip(redisplayed.submeshes, displayed.submeshes, strict=True):
            for point, expected in zip(actual.vertices, wanted.vertices, strict=True):
                assert point == pytest.approx(expected)
        assert primary.paz_file.read_bytes() == source
        raw_payload["assets"][1]["neutral_appearance"]["skin_matrices"] = [[float("nan")] * 16]
        with pytest.raises(ValueError, match="neutral appearance"):
            load_archive_refit_context(raw_payload, root)
    finally:
        if reopened is not None:
            reopened.cancel()
        if draft_session_id:
            draft_service.close_edit_session(draft_session_id, force_without_saving=True)
        session.cancel()
        authority.close_edit_session(session.authoritative_session_id, force_without_saving=True)
