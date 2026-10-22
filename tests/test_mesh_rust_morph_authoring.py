"""Pure host-bridge checks for authored sliders and scoped fitting controls.

These tests exercise real dispatch and Finish guards with a recording service.
They do not start the Rust process, create a native editor, or load game assets.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh import (
    MeshMorphDefinition,
    MeshMorphRule,
    MeshMorphSparseField,
    MeshMorphState,
    MeshMorphVertexWeight,
    MeshRefitBindingSummary,
    MeshRefitDriverRegion,
    MeshRefitGarmentSettings,
)
from cdmw.services import mesh_rust_authoring as bridge
from cdmw.services.mesh_rust_authoring import (
    RustMeshAuthoringSession,
    RustMeshValidationError,
)


_SELECTION_OPERATIONS = {
    "capture_morph_baseline",
    "set_refit_vertex_influence",
    "clear_refit_vertex_influence",
    "set_refit_driver_region",
}
_OPERATIONS = _SELECTION_OPERATIONS | {
    "fit_refit_to_body",
    "configure_refit_islands",
    "author_morph_definition",
    "cancel_morph_baseline",
    "capture_authored_morph_definition",
    "begin_morph_correction",
    "save_morph_correction",
    "cancel_morph_correction",
    "clear_refit_driver_region",
    "import_refit_recipe",
    "export_refit_recipe",
    "generate_body_morph_controls",
    "set_morph_macro",
    "reset_morph_macros",
    "set_morph_symmetry",
    "set_morph_side_value",
    "set_morph_corrections_enabled",
    "reset_morph_correction",
    "save_refit_setup",
    "apply_refit_setup",
}


class _RecordingService:
    def __init__(self) -> None:
        self.state = MeshMorphState()
        self.calls: list[tuple[str, tuple, dict]] = []
        self.result = object()
        self.live_selection = object()
        self.selection_reads: list[object] = []

    def session_view(self, session_id: str) -> object:
        assert session_id == "shadow"
        return SimpleNamespace(revision=7, authoring_enabled=True)

    def cached_morph_state_from_runtime(self, session_id: str) -> MeshMorphState:
        assert session_id == "shadow"
        return self.state

    def __getattr__(self, name: str):
        if name not in _OPERATIONS:
            raise AttributeError(name)

        def operation(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name in _SELECTION_OPERATIONS:
                selection = kwargs.get("selection")
                self.selection_reads.append(
                    self.live_selection if selection is None else selection
                )
            return self.result

        return operation


@pytest.fixture
def authoring_session(tmp_path: Path) -> RustMeshAuthoringSession:
    root = (tmp_path / "session").resolve()
    root.mkdir()
    service = _RecordingService()
    return RustMeshAuthoringSession(
        authoritative_service=SimpleNamespace(),
        authoritative_session_id="authoritative",
        shadow_service=service,
        shadow_session_id="shadow",
        root=root,
        root_identity=bridge._session_root_identity(root),
        session_id="bridge-authoring-test",
        process_generation=4,
        base_revision=7,
        base_geometry_layer_revision=0,
        base_morph_session_revision=0,
        source_weights_available=True,
        manifest_path=root / "manifest.json",
        theme={},
        acknowledged_morph_profile_fingerprint=bridge._directory_fingerprint(
            root / "mesh_slider_profiles"
        ),
    )


_DEFINITION = {
    "profile_id": "body",
    "profile_name": "Body",
    "definition_id": "waist",
    "label": "Sculpted waist",
    "category": "Authored",
    "min_percent": -100.0,
    "max_percent": 125.0,
    "default_percent": 0.0,
}


@pytest.mark.parametrize(
    ("command", "arguments", "method", "positional", "keywords"),
    [
        ("refit_fit_to_body", {}, "fit_refit_to_body", (), {}),
        ("refit_island_configure", {"islands": [{"submesh_index": 2, "face_indices": [0, 1]}], "enabled": False},
         "configure_refit_islands", (({"submesh_index": 2, "face_indices": [0, 1]},),), {"inherit": False, "enabled": False}),
        ("morph_capture_baseline", {"submesh_indices": [2, 0]},
         "capture_morph_baseline", ((2, 0),), {"selection": None}),
        ("morph_cancel_baseline", {}, "cancel_morph_baseline", (), {}),
        ("morph_generate_body_controls", {}, "generate_body_morph_controls", (), {}),
        ("morph_set_macro", {"macro_id": "waist_shape", "value": 35, "phase": "end"},
         "set_morph_macro", ("waist_shape", 35), {"phase": "end"}),
        ("morph_reset_macros", {}, "reset_morph_macros", (), {}),
        ("morph_set_symmetry", {"enabled": True}, "set_morph_symmetry", (True,), {}),
        ("morph_set_side_value", {"pair_id": "hip_size", "side": "left", "value": 25},
         "set_morph_side_value", ("hip_size", 25), {"side": "left", "phase": "end"}),
        ("morph_set_corrections_enabled", {"enabled": False},
         "set_morph_corrections_enabled", (False,), {}),
        ("morph_reset_correction", {"definition_id": "waist", "garment_submesh_indices": [3, 1]},
         "reset_morph_correction", ("waist", (3, 1)), {}),
        ("morph_save_setup", {"name": "Coat fit"}, "save_refit_setup", ("Coat fit",), {}),
        ("morph_apply_setup", {"recipe_id": "setup-id", "garment_submesh_indices": [3, 1]},
         "apply_refit_setup", ("setup-id", (3, 1)), {}),
        ("morph_capture_authored", {"definition": _DEFINITION},
         "capture_authored_morph_definition", (), _DEFINITION),
        ("morph_begin_correction",
         {"definition_id": "waist", "garment_submesh_indices": [3, 1]},
         "begin_morph_correction", ("waist", (3, 1)), {}),
        ("morph_save_correction", {}, "save_morph_correction", (), {}),
        ("morph_cancel_correction", {}, "cancel_morph_correction", (), {}),
        ("morph_set_influence", {"weight": 0.25, "garment_submesh_indices": [3, 1]},
         "set_refit_vertex_influence", (),
         {"selection": None, "weight": 0.25, "garment_submesh_indices": (3, 1)}),
        ("morph_clear_influence", {"garment_submesh_indices": [3, 1]},
         "clear_refit_vertex_influence", ((3, 1),), {"selection": None}),
        ("morph_set_driver_region", {"garment_submesh_indices": [3, 1]},
         "set_refit_driver_region", ((3, 1),), {"selection": None}),
        ("morph_clear_driver_region", {"garment_submesh_indices": [3, 1]},
         "clear_refit_driver_region", ((3, 1),), {}),
        ("morph_import_recipe",
         {"path": "saved-fit.json", "garment_submesh_indices": [3, 1]},
         "import_refit_recipe", ("saved-fit.json", (3, 1)), {}),
    ],
)
def test_authored_and_fitting_commands_dispatch_exact_scopes(
    authoring_session, command, arguments, method, positional, keywords,
):
    service = authoring_session.shadow_service
    result = authoring_session._run_morph_command(command, arguments)

    assert result is service.result
    assert service.calls == [(method, ("shadow", *positional), keywords)]


def test_recipe_export_uses_external_absolute_destination(authoring_session, tmp_path):
    destination = tmp_path / "saved-fit.json"
    service = authoring_session.shadow_service

    result = authoring_session._run_morph_command(
        "morph_export_recipe", {"path": str(destination), "name": "Coat fit"}
    )

    assert result is service.result
    assert service.calls == [
        ("export_refit_recipe", ("shadow", str(destination.resolve()), "Coat fit"), {})
    ]


@pytest.mark.parametrize("internal_root", ["session", "profiles"])
def test_recipe_export_rejects_internal_destinations(
    authoring_session, tmp_path, internal_root,
):
    authoring_session.authoritative_morph_root = (tmp_path / "profiles").resolve()
    root = (
        authoring_session.root if internal_root == "session"
        else authoring_session.authoritative_morph_root
    )

    with pytest.raises(RustMeshValidationError, match="outside the internal"):
        authoring_session._run_morph_command(
            "morph_export_recipe", {"path": str(root / "saved-fit.json")}
        )

    assert authoring_session.shadow_service.calls == []


@pytest.mark.parametrize(
    "command",
    [
        "morph_capture_baseline",
        "morph_set_influence",
        "morph_clear_influence",
        "morph_set_driver_region",
    ],
)
def test_selection_commands_resolve_current_service_selection(authoring_session, command):
    service = authoring_session.shadow_service
    first_selection = service.live_selection
    stale_client_selection = {"vertices": [999]}
    authoring_session._run_morph_command(command, {"selection": stale_client_selection})
    service.live_selection = object()
    authoring_session._run_morph_command(command, {"selection": stale_client_selection})

    assert service.selection_reads == [first_selection, service.live_selection]
    assert all(call[2]["selection"] is None for call in service.calls)


@pytest.mark.parametrize(
    "invalid",
    [None, True, 1, 1.5, "1", {1}, {"part": 1}, [True], [1.0], [-1], [1, 1]],
)
def test_target_parser_rejects_ambiguous_or_broadened_scopes(invalid):
    with pytest.raises(RustMeshValidationError):
        bridge._morph_target_indices({"garment_submesh_indices": invalid})


def test_target_parser_preserves_explicit_order_and_omitted_selection():
    assert bridge._morph_target_indices({}) == ()
    assert bridge._morph_target_indices({"garment_submesh_indices": [4, 0]}) == (4, 0)
    assert bridge._morph_target_indices({"submesh_indices": (2, 0)}, "submesh_indices") == (2, 0)


@pytest.mark.parametrize(
    ("command", "key"),
    [
        ("morph_capture_baseline", "submesh_indices"),
        ("morph_begin_correction", "garment_submesh_indices"),
        ("morph_set_influence", "garment_submesh_indices"),
        ("morph_clear_influence", "garment_submesh_indices"),
        ("morph_set_driver_region", "garment_submesh_indices"),
        ("morph_clear_driver_region", "garment_submesh_indices"),
        ("morph_import_recipe", "garment_submesh_indices"),
    ],
)
@pytest.mark.parametrize("invalid", [[True], [1, 1]])
def test_invalid_targets_never_reach_service(authoring_session, command, key, invalid):
    service = authoring_session.shadow_service
    original_state = service.state
    with pytest.raises(RustMeshValidationError):
        authoring_session._run_morph_command(
            command, {key: invalid, "definition_id": "waist", "path": "saved-fit.json"}
        )

    assert service.calls == []
    assert service.state is original_state


@pytest.mark.parametrize(
    "definition",
    [
        None,
        [],
        "waist",
        {**_DEFINITION, "authored_fields": [{"deltas": [[100, 0, 0]]}]},
        {**_DEFINITION, "selection": {"vertices": [0]}},
        {**_DEFINITION, "base_geometry_fingerprint": "0" * 64},
    ],
)
def test_authored_capture_accepts_metadata_only(authoring_session, definition):
    with pytest.raises(RustMeshValidationError):
        authoring_session._run_morph_command(
            "morph_capture_authored", {"definition": definition}
        )
    assert authoring_session.shadow_service.calls == []


@pytest.mark.parametrize("command", ["morph_set_value", "morph_bake", "morph_save_setup", "morph_apply_setup"])
def test_correction_comparison_refuses_editing_but_allows_restore(authoring_session, command):
    service = authoring_session.shadow_service
    service._morph_sessions = {"shadow": SimpleNamespace(corrections_enabled=False)}
    with pytest.raises(RustMeshValidationError, match="corrections back on"):
        authoring_session._run_morph_command(command, {})
    assert service.calls == []
    assert authoring_session._run_morph_command(
        "morph_set_corrections_enabled", {"enabled": True},
    ) is service.result
    assert service.calls == [("set_morph_corrections_enabled", ("shadow", True), {})]


@pytest.mark.parametrize("operation", ["finish", "apply_candidate"])
def test_correction_comparison_refuses_publication_and_viewport_candidates(authoring_session, operation, monkeypatch):
    service = authoring_session.shadow_service
    service._morph_sessions = {"shadow": SimpleNamespace(corrections_enabled=False)}

    def unexpected_prepare(*args, **kwargs):
        pytest.fail("Correction comparison reached geometry preparation or publication")

    monkeypatch.setattr(RustMeshAuthoringSession, "_prepare_finish_mesh", unexpected_prepare)
    monkeypatch.setattr(RustMeshAuthoringSession, "_prepare_finish_profile_publication", unexpected_prepare)
    request = {
        "event": "finish_request", "protocol": bridge.RUST_MESH_EDITOR_PROTOCOL,
        "session_id": authoring_session.session_id, "request_id": 1,
        "base_revision": 7, "process_generation": authoring_session.process_generation,
    }
    with pytest.raises(RustMeshValidationError, match="corrections back on"):
        getattr(authoring_session, operation)(request)
    assert service.calls == []


def _pending_state(phase: str) -> MeshMorphState:
    if phase == "baseline":
        return MeshMorphState(
            authoring_baseline_ready=True,
            authoring_driver_submesh_indices=(0,),
        )
    return MeshMorphState(
        correction_definition_id="waist",
        correction_garment_submesh_indices=(1,),
    )


@pytest.mark.parametrize("phase", ["baseline", "correction"])
@pytest.mark.parametrize(
    "command",
    [
        "morph_activate",
        "morph_set_value",
        "morph_apply_preset",
        "morph_reset",
        "morph_bake",
        "refit_bind",
        "refit_configure",
        "refit_island_configure",
        "refit_fit_to_body",
        "morph_set_influence",
        "morph_set_driver_region",
        "morph_import_recipe",
        "morph_export_recipe",
    ],
)
def test_pending_authoring_refuses_unrelated_morph_mutations(
    authoring_session, phase, command,
):
    service = authoring_session.shadow_service
    service.state = _pending_state(phase)
    original_state = service.state

    with pytest.raises(RustMeshValidationError, match="before changing Morph"):
        authoring_session._run_morph_command(command, {})

    assert service.calls == []
    assert service.state is original_state


@pytest.mark.parametrize(
    ("phase", "command", "arguments", "method"),
    [
        ("baseline", "morph_capture_baseline", {}, "capture_morph_baseline"),
        ("baseline", "morph_capture_authored", {"definition": _DEFINITION},
         "capture_authored_morph_definition"),
        ("baseline", "morph_cancel_baseline", {}, "cancel_morph_baseline"),
        ("correction", "morph_save_correction", {}, "save_morph_correction"),
        ("correction", "morph_cancel_correction", {}, "cancel_morph_correction"),
    ],
)
def test_pending_authoring_can_be_completed_or_cancelled(
    authoring_session, phase, command, arguments, method,
):
    service = authoring_session.shadow_service
    service.state = _pending_state(phase)

    assert authoring_session._run_morph_command(command, arguments) is service.result
    assert [call[0] for call in service.calls] == [method]


@pytest.mark.parametrize("phase", ["baseline", "correction"])
def test_finish_refuses_pending_authoring_before_preparing_or_publishing(
    authoring_session, phase, monkeypatch,
):
    service = authoring_session.shadow_service
    service.state = _pending_state(phase)
    original_state = service.state
    original_files = tuple(authoring_session.root.iterdir())

    def unexpected_prepare(*args, **kwargs):
        pytest.fail("Pending authoring reached Finish preparation or publication")

    monkeypatch.setattr(RustMeshAuthoringSession, "_prepare_finish_mesh", unexpected_prepare)
    monkeypatch.setattr(
        RustMeshAuthoringSession, "_prepare_finish_profile_publication", unexpected_prepare,
    )
    request = {
        "event": "finish_request",
        "protocol": bridge.RUST_MESH_EDITOR_PROTOCOL,
        "session_id": authoring_session.session_id,
        "request_id": 1,
        "base_revision": 7,
        "process_generation": authoring_session.process_generation,
    }

    with pytest.raises(RustMeshValidationError, match="or finishing"):
        authoring_session.finish(request)

    assert service.calls == []
    assert service.state is original_state
    assert not authoring_session._commit_started
    assert not authoring_session._finish_accepted
    assert not authoring_session.closed
    assert tuple(authoring_session.root.iterdir()) == original_files


def _large_authored_state(vertex_count: int) -> MeshMorphState:
    indices = tuple(range(vertex_count))
    definition = MeshMorphDefinition(
        definition_id="waist",
        label="Sculpted waist",
        category="Authored",
        vertices=tuple(MeshMorphVertexWeight(0, index) for index in indices),
        pivot=(0.0, 0.0, 0.0),
        local_basis=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        rule=MeshMorphRule("move", amount=0.0),
        source_kind="authored",
        authored_fields=(
            MeshMorphSparseField("waist", 0, indices, ((0.25, 0.0, 0.0),) * vertex_count),
        ),
        base_geometry_fingerprint="1" * 64,
        garment_corrections=(
            MeshMorphSparseField("waist", 1, indices, ((0.0, 0.1, 0.0),) * vertex_count),
        ),
        correction_topology_fingerprint="2" * 64,
        correction_base_geometry_fingerprint="3" * 64,
    )
    return MeshMorphState(
        definitions=(definition,),
        authoring_baseline_ready=True,
        authoring_driver_submesh_indices=(0,),
        refit=MeshRefitBindingSummary(
            driver_submesh_indices=(0,),
            garment_submesh_indices=(1,),
            garment_settings=(
                MeshRefitGarmentSettings(
                    1, mode="surface",
                    vertex_mask=tuple((index, 0.5) for index in indices),
                ),
            ),
            garment_regions=((1, (MeshRefitDriverRegion(0, indices),)),),
        ),
    )


def test_ui_state_omits_large_authored_arrays_but_keeps_counts_and_workflow_metadata():
    small_payload = bridge._json_safe(_large_authored_state(3))
    payload = bridge._json_safe(_large_authored_state(8192))
    definition = payload["definitions"][0]
    settings = payload["refit"]["garment_settings"][0]
    region = payload["refit"]["garment_regions"][0][1][0]

    assert {"vertices", "authored_fields", "garment_corrections"}.isdisjoint(definition)
    assert definition["definition_id"] == "waist"
    assert definition["source_kind"] == "authored"
    assert definition["authored_vertex_count"] == 8192
    assert definition["correction_vertex_count"] == 8192
    assert "vertex_mask" not in settings
    assert settings["has_vertex_mask"] is True
    assert settings["mode"] == "surface"
    assert region == {"submesh_index": 0, "vertex_count": 8192}
    assert payload["authoring_baseline_ready"] is True
    assert payload["authoring_driver_submesh_indices"] == [0]
    assert len(json.dumps(payload)) < 4000
    assert len(json.dumps(payload)) - len(json.dumps(small_payload)) < 40


@pytest.mark.parametrize(("mask", "expected"), [(None, False), ((), True), (((1, 0.5),), True)])
def test_ui_state_distinguishes_no_mask_from_protect_all(mask, expected):
    payload = bridge._json_safe(MeshRefitGarmentSettings(1, vertex_mask=mask))
    assert payload["has_vertex_mask"] is expected
    assert "vertex_mask" not in payload


def test_procedural_definition_uses_shared_atomic_service_and_retains_response(authoring_session):
    service = authoring_session.shadow_service
    profile, activation = object(), object()
    service.result = (profile, activation)
    result = authoring_session._run_morph_command("morph_create", {"definition": _DEFINITION})
    assert result == {"profile": profile, "activation": activation}
    assert service.calls == [("author_morph_definition", ("shadow",), _DEFINITION)]
