"""Bounded attachment payload and placement-context worker operations."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from cdmw.core.archive import read_archive_entry_data
from cdmw.core.common import read_file_bytes_cancellable
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry, AssetFamilyGraph, AttachmentPlacementEvidence


ATTACHMENT_PAYLOAD_MAX_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class AttachmentPayloadReadRequest:
    archive_entry: ArchiveEntry | None = None
    file_path: Path | None = None
    max_bytes: int = ATTACHMENT_PAYLOAD_MAX_BYTES
    request_id: int = 0


@dataclass(frozen=True, slots=True)
class AttachmentPayloadReadResult:
    request_id: int
    source_path: str
    data: bytes
    archive_entry: ArchiveEntry | None = None


@dataclass(frozen=True, slots=True)
class AttachmentContextRequest:
    target_graph: AssetFamilyGraph
    target_evidence: AttachmentPlacementEvidence | None
    target_model_entry: ArchiveEntry | None
    target_socket_entry: ArchiveEntry | None
    donor_graph: AssetFamilyGraph | None = None
    donor_evidence: AttachmentPlacementEvidence | None = None
    donor_model_entry: ArchiveEntry | None = None
    donor_socket_entry: ArchiveEntry | None = None
    extra_roots: tuple[Path, ...] = ()
    request_id: int = 0


@dataclass(frozen=True, slots=True)
class AttachmentContextResult:
    request_id: int
    target: Mapping[str, object]
    donor: Mapping[str, object]


def run_attachment_payload_read(
    request: AttachmentPayloadReadRequest,
    *,
    stop_event: threading.Event | None = None,
) -> AttachmentPayloadReadResult:
    raise_if_cancelled(stop_event, "Attachment payload read cancelled.")
    limit = max(1, int(request.max_bytes))
    entry = request.archive_entry
    if isinstance(entry, ArchiveEntry):
        declared_size = max(int(entry.orig_size or 0), int(entry.comp_size or 0))
        if declared_size > limit:
            raise ValueError(f"Attachment payload exceeds the {limit:,}-byte safety limit: {entry.path}")
        data, _decompressed, _note = read_archive_entry_data(entry)
        source_path = entry.path
    elif isinstance(request.file_path, Path):
        path = request.file_path.expanduser()
        data = read_file_bytes_cancellable(path, stop_event=stop_event, max_bytes=limit)
        source_path = str(path)
    else:
        raise ValueError("Attachment payload request has no source.")
    raise_if_cancelled(stop_event, "Attachment payload read cancelled.")
    if len(data) > limit:
        raise ValueError(f"Attachment payload exceeds the {limit:,}-byte safety limit: {source_path}")
    return AttachmentPayloadReadResult(int(request.request_id), source_path, bytes(data), entry)


def run_attachment_context_resolution(
    request: AttachmentContextRequest,
    *,
    resolver: Callable[..., Mapping[str, object]],
    stop_event: threading.Event | None = None,
) -> AttachmentContextResult:
    raise_if_cancelled(stop_event, "Attachment context resolution cancelled.")
    target = resolver(
        request.target_graph,
        request.target_evidence,
        request.target_model_entry,
        socket_entry=request.target_socket_entry,
        extra_roots=request.extra_roots,
        stop_event=stop_event,
    )
    raise_if_cancelled(stop_event, "Attachment context resolution cancelled.")
    donor: Mapping[str, object] = {}
    if isinstance(request.donor_graph, AssetFamilyGraph):
        donor = resolver(
            request.donor_graph,
            request.donor_evidence,
            request.donor_model_entry,
            socket_entry=request.donor_socket_entry,
            extra_roots=request.extra_roots,
            stop_event=stop_event,
        )
    raise_if_cancelled(stop_event, "Attachment context resolution cancelled.")
    return AttachmentContextResult(
        int(request.request_id),
        MappingProxyType(dict(target or {})),
        MappingProxyType(dict(donor or {})),
    )


__all__ = [
    "ATTACHMENT_PAYLOAD_MAX_BYTES",
    "AttachmentContextRequest",
    "AttachmentContextResult",
    "AttachmentPayloadReadRequest",
    "AttachmentPayloadReadResult",
    "run_attachment_context_resolution",
    "run_attachment_payload_read",
]
