from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.domain.mesh import MeshEditSelection
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from tests.test_mesh_editor_action_bar import _EmbeddedMeshBuilder


ROOT = Path(__file__).resolve().parents[1]
_APP = QApplication.instance() or QApplication([])


def _embedded_tab(name: str) -> tuple[MeshEditorTab, _EmbeddedMeshBuilder]:
    settings = QSettings("CDMWTests", name)
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    return tab, builder


def test_bootstrap_ready_remains_accepted_after_mutation_capability_negotiation() -> None:
    tab, builder = _embedded_tab("MeshEditorBootstrapCorrelation")

    assert tab._handle_dotnet_protocol_event(
        {"event": "protocol_ready", "capabilities": ["resident_mutation_envelope_v2"]}
    )
    assert tab._handle_dotnet_protocol_event(
        {
            "event": "textures_ready",
            "renderer": {
                "backend": "d3d11_vortice_shader",
                "gpu_backed": True,
                "renderer_blocked": False,
            },
        }
    )
    assert tab._handle_dotnet_protocol_event(
        {
            "event": "ready",
            "renderer": {
                "backend": "d3d11_vortice_shader",
                "gpu_backed": True,
                "renderer_blocked": False,
            },
        }
    )

    assert getattr(builder, "_mesh_editor_embedded_dotnet_active", False)
    assert getattr(builder, "_mesh_editor_embedded_dotnet_state", "") == "ready"
    tab.deleteLater()
    _APP.processEvents()


def test_bootstrap_ready_does_not_reverify_provenance_after_protocol_ready() -> None:
    tab, builder = _embedded_tab("MeshEditorBootstrapProvenanceOnce")
    verified_events: list[str] = []

    def verify(payload: dict[str, object]) -> bool:
        verified_events.append(str(payload.get("event", "")))
        tab.standalone_dotnet_provenance_verified = True
        return True

    tab._verify_dotnet_helper_provenance = verify  # type: ignore[method-assign]
    assert tab._handle_dotnet_protocol_event(
        {
            "event": "protocol_ready",
            "capabilities": ["helper_build_provenance_v1"],
        }
    )
    assert tab._handle_dotnet_protocol_event(
        {
            "event": "ready",
            "capabilities": ["helper_build_provenance_v1", "runtime_renderer_capability"],
            "renderer": {
                "backend": "d3d11_vortice_shader",
                "gpu_backed": True,
                "renderer_blocked": False,
            },
        }
    )

    assert verified_events == ["protocol_ready"]
    assert getattr(builder, "_mesh_editor_embedded_dotnet_active", False)
    tab.deleteLater()
    _APP.processEvents()


def test_v2_mutation_request_without_envelope_is_rejected() -> None:
    tab, builder = _embedded_tab("MeshEditorMutationCorrelation")
    assert tab._handle_dotnet_protocol_event(
        {"event": "protocol_ready", "capabilities": ["resident_mutation_envelope_v2"]}
    )

    assert not tab._handle_dotnet_protocol_event(
        {
            "event": "selection_request",
            "local_selection": {"vertices_by_submesh": {"0": [0]}},
        }
    )
    assert builder.controller.session_view().selection == MeshEditSelection()
    tab.deleteLater()
    _APP.processEvents()


def test_v2_texture_region_ack_with_envelope_remains_observable() -> None:
    tab, builder = _embedded_tab("MeshEditorTextureRegionCorrelation")
    tab.standalone_dotnet_process_generation = 5
    assert tab._handle_dotnet_protocol_event(
        {"event": "protocol_ready", "capabilities": ["resident_mutation_envelope_v2"]}
    )
    acknowledgement = {
        "event": "texture_region_applied",
        "session_id": builder.controller.active_session_id,
        "request_id": 3,
        "base_revision": builder.controller.session_view().revision,
        "process_generation": 5,
        "protocol_version": 2,
        "resource_id": "texture:body",
        "generation": 1,
    }

    assert tab._handle_dotnet_protocol_event(acknowledgement)
    assert acknowledgement in tab.standalone_dotnet_protocol_events
    tab.deleteLater()
    _APP.processEvents()


def test_save_request_is_declared_as_a_correlated_helper_mutation() -> None:
    output = (
        ROOT / "tools" / "dotnet_mesh_editor_experiment" / "ExperimentForm.Output.cs"
    ).read_text(encoding="utf-8")

    correlated = output.split("private static bool IsMutatingProtocolRequest", maxsplit=1)[1]
    assert '"save_request" => true' in correlated
