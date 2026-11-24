"""Find a head or body for Hair Tools' Change references… by its archive path.

The chooser (``HairReferencePickerDialog``) lists the character's compatible heads or
bodies, and a click prepares the chosen one's files. An AI connection names the file
instead: this finds the same catalogue entry, checks it as the chooser checks its rows,
and prepares its files the same way, without opening any window.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from PySide6.QtCore import QObject, Signal

from cdmw.domain.archives.character_catalogue import CharacterCatalogDetailRequest, CharacterCatalogDetailResult
from cdmw.domain.hair_characters import hair_character
from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
from cdmw.ui.character_finder.preview_preparation import CharacterPreviewPreparation

#: The catalogue roles each chooser lists (as HairReferencePickerDialog._result filters them).
_ROLES = {"head": {"head"}, "body": {"body", "whole_character"}}


def not_offered(path: str, role: str, profile) -> str:
    if role == "head":
        return f"{path} is not one of {profile.name}'s heads that Change references offers."
    return f"{path} is not one of {profile.name}'s base bodies that Change references offers."


def reference_problem(row, role: str, profile) -> str:
    """Why the chooser would not list ``row`` for ``role``, or "" when it would."""

    path = str(getattr(row, "path", "") or "")
    if getattr(row, "model_count", 0) != 1 or getattr(row, "resolution", "") not in {"resolved", "inferred"}:
        return f"{path} is not one resolved model, so it cannot be a hair reference."
    if getattr(row, "body_family", "") != profile.reference_family:
        return f"{path} is not in {profile.name}'s body family, so it cannot be a hair reference."
    if getattr(row, "role", "") not in _ROLES[role] or not profile.accepts_reference(path.casefold(), role):
        return not_offered(path, role, profile)
    return ""


class HairReferenceResolution(QObject):
    """One head or body, from its path to the entry and files Change references uses."""

    #: entry, dependencies, error ("" when found).
    done = Signal(object, object, str)

    def __init__(self, owner, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = owner.archive.archive_catalogue_service
        self._prepare = CharacterPreviewPreparation(self._service, self)
        self._prepare.ready.connect(self._prepared)
        self._prepare.failed.connect(lambda _token, message: self._finish(error=str(message)))
        self._service.result_ready.connect(self._result)
        self._service.request_failed.connect(self._failed)
        self._request = None
        self._role = ""
        self._path = ""
        self._profile = None
        self._finished = False

    def start(self, role: str, path: str, character: str) -> None:
        if role not in _ROLES:
            raise ValueError("A hair reference is a head or a body.")
        self._role, self._path = role, str(PurePosixPath(str(path).replace("\\", "/").strip().strip("/")))
        self._profile = hair_character(character)
        session = self._service.current_session
        if session is None:
            self._finish(error="Load the archive catalogue first.")
            return
        if not self._profile.accepts_reference(self._path.casefold(), role):
            self._finish(error=not_offered(self._path, role, self._profile))
            return
        self._request = self._service.get_character_catalog_detail(
            CharacterCatalogDetailRequest(session.session_id, f"asset:{self._path}"), ui_generation=0)

    def cancel(self) -> None:
        request, self._request = self._request, None
        if request is not None:
            self._service.cancel(request)
        self._prepare.cancel()
        self._finished = True

    def _result(self, request, _operation, result) -> None:
        if self._finished or request != self._request or not isinstance(result, CharacterCatalogDetailResult):
            return
        self._request = None
        problem = reference_problem(result.row, self._role, self._profile)
        if not problem and len(result.models) != 1:
            problem = f"{self._path} is not one resolved model, so it cannot be a hair reference."
        if problem:
            self._finish(error=problem)
            return
        self._prepare.start(result, 1)

    def _failed(self, request, error) -> None:
        if self._finished or request != self._request:
            return
        self._request = None
        self._finish(error=f"{self._path}: {getattr(error, 'message', error)}")

    def _prepared(self, _token, inputs) -> None:
        if self._finished:
            return
        if not inputs.dependencies_complete or len(inputs.detail.models) != 1:
            self._finish(error=f"{self._path} has incomplete or ambiguous dependencies.")
            return
        # As the chooser's own Use selection (HairReferencePickerDialog._prepared).
        entry = inputs.entries_by_id[inputs.detail.models[0].entry_id]
        paths, names = {}, {}
        for item in inputs.entries:
            paths.setdefault(item.path.casefold(), []).append(item)
            names.setdefault(item.basename.casefold(), []).append(item)
        self._finish(entry, ArchiveWorkflowDependencyContext(entry, inputs.entries, paths, names, True))

    def _finish(self, entry=None, dependencies=None, error: str = "") -> None:
        if self._finished:
            return
        self._finished = True
        for signal, slot in ((self._service.result_ready, self._result), (self._service.request_failed, self._failed)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self.done.emit(entry, dependencies, error)


__all__ = ["HairReferenceResolution", "not_offered", "reference_problem"]
