"""Prepare the archive files Fit to body reads to find the body an outfit was made for.

The editor's archive sets are bounded per opened PAC: they hold each PAC's
skeleton candidates but no nude bodies, so the reference lookup could never
find the authored body from them. Before a Fit, list the nude folder of every
rig those sets name through the archive worker, prepare the body Placement &
Animations would choose there, and hand the Fit worker one merged set. The
GUI thread only issues requests; the Fit worker waits for the ticket.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QObject

from cdmw.domain.archives.catalogue import ArchivePage, ArchiveQuery, ArchiveQueryHandle
from cdmw.domain.archives.catalogue_operations import (
    ARCHIVE_BACKEND_MAXIMUM_PAGE_SIZE,
    FetchPageRequest,
    PrepareEntriesRequest,
    PrepareEntriesResult,
)
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.services.mesh_refit_reference_lookup import PreparedRefitReferenceArchive
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependencyContext,
)
from cdmw.ui.shell.tab_registry import DetachedToolWindow


def _normalized(value: object) -> str:
    return str(value or "").replace("\\", "/").strip("/").casefold()


def _merged(sets) -> ArchiveWorkflowDependencyContext:
    entries, seen = [], set()
    for context in sets:
        for entry in (context.selected_entry, *context.entries):
            if entry.identity not in seen:
                seen.add(entry.identity)
                entries.append(entry)
    return _dependency_context(entries)


def _dependency_context(entries) -> ArchiveWorkflowDependencyContext:
    paths, names = {}, {}
    for entry in entries:
        paths.setdefault(_normalized(entry.path), []).append(entry)
        names.setdefault(entry.basename.strip().casefold(), []).append(entry)
    return ArchiveWorkflowDependencyContext(
        entries[0], tuple(entries), {key: tuple(value) for key, value in paths.items()},
        {key: tuple(value) for key, value in names.items()}, True,
    )


def _rig_folders(context) -> tuple[str, ...]:
    """Folders of the character skeletons the sets offer, where a rig keeps its nude body."""
    folders = {
        str(PurePosixPath(path).parent) for path in context.entries_by_normalized_path
        if path.endswith(".pab") and path.startswith("character/model/")
    }
    return tuple(sorted(folders))


class RefitReferencePreparation(QObject):
    """GUI-owned and latest-wins; a Fit worker waits on the ticket it returns."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        service.result_ready.connect(self._result)
        service.batch_ready.connect(self._batch)
        service.request_failed.connect(self._failed)
        service.request_cancelled.connect(self._cancelled)
        service.session_published.connect(self._session_changed)
        self._ticket: PreparedRefitReferenceArchive | None = None
        self._request = None
        self._cache: OrderedDict[tuple, ArchiveWorkflowDependencyContext] = OrderedDict()

    def capture(self, sets) -> PreparedRefitReferenceArchive:
        self.cancel()
        ticket = PreparedRefitReferenceArchive()
        bounded = tuple(context for context in sets if isinstance(context, ArchiveWorkflowDependencyContext)
                        and context.remote)
        if not bounded:
            ticket.settle()  # Local sets index the whole archive already.
            return ticket
        session = self.service.current_session
        if session is None:
            ticket.settle(reason="the archive catalogue is not loaded")
            return ticket
        base = _merged(bounded)
        folders = _rig_folders(base)
        if not folders:
            ticket.settle(reason="the loaded PACs' archive files name no character skeleton")
            return ticket
        key = (session.session_id, tuple(sorted(str(entry.identity) for entry in base.entries)))
        if key in self._cache:
            self._cache.move_to_end(key)
            ticket.settle(self._cache[key])
            return ticket
        self._ticket, self._key, self._base, self._folders = ticket, key, base, folders
        self._session_id, self._bodies, self._prepared = session.session_id, {}, {}
        self._submit(lambda generation: self.service.create_query(ArchiveQuery(
            session.session_id, include_text=";".join(f"{folder}/nude/*.pac" for folder in folders),
            extensions=(".pac",)), ui_generation=generation))
        return ticket

    def cancel(self) -> None:
        self._abandon("the Fit was cancelled")

    def _abandon(self, reason: str) -> None:
        request, self._request = self._request, None
        self._settle(reason=reason)
        if request is not None:
            try:
                self.service.cancel(request)
            except (AttributeError, RuntimeError):
                pass  # The archive process may already be closing.

    def _submit(self, start) -> None:
        # Requests older than the catalogue's minimum generation are dropped unanswered.
        try:
            self._request = start(int(getattr(self.service, "_minimum_ui_generation", 0)))
        except Exception as error:
            self._request = None
            self._settle(reason=f"the archive worker could not list the authored bodies ({error})")

    def _settle(self, dependencies=None, reason: str = "") -> None:
        ticket, self._ticket = self._ticket, None
        if ticket is not None:
            ticket.settle(dependencies, reason)

    def _session_changed(self, *_args) -> None:
        self._cache.clear()
        if self._ticket is not None:
            self._abandon("the archive catalogue changed during the Fit")

    def _failed(self, request, error) -> None:
        if request == self._request:
            self._request = None
            self._settle(reason=f"the archive worker could not list the authored bodies "
                                f"({getattr(error, 'message', error)})")

    def _cancelled(self, request) -> None:
        if request == self._request:
            self._request = None
            self._settle(reason="the archive request for the authored bodies was cancelled")

    def _batch(self, request, _operation, payload) -> None:
        # The worker streams prepared files in batches and ends with an empty result.
        if request == self._request and self._ticket is not None and isinstance(payload, PrepareEntriesResult):
            self._collect(payload)

    def _collect(self, result: PrepareEntriesResult) -> None:
        sessions = {self._session_id, *(dto.session_id for dto in self._bodies.values())}
        for item in result.items:
            if result.session_id in sessions and item.entry.entry_id in self._bodies:
                self._prepared.setdefault(item.entry.entry_id, item)

    def _result(self, request, _operation, payload) -> None:
        if request != self._request or self._ticket is None:
            return
        self._request = None
        if isinstance(payload, ArchiveQueryHandle):
            if payload.total_matches <= 0:
                self._settle(reason="no nude body was found in the archive for "
                                    + ", ".join(PurePosixPath(folder).name for folder in self._folders))
                return
            self._submit(lambda generation: self.service.fetch_page(FetchPageRequest(
                payload.query_id, 0, min(payload.total_matches, ARCHIVE_BACKEND_MAXIMUM_PAGE_SIZE)),
                ui_generation=generation))
        elif isinstance(payload, ArchivePage):
            self._choose_bodies(payload.rows)
        elif isinstance(payload, PrepareEntriesResult):
            self._publish(payload)
        else:
            self._settle(reason="the archive worker returned an unexpected answer for the authored bodies")

    def _choose_bodies(self, rows) -> None:
        from cdmw.services.effect_character_reference import _body_mesh_paths

        for folder in self._folders:
            prefix = f"{folder}/nude/"
            candidates = {_normalized(row.path): row for row in rows if _normalized(row.path).startswith(prefix)}
            # The lookup asks the same chooser, so preparing its answer is enough.
            for path in _body_mesh_paths(candidates, {}, rig_model=PurePosixPath(folder).name):
                if path in candidates and "/nude/" in path:
                    self._bodies[candidates[path].entry_id] = candidates[path]
                    break
        if not self._bodies:
            self._settle(reason="no nude body was found in the archive for "
                                + ", ".join(PurePosixPath(folder).name for folder in self._folders))
            return
        self._submit(lambda generation: self.service.prepare_entries(
            PrepareEntriesRequest(self._session_id, tuple(self._bodies)), ui_generation=generation))

    def _publish(self, result: PrepareEntriesResult) -> None:
        self._collect(result)
        prepared = self._prepared
        if set(prepared) != set(self._bodies):
            self._settle(reason="the archive worker did not prepare the authored bodies")
            return
        entries = list(self._base.entries)
        for entry_id, dto in self._bodies.items():
            entry = ArchiveCatalogueService.compatibility_entry(dto)
            entry.prepared_path = Path(prepared[entry_id].prepared_path)
            entry.prepared_size = prepared[entry_id].size
            entry.prepared_sha256 = prepared[entry_id].sha256
            entries.append(entry)
        merged = _dependency_context(entries)
        self._cache[self._key] = merged
        while len(self._cache) > 4:
            self._cache.popitem(last=False)
        self._settle(merged)


