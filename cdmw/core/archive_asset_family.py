from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    AssetFamilyGraph,
    AssetFamilyMember,
    AssetRelation,
    AttachmentPlacementEvidence,
    AttachmentSocketDocument,
    AttachmentSocketInfo,
    AttachmentStackEquipInfo,
    RelationConfidence,
    RelationKind,
)
from cdmw.core.common import raise_if_cancelled
from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import _is_material_sidecar_extension
from cdmw.core.archive_binary_preview import (
    _binary_sidecar_schema_declarations,
    _extract_binary_asset_references,
    _extract_binary_string_records,
    _extract_text_asset_references,
    build_archive_related_file_references,
    try_decode_text_like_archive_data,
)
from cdmw.core.archive_model_references import (
    _ARCHIVE_TEXTURE_FAMILY_SUFFIXES,
    _find_archive_model_related_entries,
    _normalize_model_texture_reference,
    _relation_kind_for_entry,
    _score_model_related_entry_candidate,
)
from cdmw.core.table_catalog import table_field_label
from cdmw.core.upscale_profiles import derive_texture_group_key, normalize_texture_reference_for_sidecar_lookup


def _archive_core():
    from cdmw.core import archive as archive_core

    return archive_core


def _archive_path_is_probable_item_icon(*args, **kwargs):
    return _archive_core()._archive_path_is_probable_item_icon(*args, **kwargs)


def _asset_family_group_order(*args, **kwargs):
    return _archive_core()._asset_family_group_order(*args, **kwargs)


def _attachment_asset_reference_re():
    return _archive_core()._ATTACHMENT_ASSET_REFERENCE_RE


def _attachment_prefab_field_names():
    return _archive_core()._ATTACHMENT_PREFAB_FIELD_NAMES


def _attachment_character_socket_priority():
    return _archive_core()._ATTACHMENT_CHARACTER_SOCKET_PRIORITY


def _attachment_weapon_socket_priority():
    return _archive_core()._ATTACHMENT_WEAPON_SOCKET_PRIORITY


def parse_socket_bone_data_xml(*args, **kwargs):
    return _archive_core().parse_socket_bone_data_xml(*args, **kwargs)

