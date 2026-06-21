from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ArchiveMutationService:
    settings: object | None = None

    def prepare_patch(self, command: object) -> object:
        raise NotImplementedError("Archive patch preparation must be wired with explicit UI confirmation.")

    def validate_patch(self, plan: object) -> object:
        raise NotImplementedError("Archive patch validation must be wired before applying mutations.")

    def create_backup(self, plan: object) -> object:
        raise NotImplementedError("Archive mutation backups must be wired before applying mutations.")

    def apply_patch(self, plan: object) -> object:
        raise NotImplementedError("Archive mutation apply must remain explicit, backed up, and recoverable.")

    def restore_backup(self, backup: object) -> object:
        raise NotImplementedError("Archive backup restore must be wired through explicit restore flow.")
