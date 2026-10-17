"""Derived resource ownership without narrowing exact-source compatibility."""
from dataclasses import asdict, replace
import json
from uuid import uuid4

import pytest

from cdmw.domain.archives.overlay_merge import OverlayConflict
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.spec import ModelSource
from cdmw.services.independent_item_install import resolve_items
from cdmw.services.independent_item_package import digest, from_plan, package_bytes
from cdmw.services.independent_item_references import audit_references
from cdmw.services.new_item_planning import ModelFiles
from tests.test_archive_overlay_manager import shop_spec
from tests.test_independent_item_compatibility import mount_mod
from tests.test_independent_item_regressions import files_in
from tests.test_independent_items import imported_game
from tests.test_new_item_service import PAC, PAC_XML, STEM, imported_pac


TEXTURE = f'character/texture/1_pc/{STEM}_d.dds'


def imported_plan(path, *, private_texture=False):
    service, snapshot = imported_game(path)
    choice = replace(shop_spec('ResourceAssessment'), model_source=ModelSource.IMPORTED)
    side_files = {PAC_XML: snapshot.payload(PAC_XML)}
    if private_texture:
        side_files[TEXTURE] = snapshot.payload(TEXTURE)
    plan = service.plan(choice, snapshot, model=ModelFiles(imported_pac(100), side_files),
                        capture_independent=True)
    return plan, snapshot


@pytest.mark.parametrize('private_texture', [False, True])
def test_graph_separates_compiled_resource_edges_from_retained_authoring_inputs(tmp_path, private_texture):
    plan, snapshot = imported_plan(tmp_path, private_texture=private_texture)
    graph = plan.reference_assessment
    assert graph.graph_complete
    rows = {row.path: row for row in graph.resources}
    outputs = {request.path: bytes(request.payload_data) for request in plan.additions}
    owned_mesh = next(path for path in outputs if path.endswith('.pac'))
    owned_xml = next(edge.target for edge in graph.edges
                     if edge.source == owned_mesh and edge.role == 'implicit-sidecar')
    assert rows[owned_mesh].ownership == rows[owned_xml].ownership == 'owned'
    assert rows[owned_mesh].source_paths == (PAC,)
    assert rows[owned_xml].source_paths == (PAC_XML,)
    assert rows[owned_mesh].reachability == ('contribution',)
    assert rows[PAC].ownership == 'borrowed' and 'authoring' in rows[PAC].reachability
    assert owned_xml in rows[owned_mesh].outgoing_references
    assert rows[owned_mesh].layout == 'verified-owned-mesh-rig'
    assert rows[owned_xml].layout == 'model-property-resource-fields'

    texture_targets = {edge.target for edge in graph.edges
                       if edge.source == owned_xml and edge.target.endswith('.dds')}
    assert TEXTURE not in texture_targets
    assert texture_targets and texture_targets <= outputs.keys()
    assert rows[TEXTURE].reachability == ('authoring',)
    assert all(rows[path].ownership == 'owned' for path in texture_targets)
    if not private_texture:
        assert all(rows[path].source_paths == (TEXTURE,) for path in texture_targets)

    for path, data in outputs.items():
        assert rows[path].sha256 == digest(data)
        assert rows[path].byte_size == len(data)
        assert rows[path].symbol == 'resource:' + path
        assert 'native lifetime unverified' in rows[path].lifetime
    package = from_plan(plan, uuid4().hex)
    assert rows[TEXTURE].sha256 == package.dependencies[TEXTURE]
    assert PAC in package.dependencies and TEXTURE in package.dependencies
    encoded = json.loads(json.dumps(asdict(graph)))
    assert len(encoded['resources']) == len(graph.resources)
    assert all(isinstance(row['sha256'], str) and len(row['sha256']) == 64 for row in encoded['resources'])
    assert any('not proven by compiler' in problem for problem in graph.unresolved)
    assert any('not proven authoring-only' in problem for problem in graph.unresolved)

    # Reversing additions changes traversal order. A target discovered first as
    # a source input must still keep its later contribution edge and role.
    reordered = audit_references(replace(plan, additions=tuple(reversed(plan.additions))), snapshot)
    assert reordered == graph


