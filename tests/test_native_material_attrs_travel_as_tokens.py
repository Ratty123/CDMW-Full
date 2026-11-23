"""A Part's material presentation crosses the mesh core as a token (2026-11-23).

The core repeats every Part's ``extra_attrs`` in each session reply. The Demenissian
Council Robes' material overrides and texture inputs (1.8 MB a Part, the bound
Preview Core material source among them) made every reply a 40 MB line, and each
edit waited for four or five of them. They now go to the core as tokens and come
back as the same values; the materials themselves must come through every edit,
read-back, Duplicate, Undo and autosave unchanged.
"""

from __future__ import annotations

import json
import uuid

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding import mesh_native_attr_tokens as tokens
from cdmw.modding import mesh_native_client as client
from cdmw.modding.mesh_native_availability import native_mesh_core_available
from cdmw.services.mesh_service import MeshService

native = pytest.mark.skipif(not native_mesh_core_available(), reason="the native mesh core is not built")

ATTRS = tokens.TOKENIZED_EXTRA_ATTRS


def _overrides(tag: str) -> dict:
    # Shaped like a bound Preview Core material source: a large batch beside small settings.
    layers = [{"slot": index, "path": f"textures/{tag}_{index}.dds", "uv": [0.5 * index, 1.0]} for index in range(3000)]
    return {"alpha_cutoff": 0.5, "preview_core_material_source": {
        "package": f"C:/cache/{tag}", "batch": {"layers": layers}, "conservation": {"tag": tag}}}


def _inputs(tag: str) -> list:
    return [{"slot_kind": "base", "source_dds_path": f"C:/cache/{tag}/{index}.dds", "owner_slot_index": index}
            for index in range(2000)]


def test_values_round_trip_and_the_callers_payload_is_kept() -> None:
    big = _overrides("round")
    payload = {"command": "open", "submeshes": [
        {"index": 0, "extra_attrs": {"preview_native_material_overrides": big, "name": "kept"}},
        {"index": 1, "material_extra_attrs": {"preview_material_texture_inputs": _inputs("round")}},
        {"index": 2, "extra_attrs": {"preview_native_material_overrides": {"alpha_cutoff": 0.5}}},  # small
    ], "positions": [[0.0, 1.0, 2.0]] * 10}
    sent = tokens.tokenize_native_payload(payload)
    assert payload["submeshes"][0]["extra_attrs"]["preview_native_material_overrides"] is big  # not changed
    first = sent["submeshes"][0]["extra_attrs"]["preview_native_material_overrides"]
    assert isinstance(first, str) and first.startswith(tokens.TOKEN_PREFIX)
    assert sent["submeshes"][0]["extra_attrs"]["name"] == "kept"
    assert isinstance(sent["submeshes"][1]["material_extra_attrs"]["preview_material_texture_inputs"], str)
    assert sent["submeshes"][2] is payload["submeshes"][2]  # too small to be worth a token
    assert sent["positions"] is payload["positions"]
    assert len(json.dumps(sent)) < 2000 < len(json.dumps(big))
    assert tokens.tokenize_native_payload(sent) == sent  # a token stays a token

    back = tokens.restore_native_report(sent)
    assert back["submeshes"][0]["extra_attrs"]["preview_native_material_overrides"] == big
    assert back["submeshes"][1]["material_extra_attrs"]["preview_material_texture_inputs"] == _inputs("round")
    # Each Part gets its own outer container, as a parsed reply gave it.
    again = tokens.restore_native_report(sent)
    assert (again["submeshes"][0]["extra_attrs"]["preview_native_material_overrides"]
            is not back["submeshes"][0]["extra_attrs"]["preview_native_material_overrides"])


def test_a_token_this_process_never_issued_is_refused() -> None:
    forged = {"submeshes": [{"extra_attrs": {
        "preview_native_material_overrides": tokens.TOKEN_PREFIX + uuid.uuid4().hex}}]}
    with pytest.raises(tokens.UnknownNativeAttrToken):
        tokens.restore_native_report(forged)


