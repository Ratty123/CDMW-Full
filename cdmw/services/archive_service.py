from __future__ import annotations

from dataclasses import dataclass

from cdmw.services import (
    archive_environment_service,
    archive_extraction_service,
    archive_preview_service,
    archive_query_service,
    archive_read_service,
    archive_workflow_service,
)


@dataclass(slots=True)
class ArchiveService:
    settings: object | None = None

    @property
    def reads(self):
        return archive_read_service

    @property
    def queries(self):
        return archive_query_service

    @property
    def previews(self):
        return archive_preview_service

    @property
    def extraction(self):
        return archive_extraction_service

    @property
    def environment(self):
        return archive_environment_service

    @property
    def workflows(self):
        return archive_workflow_service
