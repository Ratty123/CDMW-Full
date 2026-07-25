"""Native procedural morph field generation must match the Python exactly.

The C++ port exists because Python spends ~950 ms generating the fields for a
145-slider body against ~11 ms native. Both will coexist while the payload
transport is sorted out, so they have to agree vertex for vertex — these assert
that for every rule kind, not just the common ones.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from cdmw.domain.mesh import (
    MESH_MORPH_RULES,
    MeshMorphDefinition,
    MeshMorphRule,
    build_weighted_morph_selection,
    generate_procedural_morph_fields,
    procedural_morph_pivot,
)
from cdmw.modding import mesh_native_core

from tests.test_native_mesh_editor_morph_refit import _driver_garment_mesh


def _require_native() -> None:
    if not mesh_native_core.native_mesh_core_available():
        pytest.skip("native mesh core binary not available")


def _definition(mesh, rule_kind: str) -> MeshMorphDefinition:
    weighted = build_weighted_morph_selection(mesh, {0: (0, 1, 2)}, feather=0, falloff="constant")
    return MeshMorphDefinition(
        definition_id=f"{rule_kind}_probe",
        label=rule_kind.title(),
        category="Readback",
        vertices=weighted,
        pivot=procedural_morph_pivot(mesh, weighted),
        local_basis=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        rule=MeshMorphRule(rule_kind, axis="x", amount=30.0 if rule_kind == "twist" else 0.25),
    )


def _payload(definition: MeshMorphDefinition) -> dict[str, object]:
    return {
        "definition_id": definition.definition_id,
        "rule": {
            "kind": definition.rule.kind,
            "axis": definition.rule.axis,
            "amount": definition.rule.amount,
        },
        "pivot": list(definition.pivot),
        "local_basis": [list(axis) for axis in definition.local_basis],
        "vertices": [
            [vertex.submesh_index, vertex.vertex_index, vertex.weight]
            for vertex in definition.vertices
        ],
    }


def _generate(session_id: str, definitions, *, return_fields: bool = True) -> dict[str, object]:
    report = mesh_native_core.native_mesh_editor_session_command(
        "morph_generate_fields",
        session_id,
        {"definitions": [_payload(item) for item in definitions], "return_fields": return_fields},
        timeout_seconds=60.0,
    )
    assert report is not None, "native morph_generate_fields failed"
    return report


@pytest.mark.parametrize("rule_kind", MESH_MORPH_RULES)
def test_native_fields_match_python_for_every_rule(rule_kind: str) -> None:
    _require_native()
    mesh = _driver_garment_mesh()
    definition = _definition(mesh, rule_kind)
    expected = generate_procedural_morph_fields(mesh, definition)

    session_id = f"morph-fields-{uuid4().hex}"
    assert mesh_native_core.open_native_mesh_editor_session(mesh, session_id, timeout_seconds=20.0)
    try:
        fields = _generate(session_id, [definition])["fields"]
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    assert len(fields) == len(expected)
    by_key = {(item.definition_id, item.submesh_index): item for item in expected}
    for field in fields:
        reference = by_key[(field["definition_id"], int(field["submesh_index"]))]
        # Order matters: native and Python both group by submesh then sort by
        # vertex index, and the consumer relies on the pairing being positional.
        assert [int(index) for index in field["vertex_indices"]] == list(reference.vertex_indices)
        for actual, wanted in zip(field["deltas"], reference.deltas):
            for axis in range(3):
                assert float(actual[axis]) == pytest.approx(wanted[axis], abs=1e-12)


def test_native_can_skip_returning_fields_but_still_counts_them() -> None:
    """The production shape: generate natively and never ship the deltas back."""

    _require_native()
    mesh = _driver_garment_mesh()
    definitions = [_definition(mesh, kind) for kind in ("radius", "scale", "move")]
    expected = sum(
        len(field.vertex_indices)
        for definition in definitions
        for field in generate_procedural_morph_fields(mesh, definition)
    )

    session_id = f"morph-fields-{uuid4().hex}"
    assert mesh_native_core.open_native_mesh_editor_session(mesh, session_id, timeout_seconds=20.0)
    try:
        report = _generate(session_id, definitions, return_fields=False)
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)

    assert report["returned_fields"] is False
    assert report["fields"] == []
    assert int(report["definition_count"]) == len(definitions)
    assert int(report["delta_count"]) == expected


def test_native_rejects_a_definition_without_a_rule() -> None:
    _require_native()
    mesh = _driver_garment_mesh()
    session_id = f"morph-fields-{uuid4().hex}"
    assert mesh_native_core.open_native_mesh_editor_session(mesh, session_id, timeout_seconds=20.0)
    try:
        report = mesh_native_core.native_mesh_editor_session_command(
            "morph_generate_fields",
            session_id,
            {"definitions": [{"definition_id": "broken"}]},
            timeout_seconds=20.0,
        )
    finally:
        mesh_native_core.close_native_mesh_editor_session(session_id)
    # A malformed definition must fail loudly rather than yield empty fields.
    assert report is None or report.get("status") != "ok"
