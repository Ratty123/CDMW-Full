from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cdmw.domain.archives.mutation import ArchivePatchRequest, ArchivePatchResult
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.archives.safety import ArchiveMutationSafety, require_explicit_archive_mutation
from cdmw.models import RunCancelled


def _archive_patching():
    from cdmw.core import archive_patching

    return archive_patching


@dataclass(frozen=True, slots=True)
class ArchiveMutationPlan:
    requests: tuple[ArchivePatchRequest, ...]
    safety: ArchiveMutationSafety
    confirmed: bool = False

    @property
    def target_paths(self) -> tuple[str, ...]:
        return tuple(request.entry.path for request in self.requests)


@dataclass(slots=True)
class ArchiveMutationService:
    settings: object | None = None

    @property
    def backup_root(self) -> Path:
        return _archive_patching().ARCHIVE_PATCH_BACKUP_ROOT

    def prepare_patch(
        self,
        command: ArchivePatchRequest | Iterable[ArchivePatchRequest],
        *,
        confirmed: bool = False,
        description: str = "",
    ) -> ArchiveMutationPlan:
        requests = (command,) if isinstance(command, ArchivePatchRequest) else tuple(command)
        if not requests:
            raise ValueError("No archive modifications were provided.")
        if any(not isinstance(request, ArchivePatchRequest) for request in requests):
            raise TypeError("Archive mutation plans accept ArchivePatchRequest values only.")
        detail = str(description or f"Patch {len(requests)} archive entrie(s)").strip()
        return ArchiveMutationPlan(
            requests=requests,
            safety=require_explicit_archive_mutation(detail),
            confirmed=bool(confirmed),
        )

    def validate_patch(
        self,
        plan: ArchiveMutationPlan,
        *,
        stop_event: Optional[threading.Event] = None,
    ) -> ArchiveMutationPlan:
        plan = self._require_plan(plan)
        raise_if_cancelled(stop_event, "Archive patch cancelled before preflight.")
        papgt_path, grouped_requests = self._patch_context(plan.requests)
        _archive_patching()._preflight_archive_patch_requests(papgt_path, grouped_requests)
        raise_if_cancelled(stop_event, "Archive patch cancelled after preflight.")
        return plan

    def create_backup(
        self,
        plan: ArchiveMutationPlan,
        *,
        on_log: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Path:
        plan = self.validate_patch(plan, stop_event=stop_event)
        papgt_path, grouped_requests = self._patch_context(plan.requests)
        targets = {papgt_path}
        for pamt_path, requests in grouped_requests.items():
            targets.add(pamt_path)
            targets.update(request.entry.paz_file.resolve() for request in requests)
        # Backup publication is intentionally non-interruptible once copying starts.
        return _archive_patching()._create_backup(
            sorted(targets),
            description=plan.safety.description,
            on_log=on_log,
        )

    def apply_patch(
        self,
        plan: ArchiveMutationPlan,
        *,
        on_log: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> ArchivePatchResult:
        plan = self._require_confirmed(plan)
        raise_if_cancelled(stop_event, "Archive patch cancelled before writing game files.")
        backup_dir: Optional[Path] = None
        result: Optional[ArchivePatchResult] = None

        def guarded_log(message: str) -> None:
            nonlocal backup_dir
            text = str(message)
            if text.startswith("Backup created: "):
                backup_dir = Path(text.removeprefix("Backup created: "))
            if text.startswith("Creating archive patch backup"):
                raise_if_cancelled(stop_event, "Archive patch cancelled before backup creation.")
            # Once backup creation starts it runs to completion as a safety unit.
            if backup_dir is not None:
                raise_if_cancelled(stop_event, "Archive patch cancelled; restoring the backup.")
            if on_log is not None:
                on_log(text)

        try:
            result = _archive_patching().patch_archive_entries(plan.requests, on_log=guarded_log)
            raise_if_cancelled(stop_event, "Archive patch cancelled; restoring the backup.")
            return result
        except RunCancelled:
            rollback_dir = result.backup_dir if result is not None else backup_dir
            if rollback_dir is not None:
                _archive_patching().restore_archive_patch_backup(rollback_dir, on_log=on_log)
            raise
        except Exception:
            if backup_dir is not None:
                _archive_patching().restore_archive_patch_backup(backup_dir, on_log=on_log)
            raise

    def list_backups(self, *, limit: Optional[int] = None) -> list[Path]:
        return _archive_patching().list_archive_patch_backups(limit=limit)

    def restore_backup(
        self,
        backup: Path | str,
        *,
        confirmed: bool = False,
        on_log: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> Path:
        if not confirmed:
            raise PermissionError("Archive backup restore requires explicit confirmation.")
        raise_if_cancelled(stop_event, "Archive backup restore cancelled before writing game files.")
        # A partial multi-file restore can break the checksum chain, so finish once started.
        return _archive_patching().restore_archive_patch_backup(Path(backup), on_log=on_log)

    @staticmethod
    def _require_plan(plan: ArchiveMutationPlan) -> ArchiveMutationPlan:
        if not isinstance(plan, ArchiveMutationPlan):
            raise TypeError("Archive mutations require an ArchiveMutationPlan.")
        return plan

    @classmethod
    def _require_confirmed(cls, plan: ArchiveMutationPlan) -> ArchiveMutationPlan:
        plan = cls._require_plan(plan)
        if plan.safety.requires_confirmation and not plan.confirmed:
            raise PermissionError("Archive patch requires explicit confirmation.")
        return plan

    @staticmethod
    def _patch_context(
        requests: tuple[ArchivePatchRequest, ...],
    ) -> tuple[Path, dict[Path, list[ArchivePatchRequest]]]:
        package_roots = {
            _archive_patching()._package_root_from_entry(request.entry).resolve()
            for request in requests
        }
        if len(package_roots) != 1:
            raise ValueError(
                "Archive patching currently requires all modified entries to come from the same package root."
            )
        papgt_path = _archive_patching()._resolve_papgt_path(requests[0].entry)
        grouped: dict[Path, list[ArchivePatchRequest]] = {}
        for request in requests:
            grouped.setdefault(request.entry.pamt_path.resolve(), []).append(request)
        return papgt_path, grouped


__all__ = [
    "ArchiveMutationPlan",
    "ArchiveMutationService",
    "ArchivePatchRequest",
    "ArchivePatchResult",
]