@pytest.fixture
def reply_sizes(monkeypatch):
    sizes: list[int] = []
    read = client.NativeMeshCoreServiceClient._read_reply_locked

    def record(self, *args, **kwargs):
        line = read(self, *args, **kwargs)
        sizes.append(len(line))
        return line

    monkeypatch.setattr(client.NativeMeshCoreServiceClient, "_read_reply_locked", record)
    return sizes


def _material_state(mesh) -> list[tuple]:
    return [tuple(getattr(part, name, None) for name in ATTRS) for part in mesh.submeshes]


def _scenario() -> tuple[list, int]:
    """Edit, read back, Duplicate, Undo and Redo; the materials of every Part at each step."""

    from tests.test_mesh_service_editing import _quad_mesh

    mesh = _quad_mesh(two_parts=True)
    for index, part in enumerate(mesh.submeshes):
        part.preview_native_material_overrides = _overrides(f"part{index}")
        part.preview_material_texture_inputs = _inputs(f"part{index}")
    one_value = len(json.dumps(mesh.submeshes[0].preview_native_material_overrides))
    service = MeshService()
    view = service.open_edit_session(mesh, session_id=f"tokens-{uuid.uuid4().hex}", mode="edit")
    session_id = view.session_id
    steps = []
    try:
        service.apply_command(session_id, MeshEditCommand(
            "transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)}),
            params={"translate": (0.0, 0.0, 0.5)}))
        moved = service.working_mesh(session_id, clone=True)  # read back from the core
        assert moved.submeshes[0].vertices[0][2] == pytest.approx(0.5)
        steps.append(_material_state(moved))
        duplicated = service.apply_command(session_id, MeshEditCommand(
            "duplicate", selection=MeshEditSelection.from_maps(source_indices=(0,))))
        assert duplicated.ok and duplicated.topology_changed
        steps.append(_material_state(service.working_mesh(session_id, clone=True)))
        assert service.undo(session_id).ok
        steps.append(_material_state(service.working_mesh(session_id, clone=True)))
        assert service.redo(session_id).ok
        steps.append(_material_state(service.working_mesh(session_id, clone=True)))
    finally:
        service.close_edit_session(session_id, force_without_saving=True)
    return steps, one_value


@native
def test_materials_come_through_edits_duplicate_and_undo_as_without_tokens(reply_sizes, monkeypatch) -> None:
    from cdmw.modding import mesh_native_dispatch as dispatch

    steps, one_value = _scenario()
    assert one_value > 150_000
    assert reply_sizes and max(reply_sizes) < one_value, f"a reply carried the materials: {max(reply_sizes)} bytes"
    moved, duplicated, undone, redone = steps
    assert len(duplicated) == 3 and duplicated[2] == duplicated[0]  # the copy took part 0's materials
    assert duplicated[:2] == moved and undone == moved and redone == duplicated
    assert moved[0] != moved[1]

    # The same edits with the values sent whole, as before tokens: the same materials.
    monkeypatch.setattr(dispatch, "tokenize_native_payload", lambda payload: dict(payload))
    monkeypatch.setattr(dispatch, "restore_native_report", lambda report: report)
    reply_sizes.clear()
    whole, _ = _scenario()
    assert max(reply_sizes) > one_value  # the comparison run really sent them whole
    assert whole == steps


@native
def test_the_autosaved_layer_project_keeps_the_values_not_tokens(tmp_path) -> None:
    from tests.test_mesh_geometry_layers import _persistent_layer_mesh

    mesh, project_path, _manifest = _persistent_layer_mesh(tmp_path)
    mesh.submeshes[0].preview_native_material_overrides = _overrides("saved")
    service = MeshService()
    view = service.open_edit_session(mesh, session_id=f"tokens-saved-{uuid.uuid4().hex}", mode="edit")
    session_id = view.session_id
    try:
        service.apply_command(session_id, MeshEditCommand(
            "transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}),
            params={"translate": (0.25, 0.0, 0.0)}))
        service.retry_mesh_layer_autosave(session_id)
        saved = [path for path in project_path.parent.rglob("*.json")]
        assert saved
        text = "".join(path.read_text(encoding="utf-8", errors="replace") for path in saved)
        assert tokens.TOKEN_PREFIX not in text
        assert "textures/saved_2999.dds" in text  # the full value was written
    finally:
        service.close_edit_session(session_id, force_without_saving=True)
