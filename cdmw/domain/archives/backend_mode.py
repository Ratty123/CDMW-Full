"""Session selection for the full archive catalogue backend."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from typing import Mapping


ARCHIVE_BACKEND_ENV = "CDMW_ARCHIVE_BACKEND"


class ArchiveBackendMode(str, Enum):
    """Rollout modes for the standalone full archive backend."""

    LEGACY = "legacy"
    V2 = "v2"
    SHADOW = "shadow"


@dataclass(frozen=True, slots=True)
class ArchiveBackendSelection:
    """Resolved mode plus enough evidence for a diagnostic warning."""

    mode: ArchiveBackendMode
    configured_value: str
    valid: bool

    @property
    def displays_v2(self) -> bool:
        return self.mode is ArchiveBackendMode.V2

    @property
    def runs_shadow(self) -> bool:
        return self.mode is ArchiveBackendMode.SHADOW


def resolve_archive_backend_mode(
    environment: Mapping[str, str] | None = None,
) -> ArchiveBackendSelection:
    """Resolve the developer override, defaulting the stable rollout to v2."""

    source = os.environ if environment is None else environment
    configured = str(source.get(ARCHIVE_BACKEND_ENV, "") or "").strip().lower()
    if not configured:
        return ArchiveBackendSelection(ArchiveBackendMode.V2, "", True)
    try:
        return ArchiveBackendSelection(ArchiveBackendMode(configured), configured, True)
    except ValueError:
        return ArchiveBackendSelection(ArchiveBackendMode.V2, configured, False)


__all__ = [
    "ARCHIVE_BACKEND_ENV",
    "ArchiveBackendMode",
    "ArchiveBackendSelection",
    "resolve_archive_backend_mode",
]