def prepare_refit_fit_event(tab, session, event):
    """Attach the archive files Fit to body reads; returns at once."""
    args = dict(event.get("arguments") or {})
    if args.get("reference_body", True) is not True or "_reference_archive" in args:
        return event
    shadow = session.shadow_service._session(session.shadow_session_id)
    context = shadow.archive_refit_context
    if context is None:
        return event
    owner = tab.window()
    if isinstance(owner, DetachedToolWindow):
        owner = owner.owner
    service = getattr(getattr(owner, "archive", None), "archive_catalogue_service", None)
    sets = (getattr(tab, "archive_session_dependencies", None),
            *(getattr(getattr(asset, "preview_lease", None), "archive_dependencies", None)
              for asset in context.assets))
    preparation = getattr(tab, "_refit_reference_preparation", None)
    ticket = PreparedRefitReferenceArchive()
    if service is None:
        ticket.settle(reason="the archive catalogue is not loaded")
    else:
        try:
            if preparation is None or preparation.service is not service:
                preparation = RefitReferencePreparation(service, tab)
                tab._refit_reference_preparation = preparation
            ticket = preparation.capture(sets)
        except Exception as error:  # The Fit still runs, to the current body, and says why.
            ticket.settle(reason=f"the authored bodies could not be requested ({error})")
    return {**event, "arguments": {**args, "_reference_archive": ticket}}


__all__ = ["RefitReferencePreparation", "prepare_refit_fit_event"]
