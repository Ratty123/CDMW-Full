from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings

from cdmw.app.events import AppEventBus
from cdmw.services.service_container import ServiceContainer


@dataclass(slots=True)
class AppContext:
    settings: QSettings
    services: ServiceContainer
    event_bus: AppEventBus

    @classmethod
    def from_settings(cls, settings: QSettings) -> "AppContext":
        return cls(
            settings=settings,
            services=ServiceContainer.create_default(settings=settings),
            event_bus=AppEventBus(),
        )

    @classmethod
    def create_default(cls) -> "AppContext":
        settings = QSettings("CrimsonDesertModWorkbench", "CrimsonDesertModWorkbench")
        services = ServiceContainer.create_default(settings=settings)
        return cls(settings=settings, services=services, event_bus=AppEventBus())
