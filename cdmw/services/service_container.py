from __future__ import annotations

import threading
from dataclasses import dataclass, field
from importlib import import_module
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
    from cdmw.services.archive_mutation_service import ArchiveMutationService
    from cdmw.services.archive_service import ArchiveService
    from cdmw.services.asset_authoring_service import AssetAuthoringService
    from cdmw.services.cache_service import CacheService
    from cdmw.services.diagnostics_service import DiagnosticsService
    from cdmw.services.filesystem_service import FilesystemService
    from cdmw.services.item_icon_service import ItemIconService
    from cdmw.services.mesh_service import MeshService
    from cdmw.services.model_library_service import ModelLibraryService
    from cdmw.services.package_service import PackageService
    from cdmw.services.research_service import ResearchService
    from cdmw.services.texture_workflow_service import TextureWorkflowService


@dataclass(slots=True)
class ServiceContainer:
    _DEFAULT_SERVICE_TYPES: ClassVar[dict[str, tuple[str, str]]] = {
        "archives": ("cdmw.services.archive_service", "ArchiveService"),
        "asset_authoring": ("cdmw.services.asset_authoring_service", "AssetAuthoringService"),
        "archive_mutations": ("cdmw.services.archive_mutation_service", "ArchiveMutationService"),
        "textures": ("cdmw.services.texture_workflow_service", "TextureWorkflowService"),
        "meshes": ("cdmw.services.mesh_service", "MeshService"),
        "packages": ("cdmw.services.package_service", "PackageService"),
        "research": ("cdmw.services.research_service", "ResearchService"),
        "diagnostics": ("cdmw.services.diagnostics_service", "DiagnosticsService"),
        "cache": ("cdmw.services.cache_service", "CacheService"),
        "filesystem": ("cdmw.services.filesystem_service", "FilesystemService"),
        "item_icons": ("cdmw.services.item_icon_service", "ItemIconService"),
        "model_library": ("cdmw.services.model_library_service", "ModelLibraryService"),
    }

    settings: Any | None = None
    archives: ArchiveService | None = None
    asset_authoring: AssetAuthoringService | None = None
    archive_mutations: ArchiveMutationService | None = None
    textures: TextureWorkflowService | None = None
    meshes: MeshService | None = None
    packages: PackageService | None = None
    research: ResearchService | None = None
    diagnostics: DiagnosticsService | None = None
    cache: CacheService | None = None
    filesystem: FilesystemService | None = None
    item_icons: ItemIconService | None = None
    model_library: ModelLibraryService | None = None
    archive_catalogue: ArchiveCatalogueService | None = None
    _lazy_defaults: bool = field(default=False, repr=False)
    _lazy_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def __getattribute__(self, name: str) -> Any:
        service_types = object.__getattribute__(self, "_DEFAULT_SERVICE_TYPES")
        if name not in service_types or not object.__getattribute__(self, "_lazy_defaults"):
            return object.__getattribute__(self, name)
        value = object.__getattribute__(self, name)
        if value is not None:
            return value
        with object.__getattribute__(self, "_lazy_lock"):
            value = object.__getattribute__(self, name)
            if value is None:
                module_name, class_name = service_types[name]
                service_type = getattr(import_module(module_name), class_name)
                value = service_type(settings=object.__getattribute__(self, "settings"))
                object.__setattr__(self, name, value)
        return value

    def bind_settings(self, settings: Any | None) -> None:
        self.settings = settings
        for name in self._DEFAULT_SERVICE_TYPES:
            service = object.__getattribute__(self, name)
            if service is not None:
                service.settings = settings

    def require_archive_mutations(self) -> ArchiveMutationService:
        if self.archive_mutations is None:
            raise RuntimeError("Archive mutation service is not configured.")
        return self.archive_mutations

    def require_packages(self) -> PackageService:
        if self.packages is None:
            raise RuntimeError("Package service is not configured.")
        return self.packages

    def require_item_icons(self) -> ItemIconService:
        if self.item_icons is None:
            raise RuntimeError("Item Icon service is not configured.")
        return self.item_icons

    def require_model_library(self) -> ModelLibraryService:
        if self.model_library is None:
            raise RuntimeError("Model Library service is not configured.")
        return self.model_library

    @classmethod
    def create_default(cls, *, settings: Any | None = None) -> "ServiceContainer":
        return cls(settings=settings, _lazy_defaults=True)
