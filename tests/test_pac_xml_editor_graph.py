from __future__ import annotations

from pathlib import Path

from cdmw.domain.pac_xml_editor import parse_pac_xml_document
from cdmw.domain.pac_xml_graph import build_pac_xml_connection_graph
from cdmw.models import ArchiveEntry, AssetFamilyMember


XML = """
<SkinnedMeshMaterialWrapper _subMeshName="body">
  <Material _materialName="BodyShader">
    <MaterialParameterTexture _name="_base"><ResourceReferencePath_ITexture _path="character/texture/shared.dds" /></MaterialParameterTexture>
    <MaterialParameterTexture _name="_overlay"><ResourceReferencePath_ITexture _path="character/texture/shared.dds" /></MaterialParameterTexture>
  </Material>
</SkinnedMeshMaterialWrapper>
<SkinnedMeshMaterialWrapper _subMeshName="trim">
  <Material _materialName="TrimShader">
    <MaterialParameterTexture _name="_normal"><ResourceReferencePath_ITexture _path="character/texture/trim_n.dds" /></MaterialParameterTexture>
  </Material>
</SkinnedMeshMaterialWrapper>
"""


def _entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(path, Path("0.pamt"), Path("0.paz"), 1, 1, 1, 0, 0)


def test_graph_deduplicates_asset_nodes_but_keeps_each_labelled_parameter_edge() -> None:
    document = parse_pac_xml_document(XML)

    graph = build_pac_xml_connection_graph(document, root_path="character/modelproperty/body.pac_xml")

    assert graph.texture_path_count == 2
    assert len([node for node in graph.nodes if node.kind == "submesh"]) == 2
    assert len([node for node in graph.nodes if node.kind == "texture"]) == 2
    parameter_edges = [edge for edge in graph.edges if edge.row_id]
    assert [edge.label for edge in parameter_edges] == ["_base", "_overlay", "_normal"]
    assert len({edge.target_id for edge in parameter_edges[:2]}) == 1


def test_graph_uses_current_indexes_without_scanning_and_reports_resolution_confidence() -> None:
    document = parse_pac_xml_document(XML)
    shared = _entry("character/texture/shared.dds")
    trim = _entry("alternate/trim_n.dds")
    model = _entry("character/model/body.pac")

    graph = build_pac_xml_connection_graph(
        document,
        root_path="character/modelproperty/body.pac_xml",
        model_entries=(model,),
        archive_entries_by_normalized_path={shared.path.casefold(): (shared,)},
        archive_entries_by_basename={"trim_n.dds": (trim,)},
    )

    texture_nodes = {node.path: node for node in graph.nodes if node.kind == "texture"}
    assert next(node for node in graph.nodes if node.kind == "model").resolved_entry is model
    assert texture_nodes[shared.path].resolved_entry is shared
    assert texture_nodes[shared.path].confidence == "exact path"
    assert texture_nodes["character/texture/trim_n.dds"].resolved_entry is trim
    assert texture_nodes["character/texture/trim_n.dds"].confidence == "unique basename"
    assert graph.unresolved_path_count == 0


def test_asset_family_evidence_adds_unique_navigation_nodes() -> None:
    document = parse_pac_xml_document(XML)
    family_entry = _entry("character/assetfamily/body.asset")
    member = AssetFamilyMember(
        group="Prefab / Metadata",
        role="Asset Family",
        display_name="body.asset",
        path=family_entry.path,
        status="Resolved",
        confidence="Authoritative",
        reason="AssetFamilyGraph relationship",
        resolved_entry=family_entry,
    )

    graph = build_pac_xml_connection_graph(
        document,
        root_path="character/modelproperty/body.pac_xml",
        family_members=(member,),
    )

    family_nodes = [node for node in graph.nodes if node.kind == "asset-family"]
    assert len(family_nodes) == 1
    assert family_nodes[0].resolved_entry is family_entry
    assert family_nodes[0].evidence == "AssetFamilyGraph relationship"


def test_edited_texture_path_rebuilds_graph_from_patched_document() -> None:
    document = parse_pac_xml_document(XML)
    field = next(item for item in document.fields if item.parameter_name == "_normal")
    patched = document.render({field.row_id: "character/texture/replacement.dds"})
    patched_document = parse_pac_xml_document(patched.text)

    graph = build_pac_xml_connection_graph(
        patched_document,
        root_path="character/modelproperty/body.pac_xml",
    )

    paths = {node.path for node in graph.nodes if node.kind == "texture"}
    assert "character/texture/replacement.dds" in paths
    assert "character/texture/trim_n.dds" not in paths
    replacement_edge = next(edge for edge in graph.edges if edge.label == "_normal")
    assert replacement_edge.row_id == field.row_id


def test_graph_is_deterministic_and_exposes_index_warming_state() -> None:
    document = parse_pac_xml_document(XML)

    first = build_pac_xml_connection_graph(document, root_path="x.pac_xml", index_warming=True)
    second = build_pac_xml_connection_graph(document, root_path="x.pac_xml", index_warming=True)

    assert first == second
    assert first.index_warming
    assert all(node.status == "index warming" for node in first.nodes if node.kind == "texture")
