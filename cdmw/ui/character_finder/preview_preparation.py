"""Prepare one catalogue selection through bounded resident-worker lookups."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from cdmw.domain.archives.catalogue import ArchiveLookupKind, ArchiveLookupRequest, ArchiveLookupResult
from cdmw.domain.archives.catalogue_operations import PrepareEntriesRequest, PrepareEntriesResult
from cdmw.domain.archives.character_catalogue import CharacterCatalogDetailResult
from cdmw.domain.character_finder import CharacterPreviewInputs
from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet, ArchiveRemotePreviewDependencyProvider


class CharacterPreviewPreparation(QObject):
    ready = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, service: object, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._provider = ArchiveRemotePreviewDependencyProvider(service, self)
        self._provider.ready.connect(self._model_ready)
        self._provider.failed.connect(self._failed)
        service.result_ready.connect(self._result)
        service.batch_ready.connect(self._batch)
        service.request_failed.connect(self._request_failed)
        service.request_cancelled.connect(self._request_cancelled)
        self._request = None
        self._detail = None
        self._token = 0

    def cancel(self) -> None:
        self._detail = None
        self._provider.cancel(clear_snapshot=True)
        request, self._request = self._request, None
        if request:
            self._service.cancel(request)

    def start(self, detail: CharacterCatalogDetailResult, token: int) -> None:
        self.cancel()
        self._token = token
        if not detail.models or detail.row.resolution == "ambiguous":
            self.failed.emit(token, "The model is unresolved or ambiguous. Inspect its files and resolution evidence.")
            return
        if len(detail.models) > 32:
            self.failed.emit(token, "This appearance exceeds the preview limit of 32 model components.")
            return
        self._detail = detail
        self._model_index = 0
        self._entries = {}
        self._models_by_id = {}
        self._complete = detail.total_file_count <= len(detail.files)
        self._prepared = {}
        self._extra_dtos = ()
        self._extra_lookup = {}
        self._next_model()

    def _next_model(self) -> None:
        detail = self._detail
        if detail is None:
            return
        if self._model_index < len(detail.models):
            model = detail.models[self._model_index]
            stems = tuple(c.name for c in detail.components if model.entry_id in c.model_entry_ids)
            self._provider.request(model, ui_request_id=self._token, preferred_prefab_stems=stems,
                                   scope_entry_ids=tuple(f.entry_id for f in detail.files))
            return
        # Authored PABC, morph, customization and appearance files can fall outside
        # the generic material closure. Retain and materialize those exact IDs too.
        known_paths = set(self._entries)
        extra = tuple(f.entry_id for f in detail.files if f.path.casefold() not in known_paths)
        self._extra_ids = set(extra)
        if not extra:
            self._publish()
            return
        try:
            self._request = self._service.resolve_entries(ArchiveLookupRequest(detail.session_id,
                ArchiveLookupKind.ENTRY_IDS, entry_ids=extra, limit=len(extra)), ui_generation=self._token)
        except Exception as error:
            self._failed(self._token, str(error))

    def _model_ready(self, token: int, snapshot: ArchivePreviewDependencySet) -> None:
        detail = self._detail
        if detail is None or token != self._token or self._model_index >= len(detail.models):
            return
        model = detail.models[self._model_index]
        if snapshot.session_id != detail.session_id or snapshot.entry_id != model.entry_id:
            return
        self._models_by_id[model.entry_id] = snapshot.selected_entry
        self._complete &= not snapshot.truncated
        for entry in snapshot.entries:
            self._entries.setdefault(entry.path.casefold(), entry)
        self._model_index += 1
        self._next_model()

    def _batch(self, request: str, _operation: str, result: object) -> None:
        if request == self._request and isinstance(result, ArchiveLookupResult):
            self._extra_lookup.update((entry.entry_id, entry) for entry in result.entries)
            self._complete &= not result.truncated
        elif request == self._request and isinstance(result, PrepareEntriesResult):
            for item in result.items:
                self._prepared[item.entry.entry_id] = item

    def _result(self, request: str, _operation: str, result: object) -> None:
        detail = self._detail
        if detail is None or request != self._request or getattr(result, "session_id", None) != detail.session_id:
            return
        self._request = None
        if isinstance(result, ArchiveLookupResult):
            self._extra_lookup.update((entry.entry_id, entry) for entry in result.entries)
            self._extra_dtos = tuple(self._extra_lookup.values())
            self._complete &= not result.truncated and self._extra_ids == set(self._extra_lookup)
            if not self._extra_dtos:
                self._complete = False
                self._publish()
                return
            try:
                self._request = self._service.prepare_entries(PrepareEntriesRequest(detail.session_id,
                    tuple(e.entry_id for e in self._extra_dtos)), ui_generation=self._token)
            except Exception as error:
                self._failed(self._token, str(error))
        elif isinstance(result, PrepareEntriesResult):
            for item in result.items:
                self._prepared[item.entry.entry_id] = item
            try:
                snapshot = ArchivePreviewDependencySet.from_dtos(self._extra_dtos[0], self._extra_dtos[1:],
                    total_candidates=len(self._extra_dtos), truncated=False, prepared=self._prepared)
                for dto, entry in zip(self._extra_dtos, snapshot.entries, strict=True):
                    self._models_by_id[dto.entry_id] = entry
                    self._entries.setdefault(entry.path.casefold(), entry)
                self._publish()
            except Exception as error:
                self._failed(self._token, str(error))

    def _publish(self) -> None:
        detail, self._detail = self._detail, None
        if detail is not None:
            # Context may already have arrived with a model's prepared material
            # closure. Preserve its catalogue ID as well as its path so the
            # renderer can follow the exact authored appearance descriptor.
            for file in detail.files:
                if (entry := self._entries.get(file.path.casefold())) is not None:
                    self._models_by_id.setdefault(file.entry_id, entry)
            self.ready.emit(self._token, CharacterPreviewInputs(detail, dict(self._models_by_id),
                tuple(self._entries.values()), self._complete))

    def _request_failed(self, request: str, error: object) -> None:
        if request == self._request:
            self._failed(self._token, str(getattr(error, "message", error)))

    def _request_cancelled(self, request: str) -> None:
        if request == self._request:
            self._failed(self._token, "Character preview preparation was cancelled.")

    def _failed(self, token: int, message: str) -> None:
        if token != self._token or self._detail is None:
            return
        self.cancel()
        self.failed.emit(token, message)
