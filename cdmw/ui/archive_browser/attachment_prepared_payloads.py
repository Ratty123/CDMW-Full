"""Read-through cache populated by attachment placement preparation."""

from __future__ import annotations

from cdmw.domain.mesh.session import PlacementWorkspacePreparation
from cdmw.models import ArchiveEntry, ArchiveEntryIdentity
from cdmw.workers.attachment_io_workers import (
    ATTACHMENT_PAYLOAD_MAX_BYTES,
    AttachmentPayloadReadRequest,
    run_attachment_payload_read,
)


class AttachmentPreparedPayloads:
    def __init__(self, preparation: PlacementWorkspacePreparation | None = None) -> None:
        self._payloads: dict[ArchiveEntryIdentity, bytes] = {}
        self.merge(preparation)

    def merge(self, preparation: PlacementWorkspacePreparation | None) -> None:
        if not isinstance(preparation, PlacementWorkspacePreparation):
            return
        for identity, payload in tuple(preparation.archive_payloads or ()):
            if isinstance(identity, ArchiveEntryIdentity) and isinstance(payload, bytes):
                self._payloads[identity] = payload

    def read(self, entry: ArchiveEntry | None, *, allow_io: bool) -> bytes:
        if not isinstance(entry, ArchiveEntry):
            return b""
        cached = self._payloads.get(entry.identity)
        if isinstance(cached, bytes):
            return cached
        if not allow_io:
            return b""
        try:
            return run_attachment_payload_read(
                AttachmentPayloadReadRequest(
                    archive_entry=entry,
                    max_bytes=ATTACHMENT_PAYLOAD_MAX_BYTES,
                )
            ).data
        except Exception:
            return b""


__all__ = ["AttachmentPreparedPayloads"]
