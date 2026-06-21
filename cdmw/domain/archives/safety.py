"""Archive mutation safety rules owned outside UI widgets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ArchiveMutationSafety:
    """Safety contract required before an archive mutation may run."""

    description: str
    requires_confirmation: bool = True
    requires_backup: bool = True
    recoverable: bool = True


def require_explicit_archive_mutation(description: str) -> ArchiveMutationSafety:
    """Return the default safety contract for destructive archive work."""

    return ArchiveMutationSafety(description=str(description or "archive mutation").strip())


__all__ = ["ArchiveMutationSafety", "require_explicit_archive_mutation"]
