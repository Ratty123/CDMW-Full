from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cdmw.services.archive_mutation_service import ArchiveMutationService
from cdmw.services.archive_service import ArchiveService
from cdmw.services.cache_service import CacheService
from cdmw.services.diagnostics_service import DiagnosticsService
from cdmw.services.filesystem_service import FilesystemService
from cdmw.services.mesh_service import MeshService
from cdmw.services.package_service import PackageService
from cdmw.services.settings_service import SettingsService
from cdmw.services.texture_workflow_service import TextureWorkflowService


@dataclass(slots=True)
class ServiceContainer:
    settings: Any | None = None
    archives: ArchiveService | None = None
    archive_mutations: ArchiveMutationService | None = None
    textures: TextureWorkflowService | None = None
    meshes: MeshService | None = None
    packages: PackageService | None = None
    diagnostics: DiagnosticsService | None = None
    cache: CacheService | None = None
    filesystem: FilesystemService | None = None

    def bind_settings(self, settings: Any | None) -> None:
        self.settings = settings
        for service in (
            self.archives,
            self.archive_mutations,
            self.textures,
            self.meshes,
            self.packages,
            self.diagnostics,
            self.cache,
            self.filesystem,
        ):
            if service is not None:
                service.settings = settings

    @classmethod
    def create_default(cls, *, settings: Any | None = None) -> "ServiceContainer":
        return cls(
            settings=settings,
            archives=ArchiveService(settings=settings),
            archive_mutations=ArchiveMutationService(settings=settings),
            textures=TextureWorkflowService(settings=settings),
            meshes=MeshService(settings=settings),
            packages=PackageService(settings=settings),
            diagnostics=DiagnosticsService(settings=settings),
            cache=CacheService(settings=settings),
            filesystem=FilesystemService(settings=settings),
        )
