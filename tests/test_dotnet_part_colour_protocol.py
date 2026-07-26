"""Host authority for the resident .NET Colour tool page.

The child applies a colour edit locally for immediate feedback, so everything
it sends is a *request*. These cover the normalization that stands between an
untrusted child packet and the adjustment Build Mod later bakes, plus the
dispatch contract.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.ui.mesh_editor.tab_dotnet_part_colour import (
    MeshEditorDotNetPartColourMixin,
    normalized_part_material_edit,
)


ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = ROOT / "tools" / "dotnet_mesh_editor_experiment"


class _Host(MeshEditorDotNetPartColourMixin):
    """Minimal stand-in for the Mesh Editor tab's protocol surface."""

    def __init__(self, builder: object) -> None:
        self._builder = builder
        self.results: list[dict[str, object]] = []
        self.status: list[tuple[str, bool]] = []

    def active_builder(self) -> object:
        return self._builder

    def _send_dotnet_command_result(self, command, *, ok, status, diagnostics=(), request_payload=None):
        self.results.append(
            {
                "command": command,
                "ok": bool(ok),
                "status": status,
                "diagnostics": tuple(diagnostics),
            }
        )
        return True

    def _set_dotnet_status(self, message, *, error=False):
        self.status.append((str(message), bool(error)))


def _builder_recording(applied: bool = True):
    calls: list[dict[str, object]] = []

    def handler(edit):
        calls.append(dict(edit))
        return applied

    return SimpleNamespace(_mesh_editor_apply_dotnet_part_material_edit=handler), calls


# -- normalization ---------------------------------------------------------


def test_normalization_keeps_a_well_formed_edit():
    edit = normalized_part_material_edit(
        {
            "source_submesh_indices": [2, 0, 2],
            "colourise_rgb": [220, 30, 30],
            "colourise_strength": 0.75,
        }
    )
    assert edit == {
        "source_submesh_indices": (0, 2),
        "colourise_rgb": (220, 30, 30),
        "colourise_strength": 0.75,
    }


def test_normalization_clamps_values_from_the_child():
    edit = normalized_part_material_edit(
        {
            "source_submesh_indices": [0],
            "colourise_rgb": [999, -40, 12.6],
            "colourise_strength": 4.2,
            "emissive_strength": 900.0,
        }
    )
    assert edit["colourise_rgb"] == (255, 0, 13)
    assert edit["colourise_strength"] == pytest.approx(1.0)
    assert edit["emissive_strength"] == pytest.approx(20.0)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"source_submesh_indices": []},
        {"source_submesh_indices": [-1, -3]},
        {"source_submesh_indices": "0"},
        {"source_submesh_indices": [0]},
        {"source_submesh_indices": [0], "colourise_rgb": [1, 2]},
        {"source_submesh_indices": [0], "colourise_strength": "loud"},
        {"source_submesh_indices": [0], "colourise_strength": float("nan")},
    ],
)
def test_normalization_rejects_requests_with_nothing_safe_to_apply(payload):
    assert normalized_part_material_edit(payload) is None


def test_reset_short_circuits_every_other_field():
    edit = normalized_part_material_edit(
        {"source_submesh_indices": [1], "reset": True, "colourise_rgb": [1, 2, 3]}
    )
    assert edit == {"source_submesh_indices": (1,), "reset": True}


def test_emissive_flag_is_only_taken_as_a_real_boolean():
    assert "emissive" not in normalized_part_material_edit(
        {"source_submesh_indices": [0], "emissive": "yes", "colourise_strength": 0.5}
    )
    assert normalized_part_material_edit(
        {"source_submesh_indices": [0], "emissive": False}
    ) == {"source_submesh_indices": (0,), "emissive": False}


def test_boolean_indices_are_not_silently_treated_as_integers():
    assert normalized_part_material_edit(
        {"source_submesh_indices": [True, False], "colourise_strength": 0.5}
    ) is None


# -- dispatch --------------------------------------------------------------


def test_a_valid_request_reaches_the_builder_and_reports_applied():
    builder, calls = _builder_recording(applied=True)
    host = _Host(builder)

    assert host._handle_dotnet_part_material_edit_request(
        {"source_submesh_indices": [0], "colourise_strength": 0.5}
    )
    assert calls == [{"source_submesh_indices": (0,), "colourise_strength": 0.5}]
    assert host.results[-1]["ok"] is True
    assert host.results[-1]["status"] == "applied"


def test_a_builder_that_changes_nothing_reports_rejected():
    builder, _ = _builder_recording(applied=False)
    host = _Host(builder)

    assert not host._handle_dotnet_part_material_edit_request(
        {"source_submesh_indices": [0], "colourise_strength": 0.5}
    )
    assert host.results[-1]["status"] == "rejected"


def test_a_malformed_request_never_reaches_the_builder():
    builder, calls = _builder_recording()
    host = _Host(builder)

    assert not host._handle_dotnet_part_material_edit_request({"source_submesh_indices": []})
    assert calls == []
    assert host.results[-1]["status"] == "rejected"


def test_a_missing_builder_bridge_reports_unavailable():
    host = _Host(SimpleNamespace())

    assert not host._handle_dotnet_part_material_edit_request(
        {"source_submesh_indices": [0], "colourise_strength": 0.5}
    )
    assert host.results[-1]["status"] == "unavailable"


def test_a_raising_builder_is_contained_and_reported():
    def handler(_edit):
        raise RuntimeError("adjustment store is closed")

    host = _Host(SimpleNamespace(_mesh_editor_apply_dotnet_part_material_edit=handler))

    assert not host._handle_dotnet_part_material_edit_request(
        {"source_submesh_indices": [0], "colourise_strength": 0.5}
    )
    assert host.results[-1]["status"] == "error"
    assert "adjustment store is closed" in host.results[-1]["diagnostics"][0]
    assert host.status and host.status[-1][1] is True


# -- the .NET side of the contract ----------------------------------------


def test_the_dotnet_editor_declares_the_colour_page_and_its_request():
    """Both ends must agree on the page and the event name.

    A source check only; it cannot prove the page renders, but it does fail if
    the rail entry or the request name is renamed on one side alone.
    """
    layouts = (DOTNET_ROOT / "ExperimentForm.EditMeshLayouts.cs").read_text(encoding="utf-8")
    protocol = (DOTNET_ROOT / "ExperimentForm.ColourProtocol.cs").read_text(encoding="utf-8")
    smoke = (DOTNET_ROOT / "EditMeshLayoutSmoke.cs").read_text(encoding="utf-8")

    assert "Colour," in layouts
    assert "ToolRailPage.Colour" in layouts
    assert 'WriteProtocolEvent("part_material_edit_request"' in protocol
    assert '"Colour",' in smoke


def test_the_dotnet_editor_paces_slider_edits_instead_of_flooding_the_pipe():
    section = (DOTNET_ROOT / "ExperimentForm.ColourSection.cs").read_text(encoding="utf-8")
    protocol = (DOTNET_ROOT / "ExperimentForm.ColourProtocol.cs").read_text(encoding="utf-8")

    # One pending request, published on a timer, with the landed value flushed
    # on release. Without this a drag emits one host round trip per pixel.
    assert "PartColourAuthorityIntervalMs = 33" in section
    assert "_partRecolourStrength.MouseUp += (_, _) => FlushPartColourEdit();" in section
    assert "_pendingPartColourEdit = payload;" in protocol
