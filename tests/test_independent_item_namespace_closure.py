"""Unwalked material resource namespaces cannot certify source closure."""
from types import SimpleNamespace

import pytest

from cdmw.services.independent_item_references import audit_references


@pytest.mark.parametrize("qualified", [False, True])
def test_namespace_resource_boundary_retains_source_carrier_guards(qualified):
    path = "character/modelproperty/owned.pac_xml"
    reference = (b'<n:ResourceReferencePath_ITexture xmlns:n="urn:unverified" '
                 b'_path="character/texture/unwalked.dds"/>') if qualified else b""
    payload = b"<ModelPropertyList>" + reference + b"</ModelPropertyList>"
    captured = []
    tracker = SimpleNamespace(record_reference_closure=captured.append,
                              capture=lambda: SimpleNamespace(payloads=()))
    snapshot = SimpleNamespace(family=lambda _key: SimpleNamespace(files=(), parts=()),
        pappt_entry=SimpleNamespace(path="character/bin__/partprefabtable.pappt"), provenance=tracker)
    plan = SimpleNamespace(spec=SimpleNamespace(template_key=1, stem=None),
        additions=(SimpleNamespace(path=path, payload_data=payload),), loose_files={}, manifest={})
    graph = audit_references(plan, snapshot)
    assert graph.reference_closure_complete is (not qualified)
    assert captured == [not qualified]
    assert any("Namespace-qualified material resource" in value for value in graph.unresolved) is qualified
    assert not any(edge.target == "character/texture/unwalked.dds" for edge in graph.edges)
