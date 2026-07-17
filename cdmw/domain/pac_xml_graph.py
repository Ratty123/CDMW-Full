"""Deterministic, navigation-only connection graph for PAC XML documents."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Mapping, Sequence

from cdmw.domain.pac_xml_editor import PacXmlDocument


@dataclass(frozen=True, slots=True)
class PacXmlGraphNode:
    node_id: str
    kind: str
    label: str
    path: str = ""
    status: str = "unresolved"
    confidence: str = ""
    evidence: str = ""
    lane: int = 0
    resolved_entry: object | None = None


@dataclass(frozen=True, slots=True)
class PacXmlGraphEdge:
    edge_id: str
    source_id: str
    target_id: str
    label: str = ""
    row_id: str = ""
    confidence: str = ""
    evidence: str = ""


@dataclass(frozen=True, slots=True)
class PacXmlConnectionGraph:
    nodes: tuple[PacXmlGraphNode, ...]
    edges: tuple[PacXmlGraphEdge, ...]
    texture_path_count: int = 0
    unresolved_path_count: int = 0
    index_warming: bool = False

    def node_by_id(self) -> dict[str, PacXmlGraphNode]:
        return {node.node_id: node for node in self.nodes}


def normalize_asset_path(path: object) -> str:
    value = str(path or "").replace("\\", "/").strip().lstrip("/")
    while "//" in value:
        value = value.replace("//", "/")
    return PurePosixPath(value).as_posix() if value else ""


def build_pac_xml_connection_graph(
    document: PacXmlDocument,
    *,
    root_path: str,
    model_paths: Sequence[str] = (),
    model_entries: Sequence[object] = (),
    archive_entries_by_normalized_path: Mapping[str, object] | None = None,
    archive_entries_by_basename: Mapping[str, Sequence[object]] | None = None,
    family_members: Sequence[object] = (),
    index_warming: bool = False,
) -> PacXmlConnectionGraph:
    """Build stable lanes without scanning or mutating any archive index."""

    normalized_root = normalize_asset_path(root_path)
    root_id = _node_id("sidecar", normalized_root or "pac-xml")
    nodes: list[PacXmlGraphNode] = [
        PacXmlGraphNode(
            node_id=root_id,
            kind="sidecar",
            label=PurePosixPath(normalized_root).name or "PAC XML",
            path=normalized_root,
            status="resolved",
            confidence="source",
            evidence="Editor source document",
            lane=1,
        )
    ]
    edges: list[PacXmlGraphEdge] = []
    node_ids = {root_id}

    model_entry_by_path = {
        normalize_asset_path(getattr(model_entry, "path", "")).casefold(): model_entry
        for model_entry in model_entries
        if normalize_asset_path(getattr(model_entry, "path", ""))
    }
    combined_model_paths = (*model_paths, *(getattr(model_entry, "path", "") for model_entry in model_entries))
    for model_path in _unique_paths(combined_model_paths):
        model_id = _node_id("model", model_path)
        nodes.append(
            PacXmlGraphNode(
                node_id=model_id,
                kind="model",
                label=PurePosixPath(model_path).name,
                path=model_path,
                status="resolved",
                confidence="paired",
                evidence="Associated model candidate",
                lane=0,
                resolved_entry=model_entry_by_path.get(model_path.casefold()),
            )
        )
        node_ids.add(model_id)
        edges.append(_edge(model_id, root_id, "material sidecar", confidence="paired"))

    group_node_ids: dict[str, str] = {}
    for field in document.fields:
        group_key = field.group_label.casefold()
        if group_key in group_node_ids:
            continue
        group_id = _node_id("submesh", f"{len(group_node_ids)}:{group_key}")
        group_node_ids[group_key] = group_id
        nodes.append(
            PacXmlGraphNode(
                node_id=group_id,
                kind="submesh",
                label=field.group_label,
                status="source",
                confidence="exact",
                evidence=f"Shader: {field.shader_name or 'unknown'}",
                lane=2,
            )
        )
        node_ids.add(group_id)
        edges.append(_edge(root_id, group_id, field.shader_name or "submesh", confidence="exact"))

    family_by_path = {
        normalize_asset_path(getattr(member, "path", "")).casefold(): member
        for member in family_members
        if normalize_asset_path(getattr(member, "path", ""))
    }
    texture_node_ids: dict[str, str] = {}
    unresolved = 0
    for field in document.fields:
        if field.kind != "texture" or not field.value:
            continue
        path = normalize_asset_path(field.value)
        path_key = path.casefold()
        asset_id = texture_node_ids.get(path_key)
        if asset_id is None:
            asset_id = _node_id("texture", path_key)
            texture_node_ids[path_key] = asset_id
            resolved_entry, confidence, evidence = _resolve_path(
                path,
                archive_entries_by_normalized_path,
                archive_entries_by_basename,
            )
            member = family_by_path.get(path_key)
            if resolved_entry is None and member is not None:
                resolved_entry = getattr(member, "resolved_entry", None)
                confidence = str(getattr(member, "confidence", "") or "family")
                evidence = str(getattr(member, "reason", "") or getattr(member, "source_evidence", "") or "Asset Family evidence")
            status = "resolved" if resolved_entry is not None else ("index warming" if index_warming else "unresolved")
            if resolved_entry is None:
                unresolved += 1
            nodes.append(
                PacXmlGraphNode(
                    node_id=asset_id,
                    kind="texture",
                    label=PurePosixPath(path).name or path,
                    path=path,
                    status=status,
                    confidence=confidence,
                    evidence=evidence,
                    lane=3,
                    resolved_entry=resolved_entry,
                )
            )
            node_ids.add(asset_id)
        edges.append(
            _edge(
                group_node_ids[field.group_label.casefold()],
                asset_id,
                field.parameter_name,
                row_id=field.row_id,
                confidence="exact XML path",
                evidence=f"Source line {field.source_line}",
            )
        )

    _append_family_nodes(
        nodes,
        edges,
        node_ids,
        family_members=family_members,
        root_id=root_id,
        normalized_root=normalized_root,
        texture_node_ids=texture_node_ids,
    )

    return PacXmlConnectionGraph(
        nodes=tuple(nodes),
        edges=tuple(edges),
        texture_path_count=len(texture_node_ids),
        unresolved_path_count=unresolved,
        index_warming=bool(index_warming),
    )


def _append_family_nodes(
    nodes: list[PacXmlGraphNode],
    edges: list[PacXmlGraphEdge],
    node_ids: set[str],
    *,
    family_members: Sequence[object],
    root_id: str,
    normalized_root: str,
    texture_node_ids: Mapping[str, str],
) -> None:
    ordered = sorted(family_members, key=lambda value: normalize_asset_path(getattr(value, "path", "")).casefold())
    for member in ordered:
        path = normalize_asset_path(getattr(member, "path", ""))
        if not path or path.casefold() == normalized_root.casefold() or path.casefold() in texture_node_ids:
            continue
        member_id = _node_id("family", path.casefold())
        if member_id in node_ids:
            continue
        resolved_entry = getattr(member, "resolved_entry", None)
        confidence = str(getattr(member, "confidence", "") or "family")
        evidence = str(getattr(member, "reason", "") or getattr(member, "source_evidence", "") or "Asset Family evidence")
        nodes.append(
            PacXmlGraphNode(
                node_id=member_id,
                kind="asset-family",
                label=str(getattr(member, "display_name", "") or PurePosixPath(path).name),
                path=path,
                status="resolved" if resolved_entry is not None else str(getattr(member, "status", "") or "unresolved").casefold(),
                confidence=confidence,
                evidence=evidence,
                lane=4,
                resolved_entry=resolved_entry,
            )
        )
        node_ids.add(member_id)
        edges.append(
            _edge(
                root_id,
                member_id,
                str(getattr(member, "role", "") or getattr(member, "group", "") or "asset family"),
                confidence=confidence,
            )
        )


def _resolve_path(
    path: str,
    normalized_index: Mapping[str, object] | None,
    basename_index: Mapping[str, Sequence[object]] | None,
) -> tuple[object | None, str, str]:
    key = path.casefold()
    if normalized_index:
        direct = normalized_index.get(key)
        if direct is None:
            direct = normalized_index.get("/" + key)
        direct_entry = _single_index_entry(direct, expected_path=key)
        if direct_entry is not None:
            return direct_entry, "exact path", "Resolved by the existing normalized-path index"
    if basename_index:
        matches = tuple(basename_index.get(PurePosixPath(path).name.casefold(), ()) or ())
        exact = tuple(match for match in matches if normalize_asset_path(getattr(match, "path", "")).casefold() == key)
        if len(exact) == 1:
            return exact[0], "exact path", "Resolved by the existing basename index"
        if len(matches) == 1:
            return matches[0], "unique basename", "Only one existing archive index candidate has this basename"
    return None, "", "No match in the currently available archive indexes"


def _single_index_entry(value: object, *, expected_path: str) -> object | None:
    if value is None:
        return None
    if hasattr(value, "path"):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        return None
    try:
        candidates = tuple(value)  # type: ignore[arg-type]
    except TypeError:
        return None
    exact = tuple(
        candidate
        for candidate in candidates
        if normalize_asset_path(getattr(candidate, "path", "")).casefold() == expected_path
    )
    if len(exact) == 1:
        return exact[0]
    return candidates[0] if len(candidates) == 1 else None


def _unique_paths(paths: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in paths:
        path = normalize_asset_path(value)
        if not path or path.casefold() in seen:
            continue
        seen.add(path.casefold())
        result.append(path)
    return tuple(result)


def _node_id(kind: str, value: str) -> str:
    digest = hashlib.sha1(f"{kind}:{value}".encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return f"{kind}:{digest}"


def _edge(
    source_id: str,
    target_id: str,
    label: str,
    *,
    row_id: str = "",
    confidence: str = "",
    evidence: str = "",
) -> PacXmlGraphEdge:
    edge_key = f"{source_id}|{target_id}|{label}|{row_id}"
    return PacXmlGraphEdge(
        edge_id=_node_id("edge", edge_key),
        source_id=source_id,
        target_id=target_id,
        label=label,
        row_id=row_id,
        confidence=confidence,
        evidence=evidence,
    )


__all__ = [
    "PacXmlConnectionGraph",
    "PacXmlGraphEdge",
    "PacXmlGraphNode",
    "build_pac_xml_connection_graph",
    "normalize_asset_path",
]