def test_unknown_borrowed_boundaries_keep_source_closure_guards(tmp_path):
    plan, _snapshot = imported_plan(tmp_path)
    graph = plan.reference_assessment
    sockets = [row for row in graph.resources if row.path.endswith('.sockets.xml')]
    assert sockets
    assert all(row.ownership == 'borrowed' and row.layout == 'unverified-borrowed-layout' for row in sockets)
    assert any(set(row.reachability) == {'authoring', 'contribution'} for row in sockets)
    assert all(any(row.path in problem and 'no supported decoder' in problem for problem in graph.unresolved)
               for row in sockets)
    assert not graph.reference_closure_complete
    assert not plan.source_revision.reference_closure_complete
    assert any('Mesh skeleton, animation' in problem for problem in graph.unresolved)


def test_graph_uses_actual_output_references_and_refuses_missing_nested_resource(tmp_path):
    plan, snapshot = imported_plan(tmp_path)
    request = next(row for row in plan.additions if row.path.endswith('.pac_xml'))
    missing = 'character/texture/cdmw_missing_nested_dependency.dds'
    original = next(edge.target for edge in plan.reference_assessment.edges
                    if edge.source == request.path and edge.target.endswith('.dds'))
    data = bytes(request.payload_data).replace(original.encode(), missing.encode())
    assert data != bytes(request.payload_data)
    changed = replace(plan, additions=tuple(replace(row, payload_data=data) if row is request else row
                                             for row in plan.additions))
    with pytest.raises(IndependentItemError, match='Unresolved item dependency: ' + missing):
        audit_references(changed, snapshot)


def test_diagnostic_edge_limit_marks_partial_without_skipping_dependency_validation(tmp_path, monkeypatch):
    from cdmw.services import independent_item_references as references

    plan, snapshot = imported_plan(tmp_path)
    monkeypatch.setattr(references, 'MAX_ASSESSMENT_EDGES', 1)
    graph = audit_references(plan, snapshot)
    assert not graph.graph_complete and len(graph.edges) == 1
    assert all('partial' in row.reachability for row in graph.resources)
    assert any('inventory limit' in problem for problem in graph.unresolved)
    assert not graph.reference_closure_complete
    assert {row.path for row in graph.resources} == {row.path for row in plan.reference_assessment.resources}

    request = next(row for row in plan.additions if row.path.endswith('.pac_xml'))
    missing = 'character/texture/cdmw_missing_after_edge_limit.dds'
    original = next(edge.target for edge in plan.reference_assessment.edges
                    if edge.source == request.path and edge.target.endswith('.dds'))
    data = bytes(request.payload_data).replace(original.encode(), missing.encode())
    changed = replace(plan, additions=tuple(replace(row, payload_data=data) if row is request else row
                                             for row in plan.additions))
    with pytest.raises(IndependentItemError, match='Unresolved item dependency: ' + missing):
        audit_references(changed, snapshot)


@pytest.mark.parametrize('private_texture', [False, True])
@pytest.mark.parametrize('target', ['archive', 'virtual'])
def test_donor_texture_edit_still_refuses_even_when_compiler_output_uses_private_bytes(tmp_path, private_texture, target):
    plan, _snapshot = imported_plan(tmp_path / 'author', private_texture=private_texture)
    package = from_plan(plan, uuid4().hex)
    _service, stock = imported_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    original = stock.payload(TEXTURE)
    changed = original[:-1] + bytes([original[-1] ^ 1])
    mount_mod(root, tmp_path / 'foreign-package', {TEXTURE: changed})
    before = files_in(root)
    with pytest.raises(OverlayConflict) as caught:
        resolve_items([package_bytes(package)], root, target=target)
    assert 'foreign' in str(caught.value) and TEXTURE in str(caught.value)
    assert 'required resource changed' in str(caught.value).lower()
    assert files_in(root) == before
