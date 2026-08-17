"""The capability matrix has to refuse with a reason, never guess.

The limits it describes are enforced elsewhere; what is pinned here is that
asking ahead of time gives the same answer the writer would, and that every
refusal names something a reader can act on rather than only saying no.
"""

from __future__ import annotations

import pytest

from cdmw.domain.mesh.authoring_capability import (
    AUTHORABLE_MESH_FORMATS,
    AuthoringSupport,
    action_authoring_capability,
    capability_matrix,
    geometry_authoring_capability,
    normalize_mesh_format,
    topology_authoring_capability,
)
from cdmw.domain.mesh.topology import (
    TOPOLOGY_OPERATION_BY_NATIVE_ACTION,
    TOPOLOGY_OPERATION_DELETE_FACES,
    TOPOLOGY_OPERATION_LOOP_CUT,
    TOPOLOGY_OPERATION_SUBDIVIDE_MIDPOINT,
    TOPOLOGY_REBUILDABLE_OPERATIONS,
)


@pytest.mark.parametrize("value", ["pac", "PAC", ".pac", "  pac  ", ".PAC"])
def test_format_normalization_accepts_the_shapes_a_path_supplies(value: str) -> None:
    assert normalize_mesh_format(value) == "pac"


@pytest.mark.parametrize("mesh_format", sorted(AUTHORABLE_MESH_FORMATS))
def test_lod0_geometry_is_exact_for_every_authorable_format(mesh_format: str) -> None:
    capability = geometry_authoring_capability(mesh_format, lod_index=0)
    assert capability.support is AuthoringSupport.EXACT
    assert capability.authorable


def test_meshinfo_is_read_only_and_says_so() -> None:
    capability = geometry_authoring_capability("meshinfo")

    assert capability.support is AuthoringSupport.READ_ONLY
    assert not capability.authorable
    assert "read-only" in capability.reason
    assert capability.detail


@pytest.mark.parametrize("mesh_format", ["fbx", "obj", "", None, "unknown"])
def test_an_unsupported_format_is_blocked_with_a_reason(mesh_format: object) -> None:
    capability = geometry_authoring_capability(mesh_format)

    assert capability.support is AuthoringSupport.BLOCKED
    assert not capability.authorable
    assert capability.reason


@pytest.mark.parametrize("lod_index", [1, 2, 3])
def test_lod1_and_above_are_unproven_rather_than_silently_allowed(lod_index: int) -> None:
    capability = geometry_authoring_capability("pac", lod_index=lod_index)

    assert capability.support is AuthoringSupport.UNPROVEN
    assert not capability.authorable
    assert "LOD1" in capability.reason


def test_face_deletion_is_exact_because_it_derives_no_vertices() -> None:
    capability = topology_authoring_capability(
        "pac",
        topology_operation=TOPOLOGY_OPERATION_DELETE_FACES,
    )
    assert capability.support is AuthoringSupport.EXACT
    assert capability.authorable


@pytest.mark.parametrize(
    "operation",
    [TOPOLOGY_OPERATION_LOOP_CUT, TOPOLOGY_OPERATION_SUBDIVIDE_MIDPOINT],
)
def test_vertex_deriving_operations_are_unproven_with_the_measured_reason(
    operation: str,
) -> None:
    capability = topology_authoring_capability("pac", topology_operation=operation)

    assert capability.support is AuthoringSupport.UNPROVEN
    assert not capability.authorable
    assert "protected byte" in capability.reason
    # The reason has to be the measured limit, not a restated rule.
    assert "0.0072%" in capability.detail


def test_every_rebuildable_topology_operation_has_an_answer() -> None:
    for operation in TOPOLOGY_REBUILDABLE_OPERATIONS:
        capability = topology_authoring_capability("pac", topology_operation=operation)
        assert capability.support is not AuthoringSupport.BLOCKED


def test_a_geometry_only_edit_is_answered_by_format_and_lod_alone() -> None:
    assert topology_authoring_capability("pac", topology_operation=None).authorable
    assert not topology_authoring_capability("meshinfo", topology_operation=None).authorable
    assert not topology_authoring_capability("pac", lod_index=1, topology_operation=None).authorable


def test_the_format_gate_outranks_the_operation() -> None:
    """A format that cannot be written makes every operation moot."""
    capability = topology_authoring_capability(
        "meshinfo",
        topology_operation=TOPOLOGY_OPERATION_DELETE_FACES,
    )
    assert capability.support is AuthoringSupport.READ_ONLY


def test_an_unrecognised_topology_operation_is_blocked_not_allowed() -> None:
    capability = topology_authoring_capability("pac", topology_operation="teleport_topology")

    assert capability.support is AuthoringSupport.BLOCKED
    assert "teleport_topology" in capability.reason


@pytest.mark.parametrize(
    "action_key",
    ["edge_split", "bridge", "extrude", "inset", "merge", "weld", "fill", "copy", "paste", "layer_delete"],
)
def test_the_hidden_topology_actions_all_have_a_stated_reason(action_key: str) -> None:
    """These are hidden in the UI today, which reads as unfinished, not blocked."""
    capability = action_authoring_capability(action_key)

    assert capability is not None
    assert capability.support is AuthoringSupport.BLOCKED
    assert capability.reason
    assert capability.detail


@pytest.mark.parametrize("action_key", ["loop_cut", "subdivide"])
def test_vertex_deriving_actions_report_their_limit(action_key: str) -> None:
    capability = action_authoring_capability(action_key)

    assert capability is not None
    assert not capability.authorable
    assert action_key in TOPOLOGY_OPERATION_BY_NATIVE_ACTION


def test_an_action_with_no_authoring_limit_reports_none() -> None:
    # None means "no limit of its own", not "always available": selection and
    # session state still gate it.
    for action_key in ("delete", "transform_move", "select_parts", "", None):
        assert action_authoring_capability(action_key) is None


def test_the_matrix_covers_geometry_operations_and_blocked_actions() -> None:
    matrix = capability_matrix("pac", lod_index=0)

    assert matrix["format"] == "pac"
    assert matrix["lod_index"] == 0
    assert matrix["geometry"]["support"] == "exact"
    assert set(matrix["topology_operations"]) == set(TOPOLOGY_REBUILDABLE_OPERATIONS)
    assert matrix["topology_operations"][TOPOLOGY_OPERATION_DELETE_FACES]["authorable"] is True
    assert matrix["topology_operations"][TOPOLOGY_OPERATION_LOOP_CUT]["authorable"] is False
    assert "extrude" in matrix["blocked_actions"]
    assert all(
        not entry["authorable"] and entry["reason"]
        for entry in matrix["blocked_actions"].values()
    )


def test_the_matrix_reports_a_read_only_format_before_any_operation() -> None:
    matrix = capability_matrix("meshinfo")

    assert matrix["geometry"]["support"] == "read_only"
    # Every operation inherits the format's refusal rather than claiming support.
    assert all(
        entry["support"] == "read_only"
        for entry in matrix["topology_operations"].values()
    )
