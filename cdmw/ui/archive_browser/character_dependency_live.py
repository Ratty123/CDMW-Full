"""Character dependency planning against the live archive catalogue.

The planner was written for a fully loaded archive list. With the standalone
catalogue there is no such list, so the plan is built from a bounded set:

1. the worker's character catalogue names the files related to the selected
   model, including the appearance descriptors that use it;
2. the planner runs over that set with recording indexes, which note every path
   and filename it looked for and did not find;
3. those paths and filenames are resolved through the worker and the planner
   runs again, until it asks for nothing new or a bound is reached.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from PySide6.QtCore import QObject

from cdmw.domain.archives.relationships import CharacterDependencyPlan
from cdmw.models import ArchiveEntry
from cdmw.services.archive_workflow_service import build_character_dependency_plan

#: Planner passes before the result is used as it stands.
MAX_PLANNING_ROUNDS = 4
#: Entries the bounded set may grow to; a larger graph is refused, not truncated.
MAX_PLANNING_ENTRIES = 24_000
#: Filenames one pass may ask the worker for.
MAX_LOOKUPS_PER_ROUND = 8_192

#: The worker's error text when the character catalogue has no row for a key.
CHARACTER_KEY_MISSING_TEXT = "Character catalogue result is unavailable"

ANIMATION_SCOPE_WARNING = (
    "Animation and motion files were matched only within the resolved character dependency set; "
    "files the appearance does not name are not searched for across the whole archive."
)


def character_catalogue_asset_key(path: str) -> str:
    """The worker's key for a model row: ``asset:`` and the normalized lower-case path."""

    return "asset:" + str(path or "").replace("\\", "/").strip().strip("/").lower()


def _normalized(path: str) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/").lower()


class _RecordingIndex(dict):
    """A planner index that remembers the keys it was asked for and did not have."""

    def __init__(self, data: Mapping[str, Sequence[ArchiveEntry]], misses: set[str]) -> None:
        super().__init__(data)
        self._misses = misses

    def get(self, key, default=None):
        value = super().get(key)
        if value is None:
            text = str(key or "").strip()
            if text:
                self._misses.add(text)
            return default
        return value


def planner_indexes(
    entries: Iterable[ArchiveEntry],
) -> tuple[dict[str, list[ArchiveEntry]], dict[str, list[ArchiveEntry]]]:
    """Path and basename indexes keyed exactly as the planner's own indexes are."""

    by_path: dict[str, list[ArchiveEntry]] = {}
    by_basename: dict[str, list[ArchiveEntry]] = {}
    for entry in entries:
        key = _normalized(entry.path)
        if not key:
            continue
        by_path.setdefault(key, []).append(entry)
        by_basename.setdefault(PurePosixPath(key).name, []).append(entry)
    return by_path, by_basename


@dataclass(frozen=True, slots=True)
class CharacterPlanningRound:
    plan: CharacterDependencyPlan
    missing_paths: frozenset[str]
    missing_basenames: frozenset[str]


def plan_character_dependencies_round(
    body_entry: ArchiveEntry,
    entries: Sequence[ArchiveEntry],
    *,
    selected_appearance_path: str = "",
    stop_event: object = None,
) -> CharacterPlanningRound:
    path_index, basename_index = planner_indexes(entries)
    missing_paths: set[str] = set()
    missing_basenames: set[str] = set()
    plan = build_character_dependency_plan(
        body_entry,
        tuple(entries),
        selected_appearance_path=selected_appearance_path,
        stop_event=stop_event,
        path_index=_RecordingIndex(path_index, missing_paths),
        basename_index=_RecordingIndex(basename_index, missing_basenames),
    )
    return CharacterPlanningRound(plan, frozenset(missing_paths), frozenset(missing_basenames))


def with_live_scope_warning(plan: CharacterDependencyPlan) -> CharacterDependencyPlan:
    if ANIMATION_SCOPE_WARNING in plan.warnings:
        return plan
    return replace(plan, warnings=(*plan.warnings, ANIMATION_SCOPE_WARNING))


class CatalogueCall(QObject):
    """One catalogue request whose result or failure goes to a callback."""

    def __init__(
        self,
        service: object,
        submit: Callable[[], str],
        *,
        on_result: Callable[[object], None],
        on_error: Callable[[str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._submit = submit
        self._on_result = on_result
        self._on_error = on_error
        self._request_id: str | None = None
        self._done = False

    def start(self) -> None:
        self._service.result_ready.connect(self._result)
        self._service.request_failed.connect(self._failed)
        self._service.request_cancelled.connect(self._cancelled)
        try:
            self._request_id = self._submit()
        except Exception as exc:
            self._finish()
            self._on_error(str(exc))

    def cancel(self) -> None:
        if self._done:
            return
        request_id = self._request_id
        self._finish()
        cancel = getattr(self._service, "cancel", None)
        if request_id is not None and callable(cancel):
            try:
                cancel(request_id)
            except Exception:
                pass

    def _result(self, request_id: str, _operation: str, payload: object) -> None:
        if self._done or request_id != self._request_id:
            return
        self._finish()
        self._on_result(payload)

    def _failed(self, request_id: str, error: object) -> None:
        if self._done or request_id != self._request_id:
            return
        self._finish()
        self._on_error(str(getattr(error, "message", "") or error or "The archive request failed."))

    def _cancelled(self, request_id: str) -> None:
        if self._done or request_id != self._request_id:
            return
        self._finish()
        self._on_error("The archive request was cancelled.")

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        for signal, handler in (
            (self._service.result_ready, self._result),
            (self._service.request_failed, self._failed),
            (self._service.request_cancelled, self._cancelled),
        ):
            try:
                signal.disconnect(handler)
            except (RuntimeError, TypeError):
                pass


__all__ = [
    "ANIMATION_SCOPE_WARNING",
    "CHARACTER_KEY_MISSING_TEXT",
    "MAX_LOOKUPS_PER_ROUND",
    "MAX_PLANNING_ENTRIES",
    "MAX_PLANNING_ROUNDS",
    "CatalogueCall",
    "CharacterPlanningRound",
    "character_catalogue_asset_key",
    "plan_character_dependencies_round",
    "planner_indexes",
    "with_live_scope_warning",
]