def _asset_family_group_for_entry(
    entry: Optional[ArchiveEntry],
    *,
    relation_group: str = "",
    reference_name: str = "",
) -> str:
    path_text = str(getattr(entry, "path", "") or reference_name).replace("\\", "/").strip()
    basename = PurePosixPath(path_text).name.lower()
    extension = str(getattr(entry, "extension", "") or PurePosixPath(path_text).suffix).strip().lower()
    lowered = " ".join((relation_group, path_text, basename, extension)).casefold()
    if "item icon" in lowered or relation_group == "Item Icons" or _archive_path_is_probable_item_icon(path_text):
        return "Item Icons"
    if "socket" in basename or basename.endswith(".sockets.xml"):
        return "Attachment / Placement"
    if _is_material_sidecar_extension(extension, basename) or "material sidecar" in lowered:
        return "Material"
    if extension == ".pamhc":
        return "Material"
    if extension in {".dds", ".seqmt"} or "texture" in lowered:
        return "Textures"
    if extension in {".hkx", ".hkt"} or "physics" in lowered or "ragdoll" in lowered or "meshphysics" in lowered:
        return "Physics / HKX"
    if extension == ".meshinfo":
        return "MeshInfo"
    if extension in {".prefab", ".prefabdata_xml", ".app_xml", ".pappt"} or "prefab" in lowered:
        return "Prefab / Metadata"
    if extension in {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh", ".papr"} or "skeleton" in lowered or "rig" in lowered:
        return "Skeleton / Rig"
    if extension in {".paa", ".paa_metabin", ".pae", ".paem", ".motionblending", ".paseq", ".paschedule", ".paschedulepath", ".pastage"}:
        return "Animation / Motion"
    if extension in {".pac", ".pam", ".pamlod"}:
        return "Selected Model"
    return "Other"


def _asset_family_role_for_entry(entry: Optional[ArchiveEntry], *, relation_kind: str = "", relation_group: str = "") -> str:
    extension = str(getattr(entry, "extension", "") or "").strip().lower()
    kind = str(relation_kind or "").strip().lower()
    group = str(relation_group or "").strip().casefold()
    basename = str(getattr(entry, "basename", "") or "").casefold()
    if kind == "item_icon" or "item icon" in group or _archive_path_is_probable_item_icon(str(getattr(entry, "path", "") or "")):
        return "Inventory Icon"
    if "socket" in basename or "socket" in group:
        return "Socket XML"
    if extension in {".pac", ".pam", ".pamlod"} or kind in {RelationKind.MESH.value, RelationKind.LOD.value}:
        return "Model"
    if _is_material_sidecar_extension(extension, str(getattr(entry, "basename", "") or "").lower()) or kind == RelationKind.MATERIAL_SIDECAR.value:
        return "Material Sidecar"
    if extension == ".pamhc":
        return "Model Property Header"
    if extension in {".dds", ".seqmt"} or kind == RelationKind.TEXTURE.value:
        return "Texture"
    if extension in {".hkx", ".hkt"} or kind == "physics" or "physics" in group:
        return "HKX / Physics"
    if extension == ".meshinfo":
        return "MeshInfo"
    if extension in {".prefab", ".prefabdata_xml", ".app_xml", ".pappt"}:
        return "Prefab / Metadata"
    if extension in {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh", ".papr"} or kind == RelationKind.SKELETON.value:
        return "Skeleton / Rig"
    if extension in {".paa", ".paa_metabin", ".pae", ".paem", ".motionblending", ".paseq", ".paschedule", ".paschedulepath", ".pastage"} or kind == RelationKind.ANIMATION.value:
        return "Animation / Motion"
    return "Related File"


def _asset_family_status_for_reference(reference: ArchiveModelTextureReference) -> str:
    status = str(getattr(reference, "resolution_status", "") or "").strip().lower()
    if status == "resolved":
        return "Resolved"
    if status == "technical_only":
        return "Context"
    return "Missing"


def _asset_family_storage_warning(reference: ArchiveModelTextureReference) -> str:
    resolved_entry = getattr(reference, "resolved_entry", None)
    if (
        isinstance(resolved_entry, ArchiveEntry)
        and resolved_entry.extension == ".dds"
        and resolved_entry.compression_type == 1
    ):
        return "Archive texture uses Partial DDS storage; the family relationship itself is resolved."
    return ""


def _asset_family_evidence_chip(
    *,
    confidence: str = "",
    relation_group: str = "",
    reason: str = "",
    role_hint: str = "",
    status: str = "",
) -> str:
    normalized_confidence = str(confidence or "").strip().lower()
    lowered = " ".join((relation_group, reason, role_hint)).casefold()
    if str(status or "").casefold() == "missing":
        return "Missing"
    if "item_finder" in normalized_confidence or "item finder" in lowered:
        return "Item Finder"
    if "table" in normalized_confidence or "table" in lowered or "iteminfo." in lowered:
        return "Table"
    if "material" in lowered or "sidecar" in lowered:
        return "Sidecar"
    if "prefab" in lowered:
        return "Prefab"
    if normalized_confidence in {RelationConfidence.AUTHORITATIVE.value, RelationConfidence.EXACT_PATH.value}:
        return "Exact"
    if normalized_confidence in {RelationConfidence.PATH_NORMALIZED.value, RelationConfidence.CROSS_PACKAGE.value}:
        return "Path hint"
    if normalized_confidence == RelationConfidence.DERIVED_SAME_STEM.value:
        return "Same stem"
    if normalized_confidence == RelationConfidence.DERIVED_FAMILY_HEURISTIC.value:
        return "Name hint"
    return normalized_confidence.replace("_", " ").title() if normalized_confidence else "Name hint"


def _asset_family_include_policy(group: str, status: str, evidence: str) -> str:
    if group == "Selected Model":
        return "required"
    if str(status or "").casefold() not in {"resolved", "context"}:
        return "unresolved"
    if evidence in {"Exact", "Sidecar"}:
        return "required"
    if evidence == "Table":
        return "recommended"
    if group == "Item Icons" and evidence == "Item Finder":
        return "recommended"
    if group in {"Material", "Textures"} and evidence in {"Path hint", "Same stem"}:
        return "required"
    return "manual"


def _asset_family_expected_missing_rows(source_entry: ArchiveEntry, present_groups: set[str]) -> Tuple[AssetFamilyMember, ...]:
    extension = str(source_entry.extension or "").strip().lower()
    if extension not in {".pac", ".pam", ".pamlod"}:
        return ()
    source_path = source_entry.path.replace("\\", "/").strip()
    source_posix = PurePosixPath(source_path)
    source_stem = source_posix.stem
    source_parent = source_posix.parent.as_posix()

    def candidate_path(group: str) -> str:
        if group == "Material":
            if extension == ".pac":
                material_parent = source_parent.replace("/model/", "/modelproperty/")
                return f"{material_parent}/{source_stem}.pac_xml"
            if extension == ".pam":
                return f"{source_parent}/{source_stem}.pami"
            if extension == ".pamlod":
                return f"{source_parent}/{source_stem}.pamlod_xml"
        if group == "MeshInfo":
            return f"{source_parent}/{source_stem}.meshinfo"
        if group == "Physics / HKX":
            return f"{source_parent}/{source_stem}.hkx"
        if group == "Prefab / Metadata":
            return f"{source_parent}/{source_stem}.prefab"
        return source_path

    rows: List[AssetFamilyMember] = []
    for group, role, reason in (
        ("Material", "Material Sidecar", "No same-family material sidecar was resolved from the current archive index."),
        ("MeshInfo", "MeshInfo", "No same-family .meshinfo metadata was resolved from the current archive index."),
        ("Physics / HKX", "HKX / Physics", "No same-family HKX physics/animation file was resolved from the current archive index."),
        ("Prefab / Metadata", "Prefab / Metadata", "No same-family prefab or metadata file was resolved from the current archive index."),
    ):
        if group in present_groups:
            continue
        path_text = candidate_path(group)
        rows.append(
            AssetFamilyMember(
                group=group,
                role=role,
                display_name=PurePosixPath(path_text).name,
                path=path_text,
                status="Missing",
                confidence="Missing",
                source_evidence="Missing",
                include_policy="unresolved",
                reason=reason,
                warning="Not found in current index.",
            )
        )
    return tuple(rows)


def _asset_family_summary(member_rows: Sequence[AssetFamilyMember]) -> str:
    if not member_rows:
        return ""
    rows_by_group: Dict[str, List[AssetFamilyMember]] = defaultdict(list)
    for row in member_rows:
        rows_by_group[row.group].append(row)

    parts: List[str] = []
    source_rows = rows_by_group.get("Selected Model", ())
    if source_rows:
        parts.append("Model OK")

    def add_count(group: str, singular: str, plural: str, *, missing_label: str = "", hint_label: str = "") -> None:
        rows = rows_by_group.get(group, ())
        resolved_rows = [row for row in rows if str(row.status).casefold() in {"resolved", "partial", "context", "selected", "model ok"}]
        missing_rows = [row for row in rows if str(row.status).casefold() == "missing"]
        hint_rows = [
            row for row in resolved_rows
            if str(row.include_policy or "").casefold() not in {"required", "recommended"}
            or str(row.source_evidence or "").casefold() in {"same stem", "name hint", "path hint"}
        ]
        if resolved_rows:
            label = singular if len(resolved_rows) == 1 else plural
            if hint_rows and hint_label:
                parts.append(f"{label} hint")
            else:
                parts.append(f"{len(resolved_rows):,} {label}")
        elif missing_rows and missing_label:
            parts.append(missing_label)

    add_count("Material", "material", "materials", missing_label="material missing")
    add_count("Textures", "texture", "textures", missing_label="textures missing")
    add_count("Item Icons", "item icon", "item icons", hint_label="item icon")
    add_count("Physics / HKX", "HKX", "HKX", missing_label="HKX missing", hint_label="HKX")
    add_count("MeshInfo", "meshinfo", "meshinfo", missing_label="meshinfo missing", hint_label="meshinfo")
    add_count("Prefab / Metadata", "prefab", "prefabs", missing_label="prefab missing", hint_label="prefab")
    add_count("Skeleton / Rig", "skeleton", "skeletons", hint_label="skeleton")
    add_count("Animation / Motion", "animation", "animations", hint_label="animation")
    add_count("Attachment / Placement", "placement chain", "placement chains", hint_label="placement")
    return " | ".join(parts)


def _attachment_paths_from_string_records(string_records: Sequence[object]) -> Tuple[str, ...]:
    paths: List[str] = []
    seen: set[str] = set()
    for record in tuple(string_records or ()):
        text = str(getattr(record, "text", "") or "").strip().replace("\\", "/")
        if not text:
            continue
        for match in _attachment_asset_reference_re().finditer(text):
            raw_path = str(match.group(1) or "").strip().replace("\\", "/")
            if not raw_path:
                continue
            normalized = _normalize_model_texture_reference(raw_path)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            paths.append(raw_path)
    return tuple(paths)


def _choose_attachment_socket_name(names: Sequence[str], priority: Sequence[str], *, child: bool) -> str:
    cleaned = [
        str(name or "").strip()
        for name in names
        if str(name or "").strip() and not str(name or "").strip().startswith("_")
    ]
    if not cleaned:
        return ""
    name_set = {name.casefold(): name for name in cleaned}
    for candidate in priority:
        resolved = name_set.get(candidate.casefold())
        if resolved:
            return resolved
    if child:
        for name in cleaned:
            lowered = name.casefold()
            if "childsocket" in lowered or "pivot_socket" in lowered:
                return name
    else:
        for name in cleaned:
            lowered = name.casefold()
            if (
                "socket" in lowered
                and "childsocket" not in lowered
                and "pivot_socket" not in lowered
                and "inspectsocket" not in lowered
                and "trail" not in lowered
            ):
                return name
    return ""


def _path_with_extension(paths: Sequence[str], extensions: set[str], *, contains: str = "") -> str:
    contains_lower = contains.casefold()
    for path_text in tuple(paths or ()):
        normalized = str(path_text or "").replace("\\", "/").strip()
        if not normalized:
            continue
        suffix = PurePosixPath(normalized).suffix.lower()
        lowered = normalized.casefold()
        if suffix in extensions and (not contains_lower or contains_lower in lowered):
            return normalized
    return ""


def _attachment_prefab_evidence_from_entry(prefab_entry: ArchiveEntry) -> Tuple[AttachmentPlacementEvidence, ...]:
    try:
        data, _decompressed, _note = read_archive_entry_data(prefab_entry)
    except Exception:
        return ()
    try:
        string_records = _extract_binary_string_records(data, sample_limit=262_144, max_strings=512)
    except Exception:
        string_records = []
    texts = [str(getattr(record, "text", "") or "").strip() for record in string_records]
    paths = list(_attachment_paths_from_string_records(string_records))
    declared_fields: List[str] = []
    try:
        schema = _binary_sidecar_schema_declarations(data, ".prefab")
        for row in tuple(schema.get("declared_member_rows", ()) if isinstance(schema, Mapping) else ()):
            if not isinstance(row, Mapping):
                continue
            name = str(row.get("name") or "").strip()
            if name in _attachment_prefab_field_names() and name not in declared_fields:
                declared_fields.append(name)
    except Exception:
        pass
    socket_names = [text for text in texts if "Socket" in text and "/" not in text and "." not in text]
    attached_socket = _choose_attachment_socket_name(
        socket_names,
        _attachment_character_socket_priority(),
        child=False,
    )
    pivot_socket = _choose_attachment_socket_name(
        socket_names,
        _attachment_weapon_socket_priority(),
        child=True,
    )
    model_path = _path_with_extension(paths, {".pac", ".pam", ".pamlod"})
    socket_file_path = _path_with_extension(paths, {".xml"}, contains="sockets")
    skeleton_path = _path_with_extension(paths, {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh"}, contains="skeleton")

    if not any((attached_socket, pivot_socket, model_path, socket_file_path, skeleton_path, declared_fields)):
        return ()
    if attached_socket and pivot_socket and socket_file_path:
        confidence = "Exact prefab/socket"
        evidence = "Prefab"
        reason = (
            f"{prefab_entry.basename} declares attachment socket {attached_socket} and weapon pivot {pivot_socket}; "
            "socket XML gives the child-side transform when resolved."
        )
    elif attached_socket or pivot_socket or socket_file_path:
        confidence = "Socket XML only" if socket_file_path and not (attached_socket and pivot_socket) else "Prefab socket hint"
        evidence = "Socket XML" if socket_file_path else "Prefab"
        reason = f"{prefab_entry.basename} contains socket placement fields, but the full character -> weapon chain is incomplete."
    else:
        confidence = "Path hint"
        evidence = "Prefab"
        reason = f"{prefab_entry.basename} contains attachment-related prefab fields; no socket names were recovered."
    placement_modes = ["Raw Model Origin"]
    if attached_socket:
        placement_modes.append("Character Socket")
    if pivot_socket:
        placement_modes.append("Weapon Pivot")
    if attached_socket and pivot_socket:
        placement_modes.append("Final Attachment")
    return (
        AttachmentPlacementEvidence(
            source_path=prefab_entry.path,
            source_kind="prefab",
            prefab_path=prefab_entry.path,
            character_socket_name=attached_socket,
            weapon_socket_name=pivot_socket,
            model_path=model_path,
            socket_file_path=socket_file_path,
            skeleton_path=skeleton_path,
            transform_fields=tuple(declared_fields),
            confidence=confidence,
            evidence=evidence,
            reason=reason,
            placement_modes=tuple(placement_modes),
        ),
    )


def _socket_document_from_entry(entry: ArchiveEntry) -> Optional[AttachmentSocketDocument]:
    basename = PurePosixPath(entry.path.replace("\\", "/")).name.casefold()
    if "socket" not in basename and not basename.endswith(".sockets.xml"):
        return None
    try:
        data, _decompressed, _note = read_archive_entry_data(entry)
    except Exception:
        return None
    text = data.decode("utf-8-sig", errors="ignore")
    document = parse_socket_bone_data_xml(text, source_path=entry.path)
    if not document.sockets and not document.stack_equip_infos:
        return None
    return document


def _socket_document_evidence_from_entry(entry: ArchiveEntry, document: AttachmentSocketDocument) -> AttachmentPlacementEvidence:
    preferred_stack = next(
        (
            stack
            for stack in document.stack_equip_infos
            if str(stack.equip_type_name or "").casefold() in {"back", "pelvis_l", "pelvis_r", "right_hand", "left_hand"}
        ),
        document.stack_equip_infos[0] if document.stack_equip_infos else AttachmentStackEquipInfo(source_path=entry.path),
    )
    first_socket_name = preferred_stack.socket_names[0] if preferred_stack.socket_names else (
        document.sockets[0].name if document.sockets else ""
    )
    return AttachmentPlacementEvidence(
        source_path=entry.path,
        source_kind="socket_xml",
        character_socket_name=first_socket_name if preferred_stack.equip_type_name else "",
        socket_file_path=entry.path,
        confidence="Socket XML only",
        evidence="Socket XML",
        reason=(
            f"{entry.basename} defines {len(document.sockets):,} socket(s)"
            + (f" and StackEquipInfo {preferred_stack.equip_type_name}." if preferred_stack.equip_type_name else ".")
        ),
        placement_modes=("Raw Model Origin", "Character Socket") if first_socket_name else ("Raw Model Origin",),
    )


def _find_socket_info(
    documents: Sequence[AttachmentSocketDocument],
    socket_name: str,
    *,
    preferred_path: str = "",
) -> Optional[AttachmentSocketInfo]:
    normalized_preferred = _normalize_model_texture_reference(preferred_path)
    fallback: Optional[AttachmentSocketInfo] = None
    for document in tuple(documents or ()):
        for socket in tuple(getattr(document, "sockets", ()) or ()):
            if socket.name.casefold() != str(socket_name or "").casefold():
                continue
            if normalized_preferred and _normalize_model_texture_reference(socket.source_path) == normalized_preferred:
                return socket
            if fallback is None:
                fallback = socket
    return fallback


def _enrich_attachment_evidence_with_socket_documents(
    evidence: AttachmentPlacementEvidence,
    documents: Sequence[AttachmentSocketDocument],
) -> AttachmentPlacementEvidence:
    character_socket = _find_socket_info(documents, evidence.character_socket_name)
    weapon_socket = _find_socket_info(documents, evidence.weapon_socket_name, preferred_path=evidence.socket_file_path)
    if character_socket is None and weapon_socket is None:
        return evidence
    return replace(
        evidence,
        character_socket_parent=character_socket.parent if character_socket is not None else evidence.character_socket_parent,
        character_socket_translation=character_socket.translation if character_socket is not None else evidence.character_socket_translation,
        character_socket_rotation=character_socket.rotation if character_socket is not None else evidence.character_socket_rotation,
        weapon_socket_parent=weapon_socket.parent if weapon_socket is not None else evidence.weapon_socket_parent,
        weapon_socket_translation=weapon_socket.translation if weapon_socket is not None else evidence.weapon_socket_translation,
        weapon_socket_rotation=weapon_socket.rotation if weapon_socket is not None else evidence.weapon_socket_rotation,
    )


def _asset_family_attachment_evidence(source_entry: ArchiveEntry, member_rows: Sequence[AssetFamilyMember]) -> Tuple[AttachmentPlacementEvidence, ...]:
    entries: List[ArchiveEntry] = [source_entry]
    for row in tuple(member_rows or ()):
        entry = getattr(row, "resolved_entry", None)
        if isinstance(entry, ArchiveEntry) and entry not in entries:
            entries.append(entry)

    socket_documents: List[AttachmentSocketDocument] = []
    prefab_evidence: List[AttachmentPlacementEvidence] = []
    socket_only_evidence: List[AttachmentPlacementEvidence] = []
    for entry in entries:
        extension = str(entry.extension or "").lower()
        if extension in {".prefab", ".pappt"}:
            prefab_evidence.extend(_attachment_prefab_evidence_from_entry(entry))
        document = _socket_document_from_entry(entry)
        if document is not None:
            socket_documents.append(document)
            socket_only_evidence.append(_socket_document_evidence_from_entry(entry, document))

    enriched = [
        _enrich_attachment_evidence_with_socket_documents(evidence, socket_documents)
        for evidence in prefab_evidence
    ]
    if enriched:
        return tuple(enriched)
    return tuple(socket_only_evidence[:4])


def _attachment_evidence_display_name(evidence: AttachmentPlacementEvidence) -> str:
    character_socket = str(evidence.character_socket_name or "").strip()
    weapon_socket = str(evidence.weapon_socket_name or "").strip()
    model_name = PurePosixPath(str(evidence.model_path or evidence.prefab_path or evidence.socket_file_path or "").replace("\\", "/")).name
    if character_socket and weapon_socket:
        return f"{character_socket} -> {weapon_socket}"
    if character_socket:
        return character_socket
    if weapon_socket:
        return weapon_socket
    return model_name or "Attachment placement"


def build_archive_asset_family_graph(
    source_entry: ArchiveEntry,
    references: Sequence[ArchiveModelTextureReference],
) -> AssetFamilyGraph:
    grouped_paths: Dict[str, List[str]] = defaultdict(list)
    relations: List[AssetRelation] = []
    member_rows: List[AssetFamilyMember] = []
    member_paths: List[str] = []
    seen_members: set[str] = set()
    seen_member_rows: set[Tuple[str, str, str]] = set()

    def add_member(raw_value: str) -> None:
        normalized = str(raw_value or "").strip().replace("\\", "/")
        if not normalized or normalized in seen_members:
            return
        seen_members.add(normalized)
        member_paths.append(normalized)

    def add_member_row(row: AssetFamilyMember) -> None:
        key = (row.group, row.path.replace("\\", "/").casefold(), row.display_name.casefold())
        if key in seen_member_rows:
            return
        seen_member_rows.add(key)
        member_rows.append(row)

    add_member(source_entry.path)
    source_group = "Selected Model" if source_entry.extension in {".pac", ".pam", ".pamlod"} else _asset_family_group_for_entry(source_entry)
    add_member_row(
        AssetFamilyMember(
            group=source_group,
            role=_asset_family_role_for_entry(source_entry),
            display_name=source_entry.basename,
            path=source_entry.path,
            status="Model OK" if source_group == "Selected Model" else "Selected",
            confidence="Exact",
            source_evidence="Selected",
            include_policy="required",
            reason="The file currently selected in Archive Browser.",
            resolved_entry=source_entry,
        )
    )

    for reference in references:
        relation_group = str(getattr(reference, "relation_group", "") or "").strip() or "Metadata / Other"
        target_path = str(getattr(reference, "resolved_archive_path", "") or "").strip()
        if not target_path:
            target_path = str(getattr(reference, "reference_name", "") or "").strip().replace("\\", "/")
        if not target_path:
            continue
        resolved_entry = getattr(reference, "resolved_entry", None)
        if not isinstance(resolved_entry, ArchiveEntry):
            resolved_entry = None
        add_member(target_path)
        family_group = _asset_family_group_for_entry(
            resolved_entry,
            relation_group=relation_group,
            reference_name=target_path,
        )
        if target_path not in grouped_paths[family_group]:
            grouped_paths[family_group].append(target_path)
        status = _asset_family_status_for_reference(reference)
        confidence = str(getattr(reference, "relation_confidence", "") or RelationConfidence.DERIVED_SAME_STEM.value)
        role_hint = str(getattr(reference, "semantic_hint", "") or "").strip()
        reason = str(getattr(reference, "relation_reason", "") or "").strip()
        source_table = str(getattr(reference, "source_table", "") or "").strip()
        source_field = str(getattr(reference, "source_field", "") or "").strip()
        field_label = table_field_label(source_table, source_field)
        if field_label and field_label not in reason:
            reason = f"{reason} ({field_label})" if reason else f"Referenced by {field_label}"
        evidence = _asset_family_evidence_chip(
            confidence=confidence,
            relation_group=relation_group,
            reason=reason,
            role_hint=role_hint,
            status=status,
        )
        include_policy = _asset_family_include_policy(family_group, status, evidence)
        storage_warning = _asset_family_storage_warning(reference)
        warning = storage_warning or (
            "Weak relationship hint; review before treating as required." if include_policy == "manual" else ""
        )
        relation_kind = str(getattr(reference, "reference_kind", "") or _relation_kind_for_entry(resolved_entry))
        display_name = (
            PurePosixPath(resolved_entry.path.replace("\\", "/")).name
            if isinstance(resolved_entry, ArchiveEntry)
            else PurePosixPath(target_path.replace("\\", "/")).name
        )
        add_member_row(
            AssetFamilyMember(
                group=family_group,
                role=_asset_family_role_for_entry(
                    resolved_entry,
                    relation_kind=relation_kind,
                    relation_group=relation_group,
                ),
                display_name=display_name,
                path=target_path,
                status=status,
                confidence=evidence,
                source_evidence=evidence,
                include_policy=include_policy,
                reason=reason or "Recovered relationship evidence from the current archive index.",
                warning=warning,
                resolved_entry=resolved_entry,
                source_table=source_table,
                source_field=source_field,
            )
        )
        relations.append(
            AssetRelation(
                source_path=source_entry.path,
                target_path=target_path,
                relation_kind=relation_kind,
                confidence=confidence,
                role_label=str(getattr(reference, "semantic_label", "") or "").strip(),
                status=status,
                source_evidence=evidence,
                include_policy=include_policy,
                warning=warning,
                reason=reason,
                source_entry=source_entry,
                target_entry=resolved_entry,
                semantic_label=str(getattr(reference, "semantic_label", "") or "").strip(),
                semantic_hint=str(getattr(reference, "semantic_hint", "") or "").strip(),
                sidecar_parameter_name=str(getattr(reference, "sidecar_parameter_name", "") or "").strip(),
                material_name=str(getattr(reference, "material_name", "") or "").strip(),
                package_label=str(getattr(reference, "resolved_package_label", "") or "").strip(),
                source_table=source_table,
                source_field=source_field,
            )
        )
    present_groups = {row.group for row in member_rows if str(row.status).casefold() != "missing"}
    for row in _asset_family_expected_missing_rows(source_entry, present_groups):
        add_member_row(row)
        if row.path and row.path not in grouped_paths[row.group]:
            grouped_paths[row.group].append(row.path)

    attachment_evidence = _asset_family_attachment_evidence(source_entry, member_rows)
    for evidence in attachment_evidence:
        for evidence_path in (evidence.prefab_path, evidence.socket_file_path, evidence.skeleton_path, evidence.model_path):
            if evidence_path:
                add_member(evidence_path)
        display_name = _attachment_evidence_display_name(evidence)
        status = "Context" if str(evidence.confidence or "").casefold() != "no placement chain" else "Missing"
        reason = evidence.reason or "Recovered attachment placement evidence. Placement writes are not enabled from this view."
        row = AssetFamilyMember(
            group="Attachment / Placement",
            role="Socket Chain",
            display_name=display_name,
            path=evidence.prefab_path or evidence.socket_file_path or source_entry.path,
            status=status,
            confidence=evidence.confidence,
            source_evidence=evidence.evidence,
            include_policy="manual",
            reason=reason,
            warning="Read-only placement evidence; XML/binary placement writes remain gated.",
            resolved_entry=None,
        )
        add_member_row(row)
        if row.path and row.path not in grouped_paths[row.group]:
            grouped_paths[row.group].append(row.path)

    order_index = {group: index for index, group in enumerate(_asset_family_group_order())}
    member_rows.sort(
        key=lambda row: (
            order_index.get(row.group, 99),
            1 if str(row.status).casefold() == "missing" else 0,
            row.display_name.casefold(),
        )
    )
    return AssetFamilyGraph(
        root_path=source_entry.path,
        family_key=PurePosixPath(source_entry.path.replace("\\", "/")).stem,
        members=tuple(member_paths),
        member_rows=tuple(member_rows),
        relations=tuple(relations),
        attachment_evidence=tuple(attachment_evidence),
        grouped_paths={key: tuple(value) for key, value in grouped_paths.items()},
        summary=_asset_family_summary(member_rows),
    )


def _find_archive_texture_family_entries(
    source_entry: ArchiveEntry,
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]],
) -> Tuple[ArchiveEntry, ...]:
    if archive_entries_by_normalized_path is None:
        return ()
    extension = str(source_entry.extension or "").strip().lower()
    normalized_path = normalize_texture_reference_for_sidecar_lookup(source_entry.path)
    if extension != ".dds" or not normalized_path:
        return ()

    group_key = derive_texture_group_key(normalized_path)
    if not group_key:
        return ()
    if "/" in group_key:
        folder, family = group_key.rsplit("/", 1)
    else:
        folder, family = "", group_key
    if not family:
        return ()

    candidates: List[ArchiveEntry] = []
    seen_paths: set[str] = set()
    source_normalized = _normalize_model_texture_reference(source_entry.path)
    for suffix in _ARCHIVE_TEXTURE_FAMILY_SUFFIXES:
        candidate_path = f"{folder}/{family}{suffix}.dds" if folder else f"{family}{suffix}.dds"
        normalized_candidate_path = _normalize_model_texture_reference(candidate_path)
        for candidate in archive_entries_by_normalized_path.get(normalized_candidate_path, ()):
            normalized_candidate = _normalize_model_texture_reference(candidate.path)
            if normalized_candidate in seen_paths or normalized_candidate == source_normalized:
                continue
            seen_paths.add(normalized_candidate)
            candidates.append(candidate)

    if not candidates:
        return ()
    candidates.sort(key=lambda candidate: _score_model_related_entry_candidate(source_entry, candidate), reverse=True)
    return tuple(candidates[:16])


def _find_archive_texture_referencing_sidecar_entries(
    source_entry: ArchiveEntry,
    *,
    sidecar_entries_by_texture_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_entries_by_texture_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveEntry, ...]:
    normalized_path = normalize_texture_reference_for_sidecar_lookup(source_entry.path)
    if not normalized_path:
        return ()
    basename = PurePosixPath(normalized_path).name
    candidates: List[ArchiveEntry] = []
    seen_paths: set[str] = set()

    def add_candidate(entry: ArchiveEntry) -> None:
        normalized_candidate = _normalize_model_texture_reference(entry.path)
        if not normalized_candidate or normalized_candidate == _normalize_model_texture_reference(source_entry.path):
            return
        if normalized_candidate in seen_paths:
            return
        seen_paths.add(normalized_candidate)
        candidates.append(entry)

    if sidecar_entries_by_texture_path is not None:
        for candidate in sidecar_entries_by_texture_path.get(normalized_path, ()):
            add_candidate(candidate)
    if sidecar_entries_by_texture_basename is not None and basename:
        for candidate in sidecar_entries_by_texture_basename.get(basename, ()):
            add_candidate(candidate)
    return tuple(candidates)


def _collect_archive_texture_sidecar_texts_from_entries(
    sidecar_entries: Sequence[ArchiveEntry],
    *,
    limit: int = 6,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[str, ...]:
    texts: List[str] = []
    seen_texts: set[str] = set()
    for sidecar_entry in sidecar_entries:
        raise_if_cancelled(stop_event)
        try:
            raw_data, _decompressed, _note = read_archive_entry_data(sidecar_entry, stop_event=stop_event)
        except Exception:
            continue
        text = str(try_decode_text_like_archive_data(raw_data) or "").strip()
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        texts.append(text)
        if len(texts) >= limit:
            break
    return tuple(texts)


def build_archive_entry_related_references(
    source_entry: ArchiveEntry,
    *,
    text: str = "",
    binary_data: bytes = b"",
    explicit_reference_names: Sequence[str] = (),
    companion_entries: Sequence[ArchiveEntry] = (),
    archive_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_entries_by_texture_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_entries_by_texture_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[ArchiveModelTextureReference, ...]:
    combined_reference_names: List[str] = []
    seen_reference_names: set[str] = set()

    def add_reference_name(raw_value: str) -> None:
        normalized = _normalize_model_texture_reference(raw_value)
        if not normalized or normalized in seen_reference_names:
            return
        seen_reference_names.add(normalized)
        combined_reference_names.append(str(raw_value or "").strip().replace("\\", "/"))

    for reference_name in explicit_reference_names:
        add_reference_name(reference_name)
    if text:
        for reference_name in _extract_text_asset_references(text, sidecar_path=source_entry.path):
            add_reference_name(reference_name)
    elif binary_data:
        for reference_name in _extract_binary_asset_references(binary_data, sample_limit=262_144, max_references=64):
            add_reference_name(reference_name)

    combined_companion_entries: List[ArchiveEntry] = []
    seen_companion_paths: set[str] = set()

    def add_companion_entry(candidate: ArchiveEntry) -> None:
        normalized_candidate = _normalize_model_texture_reference(candidate.path)
        if not normalized_candidate or normalized_candidate == _normalize_model_texture_reference(source_entry.path):
            return
        if normalized_candidate in seen_companion_paths:
            return
        seen_companion_paths.add(normalized_candidate)
        combined_companion_entries.append(candidate)

    for candidate in companion_entries:
        add_companion_entry(candidate)
    for candidate in _find_archive_model_related_entries(source_entry, archive_entries_by_basename):
        add_companion_entry(candidate)
    for candidate in _find_archive_texture_family_entries(source_entry, archive_entries_by_normalized_path):
        add_companion_entry(candidate)
    if str(source_entry.extension or "").strip().lower() == ".dds":
        for candidate in _find_archive_texture_referencing_sidecar_entries(
            source_entry,
            sidecar_entries_by_texture_path=sidecar_entries_by_texture_path,
            sidecar_entries_by_texture_basename=sidecar_entries_by_texture_basename,
        ):
            add_companion_entry(candidate)
            for related_candidate in _find_archive_model_related_entries(candidate, archive_entries_by_basename):
                add_companion_entry(related_candidate)

    return build_archive_related_file_references(
        source_entry,
        explicit_reference_names=combined_reference_names,
        companion_entries=combined_companion_entries,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        archive_entries_by_basename=archive_entries_by_basename,
    )
