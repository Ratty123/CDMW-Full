"""Pure row helpers for the attachment donor picker."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import PurePosixPath
from typing import Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidgetItem

from cdmw.models import ArchiveEntry


AttachmentDonorKey = Tuple[str, str, int]


def attachment_donor_entry_key(candidate: ArchiveEntry) -> AttachmentDonorKey:
    return (
        str(candidate.path or "").replace("\\", "/").strip().casefold(),
        str(candidate.pamt_path).strip().casefold(),
        int(candidate.offset),
    )


def attachment_donor_type(candidate: ArchiveEntry, role_label: Callable[[ArchiveEntry], str]) -> str:
    ext = str(candidate.extension or "").lower()
    path = str(candidate.path or "").replace("\\", "/").lower()
    basename = PurePosixPath(path).name
    if basename.endswith(".sockets.xml") or "socketbonedata" in path:
        return "Socket XML - socket values"
    if ext in {".pac", ".pam", ".pamlod"}:
        return "Model (.pac) - recommended"
    if ext in {".prefab", ".prefabdata_xml", ".prefabdata.xml", ".pappt"}:
        return "Prefab - direct placement"
    if ext in {".hkx", ".hkt"}:
        return "HKX - physics context"
    if ext in {".paa", ".paa_metabin", ".motionblending"}:
        return "Animation - motion companion"
    return role_label(candidate)


def attachment_donor_evidence(candidate: ArchiveEntry, target_folder: str) -> str:
    ext = str(candidate.extension or "").lower()
    path = str(candidate.path or "").replace("\\", "/").lower()
    basename = PurePosixPath(path).name
    evidence_parts: list[str] = []
    if "/weapon/" in path:
        evidence_parts.append("weapon path")
    if basename.endswith(".sockets.xml") or "socketbonedata" in path:
        evidence_parts.append("socket descriptor")
    if ext in {".prefab", ".prefabdata_xml", ".prefabdata.xml", ".pappt"}:
        evidence_parts.append("prefab placement fields")
    if ext in {".pac", ".pam", ".pamlod"}:
        evidence_parts.append("visible model")
    if ext in {".hkx", ".hkt"}:
        evidence_parts.append("HKX companion")
    if ext in {".paa", ".paa_metabin", ".motionblending"}:
        evidence_parts.append("animation companion")
    if target_folder and target_folder in path:
        evidence_parts.append("same target folder")
    return ", ".join(evidence_parts) or "possible placement family file"


def attachment_donor_haystack(
    candidate: ArchiveEntry,
    *,
    role_label: Callable[[ArchiveEntry], str],
    item_name_match: Callable[[ArchiveEntry], tuple[str, str, str]],
) -> str:
    candidate_path = str(candidate.path or "").replace("\\", "/")
    exact_name, name_hint, _name_reason = item_name_match(candidate)
    return " ".join(
        (
            PurePosixPath(candidate_path).name,
            candidate_path,
            str(candidate.package_label or ""),
            role_label(candidate),
            exact_name,
            name_hint,
        )
    ).casefold()


def attachment_donor_candidate_score(candidate: ArchiveEntry, source: str) -> int:
    ext = str(candidate.extension or "").lower()
    path = str(candidate.path or "").replace("\\", "/").casefold()
    score = 0
    if ext in {".pac", ".pam", ".pamlod"}:
        score += 180
    elif ext == ".prefab":
        score += 150
    elif ext in {".hkx", ".hkt"}:
        score += 95
    elif "socket" in path:
        score += 80
    if "/weapon/" in path:
        score += 55
    if "indexed" in source.casefold() or "item finder" in source.casefold():
        score += 25
    if "loose" in source.casefold():
        score += 35
    return score


def attachment_donor_basename_query_variants(query: str) -> tuple[str, ...]:
    normalized = str(query or "").replace("\\", "/").strip().casefold()
    basename = PurePosixPath(normalized).name
    raw_values = [value for value in (normalized, basename) if value]
    variants: list[str] = []
    for value in raw_values:
        if "." in PurePosixPath(value).name:
            variants.append(PurePosixPath(value).name)
        else:
            for extension in (".pac", ".prefab", ".hkx", ".hkt", ".pam", ".pamlod", ".paa", ".motionblending", ".sockets.xml"):
                variants.append(f"{value}{extension}")
    seen: set[str] = set()
    ordered: list[str] = []
    for value in variants:
        if value and value not in seen:
            ordered.append(value)
            seen.add(value)
    return tuple(ordered)


def attachment_donor_search_terms(query: str) -> tuple[str, ...]:
    return tuple(part.casefold() for part in str(query or "").split() if part.strip())


def make_attachment_donor_candidate_item(
    candidate: ArchiveEntry,
    *,
    donor_type: str,
    evidence_text: str,
    source: str,
) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            candidate.basename,
            donor_type,
            evidence_text,
            candidate.path,
            source,
        ]
    )
    item.setData(0, Qt.UserRole, candidate)
    item.setToolTip(0, candidate.basename)
    item.setToolTip(1, donor_type)
    item.setToolTip(2, evidence_text)
    item.setToolTip(3, candidate.path)
    item.setToolTip(4, source)
    ext = str(candidate.extension or "").lower()
    if ext in {".pac", ".pam", ".pamlod"}:
        item.setForeground(1, QBrush(QColor("#86efac")))
    elif ext == ".prefab":
        item.setForeground(1, QBrush(QColor("#67e8f9")))
    return item


__all__ = [
    "AttachmentDonorKey",
    "attachment_donor_basename_query_variants",
    "attachment_donor_candidate_score",
    "attachment_donor_entry_key",
    "attachment_donor_evidence",
    "attachment_donor_haystack",
    "attachment_donor_search_terms",
    "attachment_donor_type",
    "make_attachment_donor_candidate_item",
]
